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

import imp
import os
import sys
import json


DRIVERS_LOCATION = '/usr/local/lib/datastore/drivers'
DEFAULT_CONFIGFILE = '/usr/local/etc/middleware.conf'


class DatastoreException(Exception):
    pass


class DuplicateKeyException(DatastoreException):
    pass


def get_datastore(type, dsn, database='freenas'):
    mod = imp.load_source(type, os.path.join(DRIVERS_LOCATION, type, type + '.py'))
    if mod is None:
        raise DatastoreException('Datastore driver not found')

    cls = getattr(mod, '{0}Datastore'.format(type.title()))
    if cls is None:
        raise DatastoreException('Datastore driver not found')

    instance = cls()
    instance.connect(dsn, database)
    return instance


def get_default_datastore():
    def parse_config(filename):
        try:
            f = open(filename, 'r')
            config = json.load(f)
            f.close()
        except IOError as err:
            raise DatastoreException('Cannot read config file: {0}'.format(err.message))
        except ValueError:
            raise DatastoreException('Config file has unreadable format (not valid JSON)')

        return config

    conf = parse_config(DEFAULT_CONFIGFILE)
    return get_datastore(conf['datastore']['driver'], conf['datastore']['dsn'])
