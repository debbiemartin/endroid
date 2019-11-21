# -----------------------------------------
# Endroid - XMPP Bot
# Copyright 2012, Ensoft Ltd.
# Created by Jonathan Millican
# -----------------------------------------

from endroid.plugins.command import CommandPlugin

class Speak(CommandPlugin):
    name = "speak"
    help = ("Speak allows you to speak as EnDroid. Don't abuse it\n"
            "Command syntax: speak <tojid> <message>")
    
    def cmd_speak(self, msg, args):
        tojid, text = self._split(args)
        if tojid in self.rosters.available_users:
            self.messages.send_chat(tojid, text, msg.sender)
        else:
            msg.reply("You can't send messages to that user. Sorry.")
    cmd_speak.helphint = "<tojid> <message>"

    def repeat(self, msg, args):
        count, tojid, text = args.split(' ', 2)
        if tojid in self.rosters.available_users:
            for i in range(int(count)):
                self.messages.send_chat(tojid, text, msg.sender)
        else:
            msg.reply("You can't send messages to that user. Sorry.")
    repeat.helphint = "<count> <tojid> <message>"
    
    def _split(self, message):
        if message.count(' ') == 0:
            return (message, '')
        else:
            return message.split(' ', 1)
