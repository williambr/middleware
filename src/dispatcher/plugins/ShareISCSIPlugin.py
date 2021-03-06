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
import errno
import uuid
import hashlib
import ctl
from task import Task, TaskStatus, Provider, TaskException, VerifyException
from freenas.dispatcher.rpc import RpcException, description, accepts, returns, private
from freenas.dispatcher.rpc import SchemaHelper as h
from freenas.utils import normalize
from freenas.utils.query import wrap


@description("Provides info about configured iSCSI shares")
class ISCSISharesProvider(Provider):
    @private
    @accepts(str)
    def get_connected_clients(self, share_name=None):
        handle = ctl.CTL()
        result = []
        for conn in handle.iscsi_connections:
            # Add entry for every lun mapped in this target
            target = self.datastore.get_by_id('iscsi.targets', conn.target)
            for lun in target['extents']:
                result.append({
                    'host': conn.initiator_address,
                    'share': lun['name'],
                    'user': conn.initiator,
                    'connected_at': None,
                    'extra': {}
                })

        return result

    @returns(str)
    def generate_serial(self):
        nic = wrap(self.dispatcher.call_sync('network.interfaces.query', [('type', '=', 'ETHER')], {'single': True}))
        laddr = nic['status.link_address'].replace(':', '')
        idx = 0

        while True:
            serial = '{0}{1:02}'.format(laddr, idx)
            if not self.datastore.exists('shares', ('properties.serial', '=', serial)):
                return serial

            idx += 1

        raise RpcException(errno.EBUSY, 'No free serial numbers found')

    @private
    @returns(str)
    def generate_naa(self):
        return '0x6589cfc000000{0}'.format(hashlib.sha256(uuid.uuid4().bytes).hexdigest()[0:19])


class ISCSITargetsProvider(Provider):
    def query(self, filter=None, params=None):
        return self.datastore.query('iscsi.targets', *(filter or []), **(params or {}))


class ISCSIAuthProvider(Provider):
    def query(self, filter=None, params=None):
        return self.datastore.query('iscsi.auth', *(filter or []), **(params or {}))


class ISCSIPortalProvider(Provider):
    def query(self, filter=None, params=None):
        return self.datastore.query('iscsi.portals', *(filter or []), **(params or {}))


@description("Adds new iSCSI share")
@accepts(h.ref('iscsi-share'))
class CreateISCSIShareTask(Task):
    def describe(self, share):
        return "Creating iSCSI share {0}".format(share['name'])

    def verify(self, share):
        if share['target'][0] == '/':
            # File extent
            if not os.path.exists(share['target']):
                raise VerifyException(errno.ENOENT, "Extent file does not exist")
        else:
            if not os.path.exists(convert_share_target(share['target'])):
                raise VerifyException(errno.ENOENT, "Extent ZVol does not exist")

        return ['service:ctl']

    def run(self, share):
        props = share['properties']
        normalize(props, {
            'serial': self.dispatcher.call_sync('shares.iscsi.generate_serial'),
            'block_size': 512,
            'physical_block_size': True,
            'tpc': False,
            'vendor_id': None,
            'device_id': None,
            'rpm': 'SSD'
        })

        props['naa'] = self.dispatcher.call_sync('shares.iscsi.generate_naa')
        id = self.datastore.insert('shares', share)
        self.dispatcher.call_sync('etcd.generation.generate_group', 'ctl')
        self.dispatcher.call_sync('services.reload', 'ctl')

        self.dispatcher.dispatch_event('shares.iscsi.changed', {
            'operation': 'create',
            'ids': [id]
        })


@description("Updates existing iSCSI share")
@accepts(str, h.ref('iscsi-share'))
class UpdateISCSIShareTask(Task):
    def describe(self, id, updated_fields):
        return "Updating iSCSI share {0}".format(id)

    def verify(self, id, updated_fields):
        return ['service:ctl']

    def run(self, id, updated_fields):
        share = self.datastore.get_by_id('shares', id)
        share.update(updated_fields)
        self.datastore.update('shares', id, share)
        self.dispatcher.call_sync('etcd.generation.generate_group', 'ctl')

        self.dispatcher.dispatch_event('shares.iscsi.changed', {
            'operation': 'update',
            'ids': [id]
        })


