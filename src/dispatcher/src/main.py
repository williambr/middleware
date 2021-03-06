#!/usr/local/bin/python2.7
#+
# Copyright 2014 iXsystems, Inc.
# All rights reserved
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted providing that the following conditions
# are met:
# 1. Redistributions of source code must retain the above copyright
#    notice, this list of conditions and the following disclaimer.
# 2. Redistributions in binary form must reproduce the above copyright
#    notice, this list of conditions and the following disclaimer in the
#    documentation and/or other materials provided with the distribution.
#
# THIS SOFTWARE IS PROVIDED BY THE AUTHOR ``AS IS'' AND ANY EXPRESS OR
# IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
# WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
# ARE DISCLAIMED.  IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR ANY
# DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
# DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS
# OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION)
# HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT,
# STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING
# IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
# POSSIBILITY OF SUCH DAMAGE.
#
#####################################################################


import os
import sys
import fnmatch
import glob
import imp
import json
import fcntl
import datetime
import logging
import logging.config
import logging.handlers
import argparse
import signal
import time
import uuid
import errno
import socket
import setproctitle
import traceback
import tempfile
import pty
import struct
import termios

import gevent
from pyee import EventEmitter
from gevent.os import tp_read, tp_write
from gevent import monkey, Greenlet
from gevent.queue import Queue
from gevent.lock import RLock
from gevent.subprocess import Popen
from gevent.event import AsyncResult, Event
from gevent.wsgi import WSGIServer
from geventwebsocket import (WebSocketServer, WebSocketApplication, Resource,
                             WebSocketError)

from datastore import get_datastore
from datastore.config import ConfigStore
from freenas.dispatcher.jsonenc import loads, dumps
from freenas.dispatcher.rpc import RpcContext, RpcException, ServerLockProxy, convert_schema
from resources import ResourceGraph
from services import ManagementService, DebugService, EventService, TaskService, PluginService, ShellService, LockService
from schemas import register_general_purpose_schemas
from api.handler import ApiHandler
from balancer import Balancer
from auth import PasswordAuthenticator, TokenStore, Token, TokenException, User, Service
from freenas.utils import FaultTolerantLogHandler


DEFAULT_CONFIGFILE = '/usr/local/etc/middleware.conf'
LOGGING_FORMAT = '%(asctime)s %(levelname)s %(filename)s:%(lineno)d %(message)s'
trace_log_file = None


def trace_log(message, *args):
    global trace_log_file

    if os.getenv('DISPATCHER_TRACE'):
        if not trace_log_file:
            try:
                trace_log_file = open('/var/tmp/dispatcher-trace.{0}.log'.format(os.getpid()), 'w')
            except OSError:
                pass

        print(message.format(*args), file=trace_log_file)
        trace_log_file.flush()


class Plugin(object):
    UNLOADED = 1
    LOADED = 2
    ERROR = 3

    def __init__(self, dispatcher, filename=None):
        self.filename = filename
        self.init = None
        self.dependencies = set()
        self.dispatcher = dispatcher
        self.module = None
        self.state = self.UNLOADED
        self.metadata = None
        self.registers = {
            'attach_hooks': [],
            'event_handlers': [],
            'event_sources': [],
            'event_types': [],
            'hooks': [],
            'providers': [],
            'resources': [],
            'schema_definitions': [],
            'task_handlers': [],
        }

    def assign_module(self, module):
        if not hasattr(module, '_init'):
            raise Exception('Invalid plugin module, _init method not found')

        if hasattr(module, '_depends'):
            self.dependencies = set(module._depends())

        if hasattr(module, '_metadata'):
            self.metadata = module._metadata()

        self.module = module

    def attach_hook(self, name, func):
        self.dispatcher.attach_hook(name, func)
        self.registers['attach_hooks'].append((name, func))

    def detach_hook(self, name, func):
        self.dispatcher.detach_hook(name, func)
        self.registers['attach_hooks'].remove((name, func))

    def load(self, dispatcher):
        try:
            self.module._init(self.dispatcher, self)
            self.state = self.LOADED
            self.dispatcher.dispatch_event('server.plugin.initialized', {"name": os.path.basename(self.filename)})
        except Exception as err:
            self.dispatcher.logger.exception('Plugin %s exception', self.filename)
            self.dispatcher.report_error('Cannot initalize plugin {0}'.format(self.filename), err)
            raise RuntimeError('Cannot load plugin {0}: {1}'.format(self.filename, str(err)))

    def register_event_handler(self, name, handler):
        self.dispatcher.register_event_handler(name, handler)
        self.registers['event_handlers'].append((name, handler))
        return handler

    def unregister_event_handler(self, name, handler):
        self.dispatcher.unregister_event_handler(name, handler)
        self.registers['event_handlers'].remove((name, handler))
        return handler

    def register_event_source(self, name, clazz):
        self.dispatcher.register_event_source(name, clazz)
        self.registers['event_sources'].append(name)

    def register_event_type(self, name, source=None, schema=None):
        self.dispatcher.register_event_type(name, source, schema)
        self.registers['event_types'].append(name)

    def unregister_event_type(self, name):
        self.dispatcher.unregister_event_type(name)
        self.registers['event_types'].remove(name)

    def register_task_handler(self, name, clazz):
        self.dispatcher.register_task_handler(name, clazz)
        self.registers['task_handlers'].append(name)

    def unregister_task_handler(self, name):
        self.dispatcher.unregister_task_handler(name)
        self.registers['task_handlers'].remove(name)

    def register_provider(self, name, clazz):
        self.dispatcher.register_provider(name, clazz)
        self.registers['providers'].append(name)

    def unregister_provider(self, name):
        self.dispatcher.unregister_provider(name)
        self.registers['providers'].remove(name)

    def register_schema_definition(self, name, definition):
        self.dispatcher.register_schema_definition(name, definition)
        self.registers['schema_definitions'].append(name)

    def unregister_schema_definition(self, name):
        self.dispatcher.unregister_schema_definition(name)
        self.registers['schema_definitions'].remove(name)

    def register_resource(self, res, parents=None):
        self.dispatcher.register_resource(res, parents)
        self.registers['resources'].append((res, parents))

    def unregister_resource(self, res):
        self.dispatcher.unregister_resource(res)
        self.registers['resources'].remove(res)

    def register_hook(self, name):
        self.dispatcher.register_hook(name)
        self.registers['hooks'].append(name)

    def unregister_hook(self, name):
        self.dispatcher.unregister_hook(name)
        self.registers['hooks'].remove(name)

    def unload(self):
        if hasattr(self.module, '_cleanup'):
            self.module._cleanup(self.dispatcher, self)

        self.dispatcher.logger.debug('Unregistering plugin {0} types'.format(
            self.filename
        ))

        for name, handler in list(self.registers['event_handlers']):
            self.unregister_event_handler(name, handler)

        #for name in self.registers['event_sources']:
        #    pass

        for name in list(self.registers['event_types']):
            self.unregister_event_type(name)

        for name, func in list(self.registers['attach_hooks']):
            self.detach_hook(name, func)

        for name in list(self.registers['hooks']):
            self.unregister_hook(name)

        for name in list(self.registers['providers']):
            self.unregister_provider(name)

        for name in list(self.registers['resources']):
            self.unregister_resource(name)

        for name in list(self.registers['schema_definitions']):
            self.unregister_schema_definition(name)

        for name in list(self.registers['task_handlers']):
            self.unregister_task_handler(name)

        self.state = self.UNLOADED

    def reload(self):
        self.unload()
        self.load(self.dispatcher)


