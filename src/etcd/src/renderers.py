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


from mako import exceptions
from mako.template import Template
from datastore.config import ConfigStore


class TemplateFunctions:
    @staticmethod
    def disclaimer(comment_style='#'):
        return "{} WARNING: This file was auto-generated".format(comment_style)


class MakoTemplateRenderer(object):
    def __init__(self, context):
        self.context = context

    def get_template_context(self):
        return {
            "disclaimer": TemplateFunctions.disclaimer,
            "config": self.context.configstore,
            "dispatcher": self.context.client,
            "ds": self.context.datastore
        }

    def render_template(self, path):
        try:
            tmpl = Template(filename=path)
            return tmpl.render(**self.get_template_context())
        except:
            self.context.logger.debug('Failed to render mako template: {0}'.format(
                exceptions.text_error_template().render()
            ))
            raise



class PythonRenderer(object):
    def __init__(self, context):
        self.context = context


class ShellTemplateRenderer(object):
    def __init__(self, context):
        self.context = context
