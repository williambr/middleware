#!/usr/local/bin/python
#
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

import sys
import logging

logger = logging.getLogger('kerberos')

class Kerberos(object):
    def __init__(self, *args,  **kwargs):
        self.dispatcher = kwargs['dispatcher']
        self.datastore = kwargs['datastore']

        sys.path.extend(['/usr/local/lib/dsd/modules/'])
        from dsdns import DSDNS

        self.dsdns = DSDNS(
            dispatcher=self.dispatcher,
            datastore=self.datastore,
        )

    def get_kerberos_servers(self, domain, site=None):
        kdcs = []
        if not domain:
            return kdcs
            
        host = "_kerberos._tcp.%s" % domain
        if site:
            host = "_kerberos._tcp.%s._sites.%s" % (site, domain)
            
        kdcs = self.dsdns.get_SRV_records(host)
        return kdcs

    def get_kerberos_domain_controllers(self, domain, site=None):
        kdcs = []
        if not domain:
            return kdcs

        host = "_kerberos._tcp.dc._msdcs.%s" % domain
        if site:
            host = "_kerberos._tcp.%s._sites.dc._msdcs.%s" % (site, domain)

        kdcs = self.dsdns.get_SRV_records(host)
        return kdcs

    def get_kpasswd_servers(self, domain):
        kpws = []
        if not domain:
            return kpws

        host = "_kpasswd._tcp.%s" % domain

        kpws = self.dsdns.get_SRV_records(host)
        return kpws


def _init(dispatcher, datastore):
    return Kerberos(
        dispatcher=dispatcher,
        datastore=datastore
    ) 