class EventType(object):
    def __init__(self, name, source=None, schema=None):
        self.name = name
        self.source = source
        self.schema = schema
        self.refcount = 0
        self.logger = logging.getLogger('EventType:{0}'.format(name))

    def incref(self):
        if self.refcount == 0 and self.source:
            self.source.enable(self.name)
            self.logger.debug('Enabling event source: {0}'.format(self.name))

        self.refcount += 1

    def decref(self):
        # lets not go below 0!!!
        if self.refcount > 0:
            self.refcount -= 1
        elif self.refcount < 0:
            # Ok so something is messed up
            # fix it by going to 0
            self.refcount = 0
            self.logger.error(
                "{0}'s refcount was below zero and was being decreased even further!".format(self.name))
            return
        elif self.refcount == 0:
            self.logger.error("Cannot decrease {0}'s refcount below zero!".format(self.name))
            return

        if self.refcount == 0 and self.source:
            self.source.disable(self.name)
            self.logger.debug('Disabling event source: {0}'.format(self.name))


class Dispatcher(object):
    def __init__(self):
        self.started_at = None
        self.plugin_dirs = []
        self.event_types = {}
        self.event_sources = {}
        self.event_handlers = {}
        self.hooks = {}
        self.plugins = {}
        self.threads = []
        self.queues = {}
        self.providers = {}
        self.tasks = {}
        self.resource_graph = ResourceGraph()
        self.logger = logging.getLogger('Main')
        self.token_store = TokenStore(self)
        self.event_delivery_lock = RLock()
        self.rpc = None
        self.balancer = None
        self.datastore = None
        self.auth = None
        self.ws_servers = []
        self.http_servers = []
        self.pidfile = None
        self.use_tls = False
        self.certfile = None
        self.keyfile = None
        self.ready = Event()
        self.port = 0

    def init(self):
        self.logger.info('Initializing')
        self.datastore = get_datastore(
            self.config['datastore']['driver'],
            self.config['datastore']['dsn']
        )

        self.configstore = ConfigStore(self.datastore)
        self.logger.info('Connected to datastore')
        self.require_collection('events', 'serial', type='log')
        self.require_collection('sessions', 'serial', type='log')
        self.require_collection('tasks', 'serial', type='log')
        self.require_collection('logs', 'uuid', type='log')

        self.balancer = Balancer(self)
        self.auth = PasswordAuthenticator(self)
        self.rpc = ServerRpcContext(self)
        register_general_purpose_schemas(self)

        self.rpc.register_service('management', ManagementService)
        self.rpc.register_service('debug', DebugService)
        self.rpc.register_service('event', EventService)
        self.rpc.register_service('task', TaskService)
        self.rpc.register_service('plugin', PluginService)
        self.rpc.register_service('shell', ShellService)
        self.rpc.register_service('lock', LockService)

        self.register_event_type('server.client_connected')
        self.register_event_type('server.client_transport_connected')
        self.register_event_type('server.client_disconnected')
        self.register_event_type('server.client_login')
        self.register_event_type('server.client_logout')
        self.register_event_type('server.service_login')
        self.register_event_type('server.service_logout')
        self.register_event_type('server.plugin.load_error')
        self.register_event_type('server.plugin.loaded')
        self.register_event_type('server.ready')
        self.register_event_type('server.shutdown')

    def start(self):
        self.started_at = time.time()
        self.balancer.start()

        self.ready.set()

        self.dispatch_event('server.ready', {
            'description': 'Server is completely loaded and ready to use.',
        })

    def read_config_file(self, file):
        try:
            f = open(file, 'r')
            data = json.load(f)
            f.close()
        except (IOError, ValueError):
            raise

        self.config = data
        self.plugin_dirs = data['dispatcher']['plugin-dirs']
        self.pidfile = data['dispatcher']['pidfile']

        if 'tls' in data['dispatcher'] and data['dispatcher']['tls']:
            self.use_tls = True
            self.certfile = data['dispatcher']['tls-certificate']
            self.keyfile = data['dispatcher']['tls-keyfile']

    def discover_plugins(self):
        for dir in self.plugin_dirs:
            self.logger.debug("Searching for plugins in %s", dir)
            self.__discover_plugin_dir(dir)

    def load_plugins(self):
        loaded = set()
        toload = self.plugins.copy()
        loadlist = []

        while len(toload) > 0:
            found = False
            for name, plugin in list(toload.items()):
                if len(plugin.dependencies - loaded) == 0:
                    found = True
                    loadlist.append(plugin)
                    loaded.add(name)
                    del toload[name]

            if not found:
                self.logger.warning(
                    "Could not load following plugins due to circular dependencies: {0}".format(', '.join(toload)))
                break

        for i in loadlist:
            try:
                i.load(self)
            except RuntimeError as err:
                self.logger.exception("Error initializing plugin %s: %s", i.filename, err.args)

    def reload_plugins(self):
        # Reload existing modules
        for i in list(self.plugins.values()):
            i.reload()

        # And look for new ones
        self.discover_plugins()

    def unload_plugins(self):
        # Generate a list of inverse plugin dependency
        required_by = {}
        for name, plugin in list(self.plugins.items()):
            if name not in required_by:
                required_by[name] = set()
            for dep in plugin.dependencies:
                if dep not in required_by:
                    required_by[dep] = set()
                required_by[dep].add(name)

        # Get a sequential list of plugins to unload
        # Plugins that no other depend on come first
        unloadlist = []
        while len(required_by) > 0:
            found = False
            for name, deps in list(required_by.items()):
                if len(deps) > 0:
                    continue

                # Remove the plugin from the list that it depends on
                plugin = self.plugins.get(name)
                for dep in plugin.dependencies:
                    if dep in required_by and name in required_by[dep]:
                        required_by[dep].remove(name)
                unloadlist.append(plugin)

                del required_by[name]
                found = True
                break

            if not found:
                self.logger.warning(
                    "Could not unload following plugins due to circular "
                    "dependencies: {0}".format(required_by)
                )
                break

        for i in unloadlist:
            try:
                i.unload()
            except RuntimeError:
                self.logger.warning(
                    "Error unloading plugin {0}".format(i.filename),
                    exc_info=True
                )

    def __discover_plugin_dir(self, dir):
        for i in glob.glob1(dir, "*.py"):
            self.__try_load_plugin(os.path.join(dir, i))

    def __try_load_plugin(self, path):
        if path in self.plugins:
            return

        self.logger.debug("Loading plugin from %s", path)
        try:
            name = os.path.splitext(os.path.basename(path))[0]
            plugin = Plugin(self, path)
            plugin.assign_module(imp.load_source(name, path))
            self.plugins[name] = plugin
        except Exception as err:
            self.logger.exception("Cannot load plugin from %s", path)
            self.report_error('Cannot load plugin from {0}'.format(path), err)
            self.dispatch_event("server.plugin.load_error", {"name": os.path.basename(path)})
            return

        self.dispatch_event("server.plugin.loaded", {"name": os.path.basename(path)})

    def __on_service_started(self, args):
        if args['name'] == 'syslog':
            try:
                self.__init_syslog()
                self.unregister_event_handler('service.started', self.__on_service_started)
            except IOError as err:
                self.logger.warning('Cannot initialize syslog: %s', str(err))

    def __init_syslog(self):
        handler = logging.handlers.SysLogHandler('/var/run/log', facility='local3')
        logging.root.setLevel(logging.DEBUG)
        logging.root.addHandler(handler)

    def dispatch_event(self, name, args):
        with self.event_delivery_lock:
            if 'timestamp' not in args:
                # If there's no timestamp, assume event fired right now
                args['timestamp'] = time.time()

            for srv in self.ws_servers:
                srv.broadcast_event(name, args)

            if name in self.event_handlers:
                for h in self.event_handlers[name]:
                    try:
                        gevent.spawn(h, args)
                    except BaseException as err:
                        self.report_error('Event handler for event {0} failed'.format(name), err)
                        self.logger.exception('Event handler for event %s failed', name)

            if 'nolog' in args and args['nolog']:
                return

            # Persist event
            event_data = args.copy()
            del event_data['timestamp']

            self.datastore.insert('events', {
                'name': name,
                'timestamp': args['timestamp'],
                'args': event_data
            })

    def call_sync(self, name, *args, **kwargs):
        return self.rpc.call_sync(name, *args)

    def call_task_sync(self, name, *args):
        t = self.balancer.run_subtask(None, name, args)
        self.balancer.join_subtasks(t)
        return t.result

    def submit_task(self, name, *args):
        self.balancer.run_subtask(None, name, args)

    def verify_subtask(self, *args, **kwargs):
        return self.balancer.verify_subtask(*args, **kwargs)

    def register_event_handler(self, name, handler):
        if name not in self.event_handlers:
            self.event_handlers[name] = []

        self.event_handlers[name].append(handler)
        return handler

    def unregister_event_handler(self, name, handler):
        self.event_handlers[name].remove(handler)

    def register_event_source(self, name, clazz):
        self.logger.debug("New event source: %s", name)
        self.event_sources[name] = clazz

        source = clazz(self)
        greenlet = gevent.spawn(source.run)
        self.threads.append(greenlet)

    def register_event_type(self, name, source=None, schema=None):
        self.event_types[name] = EventType(name, source, schema)
        self.dispatch_event('server.event.added', {'name': name})

    def unregister_event_type(self, name):
        del self.event_types[name]
        self.dispatch_event('server.event.removed', {'name': name})

    def register_task_handler(self, name, clazz):
        self.logger.debug("New task handler: %s", name)
        self.tasks[name] = clazz

    def unregister_task_handler(self, name):
        del self.tasks[name]

    def register_provider(self, name, clazz):
        self.logger.debug("New provider: %s", name)
        self.providers[name] = clazz
        self.rpc.register_service(name, clazz)

    def unregister_provider(self, name):
        self.logger.debug("Unregistering provider: %s", name)
        self.rpc.unregister_service(name)
        del self.providers[name]

    def register_schema_definition(self, name, definition):
        self.rpc.register_schema_definition(name, definition)

    def unregister_schema_definition(self, name):
        self.rpc.unregister_schema_definition(name)

    def require_collection(self, collection, pkey_type='uuid', **kwargs):
        self.datastore.collection_create(collection, pkey_type, kwargs)

    def register_resource(self, res, parents=None):
        self.logger.debug('Resource added: {0}'.format(res.name))
        self.resource_graph.add_resource(res, parents)

    def update_resource(self, name, new_parents):
        self.logger.debug('Resource updated: {0}, new parents: {1}'.format(name, ', '.join(new_parents)))
        self.resource_graph.update_resource(name, new_parents)

    def unregister_resource(self, name):
        self.logger.debug('Resource removed: {0}'.format(name))
        self.resource_graph.remove_resource(name)

    def resource_exists(self, name):
        return self.resource_graph.get_resource(name) is not None

    def register_hook(self, name):
        if name not in self.hooks:
            self.hooks[name] = []

    def unregister_hook(self, name):
        del self.hooks[name]

    def attach_hook(self, name, func):
        self.register_hook(name)
        self.hooks[name].append(func)
        return func

    def detach_hook(self, name, func):
        self.hooks[name].remove(func)

    def run_hook(self, name, args):
        for h in self.hooks[name]:
            try:
                if not h(args):
                    return False
            except BaseException as err:
                self.report_error('Hook for {0} with args {1} failed'.format(name, args), err)
                return False

        return True

    def test_or_wait_for_event(self, event, match_fn, initial_condition_fn, timeout=None):
        done = Event()
        self.event_delivery_lock.acquire()

        if initial_condition_fn():
            self.event_delivery_lock.release()
            return

        def handler(args):
            if match_fn(args):
                self.logger.debug("Test or wait condition satisfied for event {0}".format(event))
                done.set()

        self.register_event_handler(event, handler)
        self.event_delivery_lock.release()
        done.wait(timeout=timeout)
        self.unregister_event_handler(event, handler)

    def exec_and_wait_for_event(self, event, match_fn, fn, timeout=None):
        done = Event()
        self.event_delivery_lock.acquire()

        try:
            fn()
        except:
            self.event_delivery_lock.release()
            raise

        def handler(args):
            if match_fn(args):
                self.logger.debug("Exec and wait condition satisfied for event {0}".format(event))
                done.set()

        self.register_event_handler(event, handler)
        self.event_delivery_lock.release()
        done.wait(timeout=timeout)
        self.unregister_event_handler(event, handler)

    def get_lock(self, name):
        self.call_sync('lock.init', name)
        return ServerLockProxy(self, name)

    def report_error(self, message, exception):
        if not os.path.isdir('/var/tmp/crash'):
            try:
                os.mkdir('/var/tmp/crash')
            except:
                # at least we tried
                return

        report = {
            'timestamp': str(datetime.datetime.now()),
            'type': 'exception',
            'application': 'dispatcher',
            'message': message,
            'exception': str(exception),
            'traceback': traceback.format_exc()
        }

        try:
            with tempfile.NamedTemporaryFile(dir='/var/tmp/crash', suffix='.json', prefix='report-', delete=False) as f:
                json.dump(report, f, indent=4)
        except:
            # at least we tried
            pass

    def die(self):
        self.logger.warning('Exiting from "die" command')

        self.dispatch_event('server.shutdown', {
            'description': 'Server is shutting down.',
        })

        self.balancer.dispose_executors()
        gevent.killall(self.threads)
        self.logger.warning('Unloading plugins')
        self.unload_plugins()
        sys.exit(0)


