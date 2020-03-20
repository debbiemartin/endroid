# -----------------------------------------------------------------------------
# EnDroid - Exec process plugin
# Copyright 2013, Ensoft Ltd
# Created by Simon C
# -----------------------------------------------------------------------------

import re
from twisted.internet.utils import getProcessOutput
from endroid.pluginmanager import Plugin

class Exec(Plugin):
    name = "exec"
    help = "Execute a command and display the output"
    
    def endroid_init(self):
        """
        Go through each command, and compile a regexp for all the possible
        ways to invoke it. We want any expensive string processing to be done
        by the regexp engine, not Python.
        """
        self.regexp_map = []
        for cmd_spec in self.vars.values():
            invocation = cmd_spec[0]
            help_str = cmd_spec[1]
            cmds = cmd_spec[2:]
            regexp_bits = []
            self.help += '\n\n{}:'.format(help_str)
            for cmd in cmds:
                regexp_bits.append(r'(?:(?:(?:hey\s+)?endroid[,!:\s\?]*)?'
                                   + '(?:' + cmd + ')' +
                                   r'[,\s]*(?:please[,\s]*)?[\?!]*(?:endroid)?[\s\?!]*$)')
                self.help += '\n - ' + cmd
            regexp = re.compile('|'.join(regexp_bits), re.IGNORECASE)
            self.regexp_map.append((regexp, invocation))
        self.messages.register(self.heard)

    def heard(self, msg):
        """
        See if any of our commands match, and execute the process if so.
        """
        for regexp, invocation in self.regexp_map:
            if regexp.match(msg.body):
                self.invoke(invocation, msg)
                break
        else:
            msg.unhandled()

    def invoke(self, invocation, msg):
        """
        Spawn a process and send the output
        """
    	def failure(result):
            # twisted voodoo to try to guess at the interesting bit of a failure
            try:
                failure_summary = result.value[0].split('\\n')[-2]
                assert len(failure_summary) > 0
            except Exception:
                failure_summary = str(result.value)
            msg.reply("I have this terrible pain in all the diodes down my "
                      "left hand side, trying to execute {}: {}".
                      format(invocation, failure_summary))
        d = getProcessOutput('/bin/sh', ('-c', invocation))
        d.addCallbacks(lambda result: msg.reply(result.rstrip()), failure)