@description("Removes iSCSI share")
@accepts(str)
class DeleteiSCSIShareTask(Task):
    def describe(self, id):
        return "Deleting iSCSI share {0}".format(id)

    def verify(self, id):
        return ['service:ctl']

    def run(self, id):
        share = self.datastore.get_by_id('shares', id)

        # Check if share is mapped anywhere
        subtasks = []
        for i in self.datastore.query('iscsi.targets'):
            if share['name'] in [m['name'] for m in i['extents']]:
                i['extents'] = list(filter(lambda e: e['name'] != share['name'], i['extents']))
                subtasks.append(self.run_subtask('share.iscsi.target.update', i['id'], i))

        self.join_subtasks(subtasks)

        self.datastore.delete('shares', id)
        self.dispatcher.call_sync('etcd.generation.generate_group', 'ctl')
        self.dispatcher.call_sync('services.reload', 'ctl')

        self.dispatcher.dispatch_event('shares.iscsi.changed', {
            'operation': 'delete',
            'ids': [id]
        })


@accepts(h.ref('iscsi-target'))
class CreateISCSITargetTask(Task):
    def verify(self, target):
        for i in target.get('extents', []):
            if not self.datastore.exists('shares', ('type', '=', 'iscsi'), ('name', '=', i['name'])):
                raise VerifyException(errno.ENOENT, "Share {0} not found".format(i['name']))

        return ['service:ctl']

    def run(self, target):
        normalize(target, {
            'description': None,
            'auth_group': 'no-authentication',
            'portal_group': 'default',
            'extents': []
        })

        id = self.datastore.insert('iscsi.targets', target)
        self.dispatcher.dispatch_event('iscsi.target.changed', {
            'operation': 'create',
            'ids': [id]
        })

        return id


@accepts(str, h.ref('iscsi-target'))
class UpdateISCSITargetTask(Task):
    def verify(self, id, updated_params):
        if not self.datastore.exists('iscsi.targets', ('id', '=', id)):
            raise VerifyException(errno.ENOENT, 'Target {0} does not exist'.format(id))

        if 'extents' in updated_params:
            seen_numbers = []
            for i in updated_params['extents']:
                if not self.datastore.exists('shares', ('type', '=', 'iscsi'), ('name', '=', i['name'])):
                    raise VerifyException(errno.ENOENT, "Share {0} not found".format(i['name']))

                if i['number'] in seen_numbers:
                    raise VerifyException(errno.EEXIST, "LUN number {0} used twice".format(i['number']))

                seen_numbers.append(i['number'])

        return ['service:ctl']

    def run(self, id, updated_params):
        target = self.datastore.get_by_id('iscsi.targets', id)
        target.update(updated_params)
        self.datastore.update('iscsi.targets', id, target)
        self.dispatcher.call_sync('etcd.generation.generate_group', 'ctl')
        self.dispatcher.call_sync('services.reload', 'ctl')
        self.dispatcher.dispatch_event('iscsi.target.changed', {
            'operation': 'update',
            'ids': [id]
        })


@accepts(str)
class DeleteISCSITargetTask(Task):
    def verify(self, id):
        if not self.datastore.exists('iscsi.targets', ('id', '=', id)):
            raise VerifyException(errno.ENOENT, 'Target {0} does not exist'.format(id))

        return ['service:ctl']

    def run(self, id):
        self.datastore.delete('iscsi.targets', id)
        self.dispatcher.call_sync('etcd.generation.generate_group', 'ctl')
        self.dispatcher.call_sync('services.reload', 'ctl')
        self.dispatcher.dispatch_event('iscsi.target.changed', {
            'operation': 'delete',
            'ids': [id]
        })


@accepts(
    h.all_of(
        h.ref('iscsi-auth-group'),
        h.required('type')
    )
)
class CreateISCSIAuthGroupTask(Task):
    def verify(self, auth_group):
        return ['service:ctl']

    def run(self, auth_group):
        normalize(auth_group, {
            'id': self.datastore.collection_get_next_pkey('iscsi.auth', 'ag'),
            'users': None,
            'initiators': None,
            'networks': None
        })

        id = self.datastore.insert('iscsi.auth', auth_group)
        self.dispatcher.call_sync('etcd.generation.generate_group', 'ctl')
        self.dispatcher.call_sync('services.reload', 'ctl')
        self.dispatcher.dispatch_event('iscsi.auth.changed', {
            'operation': 'create',
            'ids': [id]
        })
        return id