class ServerRpcContext(RpcContext):
    def __init__(self, dispatcher):
        super(ServerRpcContext, self).__init__()
        self.dispatcher = dispatcher

    def call_sync(self, name, *args):
        svcname, _, method = name.rpartition('.')
        svc = self.get_service(svcname)
        if svc is None:
            raise RpcException(errno.ENOENT, 'Service {0} not found'.format(svcname))

        if not hasattr(svc, method):
            raise RpcException(errno.ENOENT, 'Method {0} in service {1} not found'.format(method, svcname))

        return getattr(svc, method)(*args)


class ServerResource(Resource):
    def __init__(self, apps=None, dispatcher=None):
        super(ServerResource, self).__init__(apps)
        self.dispatcher = dispatcher

    def __call__(self, environ, start_response):
        environ = environ
        current_app = self._app_by_path(environ['PATH_INFO'], 'wsgi.websocket' in environ)

        if current_app is None:
            raise Exception("No apps defined")

        if 'wsgi.websocket' in environ:
            ws = environ['wsgi.websocket']
            current_app = current_app(ws, self.dispatcher)
            current_app.ws = ws  # TODO: needed?
            current_app.handle()

            return None
        else:
            return current_app(environ, start_response)


class Server(WebSocketServer):
    def __init__(self, *args, **kwargs):
        super(Server, self).__init__(*args, **kwargs)
        self.connections = []

    def broadcast_event(self, event, args):
        for i in self.connections:
            i.emit_event(event, args)


