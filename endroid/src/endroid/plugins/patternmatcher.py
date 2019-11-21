# -----------------------------------------
# Endroid - XMPP Bot
# Copyright 2012, Ensoft Ltd.
# Created by Jonathan Millican
# -----------------------------------------

import re
from endroid.pluginmanager import Plugin
from collections import namedtuple

Registration = namedtuple('Registration', ('callback', 'pattern'))

class PatternMatcher(Plugin):
    name = "patternmatcher"
    hidden = True
    
    def __init__(self):
        self._muc_match_list = []
        self._chat_match_list = []
    
    def enInit(self):
        self.register_muc_callback(self.match_muc_message)
        self.register_chat_callback(self.match_chat_message)

    def pattern(self, pattern):
        if isinstance(pattern, (str, unicode)):
            return re.compile(pattern)
        else:
            return pattern

    def register_muc(self, callback, pattern):
        self._muc_match_list.append(Registration(callback,
                                                 self.pattern(pattern)))
    
    def register_chat(self, callback, pattern):
        self._chat_match_list.append(Registration(callback,
                                                  self.pattern(pattern)))

    def register_both(self, callback, pattern):
        self.register_muc(callback, pattern)
        self.register_chat(callback, pattern)
    
    def match_message(self, testlist, msg):
        for callback, pattern in testlist:
            body = msg.body.strip()
            if pattern.search(body):
                msg.inc_handlers()
                callback(msg)
        msg.unhandled()
    
    def match_muc_message(self, message):
        self.match_message(self._muc_match_list, message)
        
    def match_chat_message(self, message):
        self.match_message(self._chat_match_list, message)

    def help(self):
        return "I match patterns for other plugins. I can't yet tell you what patterns are registered though, sorry."

def get_plugin():
    return PatternMatcher()