@accepts(str, h.ref('iscsi-auth-group'))
class UpdateISCSIAuthGroupTask(Task):
    def verify(self, id, updated_params):
        if not self.datastore.exists('iscsi.auth', ('id', '=', id)):
            raise VerifyException(errno.ENOENT, 'Auth group {0} does not exist'.format(id))

        return ['service:ctl']

    def run(self, id, updated_params):
        ag = self.datastore.get_by_id('iscsi.auth', id)
        ag.update(updated_params)
        self.datastore.update('iscsi.auth', id, ag)
        self.dispatcher.call_sync('etcd.generation.generate_group', 'ctl')
        self.dispatcher.call_sync('services.reload', 'ctl')
        self.dispatcher.dispatch_event('iscsi.auth.changed', {
            'operation': 'update',
            'ids': [id]
        })


@accepts(str)
class DeleteISCSIAuthGroupTask(Task):
    def verify(self, id):
        if not self.datastore.exists('iscsi.auth', ('id', '=', id)):
            raise VerifyException(errno.ENOENT, 'Auth group {0} does not exist'.format(id))

        return ['service:ctl']

    def run(self, id):
        self.datastore.delete('iscsi.auth', id)
        self.dispatcher.call_sync('etcd.generation.generate_group', 'ctl')
        self.dispatcher.call_sync('services.reload', 'ctl')
        self.dispatcher.dispatch_event('iscsi.auth.changed', {
            'operation': 'delete',
            'ids': [id]
        })


@accepts(h.ref('iscsi-portal'))
class CreateISCSIPortalTask(Task):
    def verify(self, portal):
        return ['service:ctl']

    def run(self, portal):
        normalize(portal, {
            'id': self.datastore.collection_get_next_pkey('iscsi.portals', 'pg'),
            'discovery_auth_group': None,
            'discovery_auth_method': 'NONE',
            'portals': []
        })

        id = self.datastore.insert('iscsi.portals', portal)
        self.dispatcher.call_sync('etcd.generation.generate_group', 'ctl')
        self.dispatcher.call_sync('services.reload', 'ctl')
        self.dispatcher.dispatch_event('iscsi.portal.changed', {
            'operation': 'create',
            'ids': [id]
        })
        return id


@accepts(str, h.ref('iscsi-portal'))
class UpdateISCSIPortalTask(Task):
    def verify(self, id, updated_params):
        if not self.datastore.exists('iscsi.portals', ('id', '=', id)):
            raise VerifyException(errno.ENOENT, 'Portal {0} does not exist'.format(id))

        return ['service:ctl']

    def run(self, id, updated_params):
        ag = self.datastore.get_by_id('iscsi.portals', id)
        ag.update(updated_params)
        self.datastore.update('iscsi.portals', id, ag)
        self.dispatcher.call_sync('etcd.generation.generate_group', 'ctl')
        self.dispatcher.call_sync('services.reload', 'ctl')
        self.dispatcher.dispatch_event('iscsi.portal.changed', {
            'operation': 'update',
            'ids': [id]
        })


@accepts(str)
class DeleteISCSIPortalTask(Task):
    def verify(self, id):
        if not self.datastore.exists('iscsi.portals', ('id', '=', id)):
            raise VerifyException(errno.ENOENT, 'Portal {0} does not exist'.format(id))

        return ['service:ctl']

    def run(self, id):
        self.datastore.delete('iscsi.portals', id)
        self.dispatcher.call_sync('etcd.generation.generate_group', 'ctl')
        self.dispatcher.call_sync('services.reload', 'ctl')
        self.dispatcher.dispatch_event('iscsi.portal.changed', {
            'operation': 'delete',
            'ids': [id]
        })


def convert_share_target(target):
    if target[0] == '/':
        return target

    return os.path.join('/dev/zvol', target)


def _metadata():
    return {
        'type': 'sharing',
        'subtype': 'block',
        'method': 'iscsi',
    }