class UnixSocketServer(object):
    class UnixSocketHandler(object):
        def __init__(self, server, dispatcher, connfd, address):
            import types
            self.dispatcher = dispatcher
            self.fd = connfd.makefile('rwb')
            self.address = address
            self.server = server
            self.handler = types.SimpleNamespace()
            self.handler.client_address = ("unix", 0)
            self.handler.server = server
            self.conn = None

        def send(self, message):
            data = message.encode('utf-8')
            header = struct.pack('II', 0xdeadbeef, len(data))
            self.fd.write(header)
            self.fd.write(data)
            self.fd.flush()

        def handle_connection(self):
            self.conn = ServerConnection(self, self.dispatcher)
            self.conn.on_open()

            while True:
                header = self.fd.read(8)
                if header == b'' or len(header) != 8:
                    self.server.logger.info('Message wrong header dropped; closing connection')
                    break

                magic, length = struct.unpack('II', header)
                if magic != 0xdeadbeef:
                    self.server.logger.info('Message with wrong magic dropped')
                    continue

                msg = self.fd.read(length)
                if msg == b'' or len(msg) != length:
                    self.server.logger.info('Message with wrong length dropped; closing connection')
                    break

                self.conn.on_message(msg)

            self.conn.on_close('Bye bye')
            self.fd.close()

    def __init__(self, path, dispatcher):
        self.path = path
        self.dispatcher = dispatcher
        self.sockfd = None
        self.backlog = 50
        self.logger = logging.getLogger('UnixSocketServer')
        self.connections = []

    def broadcast_event(self, event, args):
        for i in self.connections:
            i.emit_event(event, args)

    def serve_forever(self):
        try:
            if os.path.exists(self.path):
                os.unlink(self.path)

            self.sockfd = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            self.sockfd.bind(self.path)
            self.sockfd.listen(self.backlog)
        except OSError as err:
            self.logger.error('Cannot start socket server: {0}'.format(str(err)))
            return

        while True:
            try:
                fd, addr = self.sockfd.accept()
            except OSError as err:
                self.logger.error('accept() failed: {0}'.format(str(err)))
                continue

            handler = self.UnixSocketHandler(self, self.dispatcher, fd, addr)
            gevent.spawn(handler.handle_connection)


