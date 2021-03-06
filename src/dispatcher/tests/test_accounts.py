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
######################################################################

import unittest
from freenas.dispatcher.rpc import RpcException
from shared import BaseTestCase


class UsersTest(BaseTestCase):
    def tearDown(self):
        # try to delete all users created during tests
        for u in self.conn.call_sync('users.query', [('username', '~', 'testUser.*')]):
            self.assertTaskCompletion(self.submitTask('users.delete', u['id']))

        super(UsersTest, self).tearDown()

    def test_create_user_uid(self):
        tid = self.submitTask('users.create', {
            'id': 1234,
            'username': 'testUser',
            'group': 0,
            'shell': '/bin/csh',
            'home': '/mnt',
            'password': 'null',
        })
        
        self.assertTaskCompletion(tid)
        user = self.conn.call_sync('users.query', [('id', '=', 1234)], {'single': True})
        self.assertIsInstance(user, dict)
        self.assertEqual(user['username'], 'testUser')

    def test_create_user_nouid(self):
        tid = self.submitTask('users.create', {
            'username': 'testUserNoUid',
            'group': 0,
            'shell': '/bin/csh',
            'home': '/nonexistent',
            'password': 'null',
        })

        self.assertTaskCompletion(tid)
        user = self.conn.call_sync('users.query', [('id', '=', self.getTaskResult(tid))], {'single': True})
        self.assertIsInstance(user, dict)
        self.assertEqual(user['username'], 'testUserNoUid')

    
    def test_create_user_invalid(self):
        with self.assertRaises(RpcException):
            self.submitTask('users.create', {
                'blargh': 'foo',
                'group': 1234,
                'username': False
            })

    def test_modify_user(self):
        tid = self.submitTask('users.create', {
            'id': 1234,
            'username': 'testUser',
            'group': 0,
            'shell': '/bin/csh',
            'home': '/nonexistent',
            'password': 'null'
        })

        self.assertTaskCompletion(tid)
        self.assertTaskCompletion(self.submitTask('users.update', 1234, {'full_name': 'Hello', 'password': 'null', 'home': '/nonexistent'}))
        user = self.conn.call_sync('users.query', [('id', '=', 1234)], {'single': True})
        self.assertIsInstance(user, dict)
        self.assertEqual(user['full_name'], 'Hello')

    def test_remove_builtin_user(self):
        self.assertTaskFailure(self.submitTask('users.delete', 0))

    def test_query_users(self):
        users = self.conn.call_sync('users.query')
        self.assertIsInstance(users, list)
        self.assertGreater(len(users), 0)
        self.assertIsInstance(users[0], dict)
    
    def test_query_next_uid(self):
        uid = self.conn.call_sync('users.next_uid')
        self.assertIsInstance(uid, int)
        


class GroupsTest(BaseTestCase):
    def tearDown(self):
        # try to delete all groups created during tests
        for u in self.conn.call_sync('groups.query', [('name', '~', 'testGroup.*')]):
            self.assertTaskCompletion(self.submitTask('groups.delete', u['id']))

        super(GroupsTest, self).tearDown()
 

    def test_create_group_gid(self):
        tid = self.submitTask('groups.create', {
            'name': 'testGroup',
            'sudo': False,
            'id': 1234,
        })

        self.assertTaskCompletion(tid)

    def test_create_group_nogid(self):
        tid = self.submitTask('groups.create', {
            'name': 'testGroupNoGid',
        })

        self.assertTaskCompletion(tid)

    def test_create_group_invalid(self):
        with self.assertRaises(RpcException):
            self.submitTask('groups.create', {
                'blargh': 'foo',
                'group': 1234,
            })

    def test_update_group(self):
        pass

    def test_list_groups(self):
        groups = self.conn.call_sync('groups.query')
        self.assertIsInstance(groups, list)
        self.assertGreater(len(groups), 0)
        self.assertIsInstance(groups[0], dict)


if __name__ == '__main__':
    unittest.main()