def _init(dispatcher, plugin):
    plugin.register_schema_definition('iscsi-share-properties', {
        'type': 'object',
        'additionalProperties': False,
        'properties': {
            'serial': {'type': 'string'},
            'ctl_lun': {'type': 'integer'},
            'naa': {'type': 'string'},
            'size': {'type': 'integer'},
            'block_size': {
                'type': 'integer',
                'enum': [512, 1024, 2048, 4096]
            },
            'physical_block_size': {'type': 'boolean'},
            'available_space_threshold': {'type': 'integer'},
            'tpc': {'type': 'boolean'},
            'vendor_id': {'type': ['string', 'null']},
            'device_id': {'type': ['string', 'null']},
            'rpm': {
                'type': 'string',
                'enum': ['UNKNOWN', 'SSD', '5400', '7200', '10000', '15000']
            }
        }
    })

    plugin.register_schema_definition('iscsi-target', {
        'type': 'object',
        'additionalProperties': False,
        'properties': {
            'id': {'type': 'string'},
            'description': {'type': 'string'},
            'auth_group': {'type': 'string'},
            'portal_group': {'type': 'string'},
            'extents': {
                'type': 'array',
                'items': {
                    'type': 'object',
                    'additionalProperties': False,
                    'properties': {
                        'name': {'type': 'string'},
                        'number': {'type': 'integer'}
                    },
                    'required': ['name', 'number']
                },
            }
        }
    })

    plugin.register_schema_definition('iscsi-portal', {
        'type': 'object',
        'additionalProperties': False,
        'properties': {
            'id': {'type': 'string'},
            'tag': {'type': 'integer'},
            'description': {'type': 'string'},
            'discovery_auth_group': {'type': 'string'},
            'listen': {
                'type': 'array',
                'items': {
                    'type': 'object',
                    'additionalProperties': False,
                    'properties': {
                        'address': {'type': 'string'},
                        'port': {'type': 'integer'}
                    }
                }
            }
        }
    })

    plugin.register_schema_definition('iscsi-auth-group', {
        'type': 'object',
        'additionalProperties': False,
        'properties': {
            'id': {'type': 'string'},
            'description': {'type': 'string'},
            'type': {
                'type': 'string',
                'enum': ['NONE', 'DENY', 'CHAP', 'CHAP_MUTUAL']
            },
            'users': {
                'type': ['array', 'null'],
                'items': {'$ref': 'iscsi-user'}
            },
            'initiators': {
                'type': ['array', 'null'],
                'items': {'type': 'string'}
            },
            'networks': {
                'type': ['array', 'null'],
                'items': {'type': 'string'}
            },
        }
    })

    plugin.register_schema_definition('iscsi-user', {
        'type': 'object',
        'additionalProperties': False,
        'properties': {
            'name': {'type': 'string'},
            'secret': {'type': 'string', 'minLength': 12, 'maxLength': 16},
            'peer_name': {'type': ['string', 'null']},
            'peer_secret': {'type': ['string', 'null'], 'minLength': 12, 'maxLength': 16}
        }
    })

    plugin.register_task_handler("share.iscsi.create", CreateISCSIShareTask)
    plugin.register_task_handler("share.iscsi.update", UpdateISCSIShareTask)
    plugin.register_task_handler("share.iscsi.delete", DeleteiSCSIShareTask)
    plugin.register_task_handler("share.iscsi.target.create", CreateISCSITargetTask)
    plugin.register_task_handler("share.iscsi.target.update", UpdateISCSITargetTask)
    plugin.register_task_handler("share.iscsi.target.delete", DeleteISCSITargetTask)
    plugin.register_task_handler("share.iscsi.auth.create", CreateISCSIAuthGroupTask)
    plugin.register_task_handler("share.iscsi.auth.update", UpdateISCSIAuthGroupTask)
    plugin.register_task_handler("share.iscsi.auth.delete", DeleteISCSIAuthGroupTask)
    plugin.register_task_handler("share.iscsi.portal.create", CreateISCSIPortalTask)
    plugin.register_task_handler("share.iscsi.portal.update", UpdateISCSIPortalTask)
    plugin.register_task_handler("share.iscsi.portal.delete", DeleteISCSIPortalTask)

    plugin.register_provider("shares.iscsi", ISCSISharesProvider)
    plugin.register_provider("shares.iscsi.target", ISCSITargetsProvider)
    plugin.register_provider("shares.iscsi.auth", ISCSIAuthProvider)
    plugin.register_provider("shares.iscsi.portal", ISCSIPortalProvider)
    plugin.register_event_type('shares.iscsi.changed')