class ServerConnection(WebSocketApplication, EventEmitter):
    def __init__(self, ws, dispatcher):
        super(ServerConnection, self).__init__(ws)
        self.server = ws.handler.server
        self.dispatcher = dispatcher
        self.server_pending_calls = {}
        self.client_pending_calls = {}
        self.resource = None
        self.user = None
        self.session_id = None
        self.token = None
        self.event_masks = set()
        self.rlock = RLock()
        self.event_subscription_lock = RLock()
        self.has_external_transport = False
        self.real_client_address = None

    def on_open(self):
        self.real_client_address = self.ws.handler.client_address
        client_addr, client_port = self.real_client_address[:2]
        trace_log('Client {0} connected', self.real_client_address)
        self.server.connections.append(self)
        self.dispatcher.dispatch_event('server.client_connected', {
            'address': client_addr,
            'port': client_port,
            'description': "Client {0} connected".format(self.real_client_address)
        })

    def on_close(self, reason):
        client_addr, client_port = self.real_client_address[:2]
        trace_log('Client {0} disconnected', self.real_client_address)
        self.server.connections.remove(self)

        if self.user:
            self.close_session()

        for mask in self.event_masks:
            for name, ev in list(self.dispatcher.event_types.items()):
                if fnmatch.fnmatch(name, mask):
                    ev.decref()

        self.dispatcher.dispatch_event('server.client_disconnected', {
            'address': client_addr,
            'port': client_port,
            'description': "Client {0} disconnected".format(self.real_client_address)
        })

    def on_message(self, message, *args, **kwargs):
        trace_log('{0} -> {1}', self.real_client_address, str(message))

        if not type(message) is bytes:
            return

        try:
            message = loads(message.decode('utf-8'))
        except ValueError:
            self.emit_rpc_error(None, errno.EINVAL, 'Request is not valid JSON')
            return

        if 'namespace' not in message:
            self.emit_rpc_error(None, errno.EINVAL, 'Invalid request')
            return

        try:
            method = getattr(self, "on_{}_{}".format(message["namespace"], message["name"]))
        except AttributeError:
            self.emit_rpc_error(None, errno.EINVAL, 'Invalid request')
            return

        method(message["id"], message["args"])

    def on_transport_setup(self, id, client_address):
        self.has_external_transport = True
        trace_log('Client transport layer set up - client {0} is from now on client {1}', self.real_client_address, client_address)
        self.dispatcher.dispatch_event('server.client_transport_connected', {
            'old_address': self.real_client_address,
            'new_address': client_address,
            'description': "Client transport layer set up - client {0} is from now on client {1}".format(self.real_client_address, client_address)
        })
        self.real_client_address = client_address

    def on_events_subscribe(self, id, event_masks):
        if not isinstance(event_masks, list):
            return

        if self.user is None:
            return

        # Keep session alive
        if self.token:
            try:
                self.dispatcher.token_store.keepalive_token(self.token)
            except TokenException:
                # Token expired, logout user
                self.logout('Logged out due to inactivity period')
                return

        with self.event_subscription_lock:
            # Increment reference count for any newly subscribed event
            for mask in set.difference(set(event_masks), self.event_masks):
                for name, ev in list(self.dispatcher.event_types.items()):
                    if fnmatch.fnmatch(name, mask):
                        ev.incref()

            self.event_masks = set.union(self.event_masks, set(event_masks))

    def on_events_unsubscribe(self, id, event_masks):
        if not isinstance(event_masks, list):
            return

        if self.user is None:
            return

        # Keep session alive
        if self.token:
            try:
                self.dispatcher.token_store.keepalive_token(self.token)
            except TokenException:
                # Token expired, logout user
                self.logout('Logged out due to inactivity period')
                return

        with self.event_subscription_lock:
            # Decrement reference count for any newly unsubscribed event
            intersecting_unsubscribe_events = set.intersection(set(event_masks), self.event_masks)
            for mask in intersecting_unsubscribe_events:
                for name, ev in list(self.dispatcher.event_types.items()):
                    if fnmatch.fnmatch(name, mask):
                        ev.decref()

            self.event_masks = set.difference(self.event_masks, intersecting_unsubscribe_events)

    def on_events_event(self, id, data):
        if self.user is None:
            return

        # Keep session alive
        if self.token:
            try:
                self.dispatcher.token_store.keepalive_token(self.token)
            except TokenException:
                # Token expired, logout user
                self.logout('Logged out due to inactivity period')
                return

        self.dispatcher.dispatch_event(data['name'], data['args'])

    def on_events_event_burst(self, id, data):
        if self.user is None:
            return

        # Keep session alive
        if self.token:
            try:
                self.dispatcher.token_store.keepalive_token(self.token)
            except TokenException:
                # Token expired, logout user
                self.logout('Logged out due to inactivity period')
                return

        if 'events' not in data:
            return

        for i in data['events']:
            self.dispatcher.dispatch_event(i['name'], i['args'])

    def on_rpc_auth_service(self, id, data):
        client_addr, client_port = self.real_client_address[:2]
        service_name = data['name']

        if client_addr not in ('127.0.0.1', '::1', 'unix') and not self.has_external_transport:
            return

        self.send_json({
            'namespace': 'rpc',
            'name': 'response',
            'id': id,
            'args': []
        })

        self.user = self.dispatcher.auth.get_service(service_name)
        self.open_session()
        self.dispatcher.dispatch_event('server.service_login', {
            'address': client_addr,
            'port': client_port,
            'name': service_name,
            'description': "Service {0} logged in".format(service_name)
        })

    def on_rpc_auth_token(self, id, data):
        token = data['token']
        resource = data.get('resource', None)
        lifetime = self.dispatcher.configstore.get("middleware.token_lifetime")
        token = self.dispatcher.token_store.lookup_token(token)
        client_addr, client_port = self.real_client_address[:2]

        if not token:
            self.emit_rpc_error(id, errno.EACCES, "Incorrect or expired token")
            return

        self.user = token.user
        self.token = self.dispatcher.token_store.issue_token(
            Token(
                user=self.user,
                lifetime=lifetime,
                revocation_function=self.logout
            )
        )

        self.send_json({
            'namespace': 'rpc',
            'name': 'response',
            'id': id,
            'args': [self.token, lifetime, self.user.name]
        })

        self.open_session()
        self.dispatcher.dispatch_event('server.client_loggin', {
            'address': client_addr,
            'port': client_port,
            'username': self.user.name,
            'description': "Client {0} logged in".format(self.user.name)
        })

    def on_rpc_auth(self, id, data):
        username = data['username']
        password = data['password']
        lifetime = self.dispatcher.configstore.get("middleware.token_lifetime")
        self.resource = data.get('resource', None)
        client_addr, client_port = self.real_client_address[:2]

        user = self.dispatcher.auth.get_user(username)

        if user is None:
            self.emit_rpc_error(id, errno.EACCES, "Incorrect username or password")
            return

        if client_addr in ('127.0.0.1', '::1', 'unix') or self.has_external_transport:
            # If client is connecting from localhost, omit checking password
            # and instead verify his username using sockstat(1). Also make
            # token lifetime None for such users (as we do not want their
            # sessions to timeout)
            # If client is connecting using transport layer other than raw ws
            # authentication part is held by transport layer itself so we do not
            # check password correctness but be aware such users sessions will timeout.
            if not self.has_external_transport and client_addr != 'unix':
                if not user.check_local(client_addr, client_port, self.dispatcher.port):
                    self.emit_rpc_error(id, errno.EACCES, "Incorrect username or password")
                    return
                lifetime = None
        else:
            if not user.check_password(password):
                self.emit_rpc_error(id, errno.EACCES, "Incorrect username or password")
                return

        self.user = user
        self.token = self.dispatcher.token_store.issue_token(Token(
            user=user,
            lifetime=lifetime,
            revocation_function=self.logout
        ))

        self.send_json({
            "namespace": "rpc",
            "name": "response",
            "id": id,
            "args": [self.token, lifetime, self.user.name]
        })

        self.open_session()
        self.dispatcher.dispatch_event('server.client_login', {
            'address': client_addr,
            'port': client_port,
            'username': username,
            'description': "Client {0} logged in".format(username)
        })

    def on_rpc_response(self, id, data):
        if id not in list(self.client_pending_calls.keys()):
            return

        call = self.client_pending_calls[id]
        if call['callback'] is not None:
            call['callback'](*data)

        if call['event'] is not None:
            call['event'].set(data)

        del self.client_pending_calls[id]

    def on_rpc_error(self, id, data):
        if id not in list(self.client_pending_calls.keys()):
            return

        call = self.client_pending_calls[id]
        if call['event'] is not None:
            call['event'].set_exception(RpcException(data['code'], data['message']))

        del self.client_pending_calls[id]

    def on_rpc_call(self, id, data):
        def dispatch_call_async(id, method, args):
            try:
                result = self.dispatcher.rpc.dispatch_call(method, args, sender=self)
            except RpcException as err:
                self.send_json({
                    "namespace": "rpc",
                    "name": "error",
                    "id": id,
                    "timestamp": time.time(),
                    "args": {
                        "code": err.code,
                        "message": err.message,
                        "extra": err.extra
                    }
                })
            else:
                self.send_json({
                    "namespace": "rpc",
                    "name": "response",
                    "id": id,
                    "timestamp": time.time(),
                    "args": result
                })

        if self.user is None:
            self.emit_rpc_error(id, errno.EACCES, 'Not logged in')
            return

        # Keep session alive
        if self.token:
            try:
                self.dispatcher.token_store.keepalive_token(self.token)
            except TokenException:
                # Token expired, logout user
                self.logout('Logged out due to inactivity period')
                return

        method = data["method"]
        args = data["args"]

        greenlet = Greenlet(dispatch_call_async, id, method, args)
        self.server_pending_calls[id] = {
            "method": method,
            "args": args,
            "greenlet": greenlet
        }

        greenlet.start()

    def open_session(self):
        client_addr, client_port = self.real_client_address[:2]
        self.session_id = self.dispatcher.datastore.insert('sessions', {
            'started-at': time.time(),
            'address': client_addr,
            'port': client_port,
            'resource': self.resource,
            'active': True,
            'username': self.user.name
        })

    def close_session(self):
        client_addr, client_port = self.real_client_address[:2]
        session = self.dispatcher.datastore.get_by_id('sessions', self.session_id)
        session['active'] = False
        session['ended-at'] = time.time()
        self.dispatcher.datastore.update('sessions', self.session_id, session)

        if isinstance(self.user, User):
            self.dispatcher.dispatch_event('server.client_logout', {
                'address': client_addr,
                'port': client_port,
                'username': self.user.name,
                'description': "Client {0} logged out".format(self.user.name)
            })

        elif isinstance(self.user, Service):
            self.dispatcher.dispatch_event('server.service_logout', {
                'address': client_addr,
                'port': client_port,
                'name': self.user.name,
                'description': "Client {0} logged out".format(self.user.name)
            })

    def broadcast_event(self, event, args):
        for i in self.server.connections:
            i.emit_event(event, args)

    def call_client(self, method, callback, *args):
        id = uuid.uuid4()
        event = AsyncResult()
        self.client_pending_calls[str(id)] = {
            "method": method,
            "args": args,
            "callback": callback,
            "event": event
        }

        self.emit_rpc_call(id, method, args)
        return event

    def logout(self, reason):
        args = {
            "reason": reason,
        }
        try:
            self.send_json({
                "namespace": "events",
                "name": "logout",
                "timestamp": time.time(),
                "id": None,
                "args": args
            })
            # Delete the token at logout since otherwise
            # the reconnect will just log the session back in
            self.dispatcher.token_store.revoke_token(self.token)
            self.ws.close()
        except WebSocketError as werr:
            # This error usually implies that the socket is dead
            # so just log it and move on
            self.dispatcher.logger.debug(
                'Tried to logout Websocket Connection and the ' +
                'following error occured {0}'.format(str(werr)))

    def call_client_sync(self, method, *args, **kwargs):
        timeout = kwargs.pop('timeout', None)
        event = self.call_client(method, None, *args)
        return event.get(timeout=timeout)

    def emit_event(self, event, args):
        for i in self.event_masks:
            if not fnmatch.fnmatch(event, i):
                continue

            self.send_json({
                "namespace": "events",
                "name": "event",
                "id": None,
                "args": {
                    "name": event,
                    "args": args
                }
            })

    def emit_rpc_call(self, id, method, args):
        payload = {
            "namespace": "rpc",
            "name": "call",
            "id": str(id),
            "args": {
                "method": method,
                "args": args
            }
        }

        return self.send_json(payload)

    def emit_rpc_error(self, id, code, message, extra=None):
        payload = {
            "namespace": "rpc",
            "name": "error",
            "id": str(id),
            "args": {
                "code": code,
                "message": message
            }
        }

        if extra is not None:
            payload['args'].update(extra)

        return self.send_json(payload)

    def send_json(self, obj):
        try:
            data = dumps(obj)
        except UnicodeDecodeError as e:
            self.dispatcher.logger.error('Error encoding following payload to JSON:')
            self.dispatcher.logger.error(repr(obj))
            return

        trace_log('{0} <- {1}', self.real_client_address, data)

        with self.rlock:
            try:
                self.ws.send(data)
            except WebSocketError as err:
                self.dispatcher.logger.error(
                    'Cannot send message to %s: %s', self.real_client_address, str(err))


