#!/usr/bin/env python2.7
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


import os
import sys
import tempfile
from utils import sh, sh_str, e, setup_env, objdir, info, import_function
create_aux_files = import_function('create-release-distribution', 'create_aux_files')


def main():
    changelog = e('${CHANGELOG}')
    ssh = e('${UPDATE_USER}@${UPDATE_HOST}')
    temp_dest = sh_str("ssh ${ssh} mktemp -d /tmp/update-${PRODUCT}-XXXXXXXXX")
    temp_changelog = sh_str("ssh ${ssh} mktemp /tmp/changelog-XXXXXXXXX")

    sh('scp -r ${BUILD_ROOT}/objs/LATEST/. ${ssh}:${temp_dest}')
    if changelog:
        if changelog == '-':
            print 'Enter changelog, ^D to end:'
            changelog = sys.stdin.read()


        sh('scp ${changelog} ${ssh}:${temp_changelog}')

    sh(
        "ssh ${ssh}",
        "/usr/local/bin/freenas-release",
        "-P ${PRODUCT}",
        "-D ${UPDATE_DB}",
        "--archive ${UPDATE_DEST}",
        "-K ${FREENAS_KEYFILE}",
        "-C ${temp_changelog}" if changelog else "",
        "add ${temp_dest}"
    )

    sh("ssh ${ssh} rm -rf ${temp_dest}")
    sh("ssh ${ssh} rm -rf ${temp_changelog}")

if __name__ == '__main__':
    main()