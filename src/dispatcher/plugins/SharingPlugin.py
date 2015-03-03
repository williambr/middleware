#+
# Copyright 2015 iXsystems, Inc.
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

import errno
from task import Task, TaskException, VerifyException, Provider, RpcException, query


class SharesProvider(Provider):
    @query('definitions/share')
    def query(self, filter=None, params=None):
        return self.datastore.query('shares', *(filter or []), **(params or {}))

    def supported_types(self):
        result = []
        for p in self.dispatcher.plugins.values():
            if p.metadata and p.metadata.get('type') == 'sharing':
                result.append(p.metadata['method'])

        return result

    def get_connected_clients(self, share_name):
        share = self.datastore.get_by_id('shares', share_name)
        if not share:
            raise RpcException(errno.ENOENT, 'Share not found')

        return self.dispatcher.call_sync('shares.{0}.get_connected_clients'.format(share['type']), share_name)


class CreateShareTask(Task):
    def verify(self, share):
        return ['system']

    def run(self, share):
        self.join_subtasks(self.run_subtask('share.{0}.create'.format(share['type']), share))


class UpdateShareTask(Task):
    def verify(self, name, updated_fields):
        share = self.datastore.get_by_id('shares', name)
        if not share:
            raise VerifyException(errno.ENOENT, 'Share not found')

        self.share_type = share['type']
        return ['system']

    def run(self, name, updated_fields):
        self.join_subtasks(self.run_subtask('share.{0}.update'.format(self.share_type), name, updated_fields))


class DeleteShareTask(Task):
    def verify(self, name):
        share = self.datastore.get_by_id('shares', name)
        if not share:
            raise VerifyException(errno.ENOENT, 'Share not found')

        self.share_type = share['type']
        return ['system']

    def run(self, name):
        self.join_subtasks(self.run_subtask('share.{0}.delete'.format(self.share_type), name))


def _init(dispatcher):
    dispatcher.register_schema_definition('share', {
        'type': 'object',
        'properties': {
            'id': {'type': 'string'},
            'type': {'type': 'string'},
            'target': {'type': 'string'},
            'properties': {'type': 'object'}
        }
    })

    dispatcher.require_collection('shares', 'string')
    dispatcher.register_provider('shares', SharesProvider)
    dispatcher.register_task_handler('share.create', CreateShareTask)
    dispatcher.register_task_handler('share.update', UpdateShareTask)
    dispatcher.register_task_handler('share.delete', DeleteShareTask)