class ShellConnection(WebSocketApplication, EventEmitter):
    BUFSIZE = 1024

    def __init__(self, ws, dispatcher):
        super(ShellConnection, self).__init__(ws)
        self.dispatcher = dispatcher
        self.logger = logging.getLogger('ShellConnection')
        self.authenticated = False
        self.master = None
        self.slave = None
        self.proc = None
        self.inq = Queue()

    def worker(self, user, shell):
        self.logger.info('Opening shell %s...', shell)
        self.master, self.slave = pty.openpty()
        env = os.environ.copy()
        env['TERM'] = 'xterm'

        def preexec():
            try:
                fd = os.open("/dev/tty", os.O_RDWR | os.O_NOCTTY)
            except OSError:
                pass
            else:
                try:
                    fcntl.ioctl(fd, termios.TIOCNOTTY, '')
                except:
                    pass
                os.close(fd)

            os.setsid()
            fcntl.ioctl(0, termios.TIOCSCTTY)

        def read_worker():
            while True:
                data = tp_read(self.master, self.BUFSIZE)
                if not data:
                    return

                self.ws.send(data)

        def write_worker():
            for i in self.inq:
                tp_write(self.master, i)

        self.proc = Popen(
            ['/usr/bin/su', '-m', user, '-c', shell],
            stdout=self.slave,
            stderr=self.slave,
            stdin=self.slave,
            close_fds=True,
            env=env,
            preexec_fn=preexec)

        self.logger.info('Shell %s spawned as PID %d', shell, self.proc.pid)

        wr = gevent.spawn(write_worker)
        rd = gevent.spawn(read_worker)
        self.proc.wait()
        self.ws.close()
        gevent.joinall([rd, wr])

    def on_open(self, *args, **kwargs):
        pass

    def on_close(self, *args, **kwargs):
        self.inq.put(StopIteration)
        self.logger.info('Terminating shell PID %d', self.proc.pid)
        if not self.proc.returncode:
            try:
                self.proc.terminate()
            except OSError:
                pass

        os.close(self.master)

    def on_message(self, message, *args, **kwargs):
        if message is None:
            return

        if not self.authenticated:
            message = loads(message.decode('utf8'))

            if type(message) is not dict:
                return

            if 'token' not in message:
                return

            token = self.dispatcher.token_store.lookup_token(message['token'])

            self.authenticated = True
            gevent.spawn(self.worker, token.user.name, token.shell)
            self.ws.send(dumps({'status': 'ok'}))
            return

        for i in message:
            i = bytes([i])
            if i == '\r':
                i = '\n'
            self.inq.put(i)


