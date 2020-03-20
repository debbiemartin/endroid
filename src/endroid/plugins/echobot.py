# -----------------------------------------
# Endroid - Webex Bot
# Copyright 2012, Ensoft Ltd.
# Created by Jonathan Millican
# -----------------------------------------

from endroid.pluginmanager import Plugin

class EchoBot(Plugin):
    def endroid_init(self):
        self.register_chat_callback(self.do_echo)
        self.register_muc_callback(self.do_echo)
    
    def do_echo(self, msg):
        msg.reply(msg.body)