class FileConnection(WebSocketApplication, EventEmitter):
    BUFSIZE = 1024

    def __init__(self, ws, dispatcher):
        super(FileConnection, self).__init__(ws)
        self.dispatcher = dispatcher
        self.token = None
        self.authenticated = False
        self.bytes_done = None
        self.bytes_total = None
        self.done = Event()
        self.inq = Queue()
        self.logger = logging.getLogger('FileConnection')

    def worker(self, file, direction, size=None):
        def read_worker():
            while True:
                data = file.read(self.BUFSIZE)
                if not data:
                    return

                self.ws.send(data)

        def write_worker():
            for i in self.inq:
                file.write(i)

        wr = gevent.spawn(write_worker)
        rd = gevent.spawn(read_worker)
        self.ws.close()
        gevent.joinall([rd, wr])

    def on_open(self, *args, **kwargs):
        pass

    def on_close(self, *args, **kwargs):
        pass

    def on_message(self, message, *args, **kwargs):
        if message is None:
            return

        if not self.authenticated:
            message = loads(message)

            if type(message) is not dict:
                return

            if 'token' not in message:
                return

            self.token = self.dispatcher.token_store.lookup_token(message['token'])
            self.authenticated = True

            gevent.spawn(self.worker, self.token.file, self.token.direction, self.token.size)
            self.dispatcher.balancer.submit('file.{0}'.format(self.token.direction), self.token.name, self)
            self.ws.send(dumps({'status': 'ok'}))
            return

        for i in message:
            self.inq.put(i)


def run(d, args):
    setproctitle.setproctitle('dispatcher')
    monkey.patch_all(thread=False)

    # Signal handlers
    gevent.signal(signal.SIGQUIT, d.die)
    gevent.signal(signal.SIGTERM, d.die)
    gevent.signal(signal.SIGINT, d.die)
    gevent.signal(signal.SIGHUP, d.reload_plugins)

    # WebSockets server
    kwargs = {}
    if d.use_tls:
        kwargs = {'certfile': d.certfile, 'keyfile': d.keyfile}

    s4 = Server(('', args.p), ServerResource({
        '/socket': ServerConnection,
        '/shell': ShellConnection,
        '/api': ApiHandler(d)
    }, dispatcher=d), **kwargs)

    s6 = Server(('::', args.p), ServerResource({
        '/socket': ServerConnection,
        '/shell': ShellConnection,
        '/api': ApiHandler(d)
    }, dispatcher=d), **kwargs)

    su = UnixSocketServer(
        args.u,
        dispatcher=d
    )

    d.ws_servers = [s4, s6, su]
    d.port = args.p
    d.init()

    if args.s:
        # Debugging frontend server
        from frontend import frontend

        frontend.dispatcher = d
        http_server4 = WSGIServer(('', args.s), frontend.app, **kwargs)
        http_server6 = WSGIServer(('::', args.s), frontend.app, **kwargs)

        d.http_servers = [http_server4, http_server6]
        for i in d.http_servers:
            gevent.spawn(i.serve_forever)

        logging.info('Frontend server listening on port %d', args.s)

    serv_threads = [gevent.spawn(s4.serve_forever), gevent.spawn(s6.serve_forever), gevent.spawn(su.serve_forever)]

    d.discover_plugins()
    d.load_plugins()
    d.start()
    gevent.joinall(d.threads + serv_threads)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--log-level', type=str, metavar='LOG_LEVEL', default='INFO', help="Logging level")
    parser.add_argument('--log-file', type=str, metavar='LOG_FILE', help="Log to file")
    parser.add_argument('-s', type=int, metavar='PORT', default=8180, help="Run debug frontend server on port")
    parser.add_argument('-p', type=int, metavar='PORT', default=5000, help="WebSockets server port")
    parser.add_argument('-u', type=str, metavar='PATH', default='/var/run/dispatcher.sock', help="Unix domain server path")
    parser.add_argument('-c', type=str, metavar='CONFIG', default=DEFAULT_CONFIGFILE, help='Configuration file path')
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.getLevelName(args.log_level),
        format=LOGGING_FORMAT)

    if args.log_file:
        handler = FaultTolerantLogHandler(args.log_file)
        handler.setFormatter(logging.Formatter(LOGGING_FORMAT))
        logging.root.removeHandler(logging.root.handlers[0])
        logging.root.addHandler(handler)

    # Initialization and dependency injection
    d = Dispatcher()
    try:
        d.read_config_file(args.c)
    except IOError as err:
        logging.fatal("Cannot read config file {0}: {1}".format(args.c, str(err)))
        sys.exit(1)
    except ValueError as err:
        logging.fatal("Cannot parse config file {0}: {1}".format(args.c, str(err)))
        sys.exit(1)

    run(d, args)


if __name__ == '__main__':
    main()
