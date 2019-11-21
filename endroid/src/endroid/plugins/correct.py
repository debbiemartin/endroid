# -----------------------------------------------------------------------------
# Endroid - XMPP Bot - Correction plugin
# Copyright 2012, Ensoft Ltd.
# Created by Martin Morrison
# -----------------------------------------------------------------------------

import re

from endroid.pluginmanager import Plugin

REGEX = r"^s(?P<sep>[^a-zA-Z0-9\\])((?:[^\\]|\\.)+)(?P=sep)((?:[^\\]|\\.)*)(?P=sep)(g?i?|ig)(?:\s.*)?$"
REOBJ = re.compile(REGEX)

ERROR = "It looks like you tried to correct yourself, but I couldn't parse it! "

class Correct(Plugin):
    """
    Correction plugin handles sed-style regular expressions, and corrects the
    last message heard from the sender using that regex.
    """
    name = "correct"
    help = "Correct typos using s/<regex>/<replace>/[gi]"

    def endroid_init(self):
        self.lastmsg = {}
        self.messages.register(self.heard)

    def heard(self, msg):
        """
        Monitors all received messages to track the last message from each
        sender. Checks whether the phrase matches the substitution regex, and
        if so, attempts to correct using the correct() method.
        """
        try:
            match = REOBJ.match(msg.body)
        except re.error:
            match = None

        if match and msg.sender in self.lastmsg:
            self.correct(msg, self.lastmsg[msg.sender], match)
        else:
            msg.unhandled()
            self.lastmsg[msg.sender] = msg.body

    def correct(self, msg, body, match):
        """
        Attempts to correct the previous message (given by 'body') using the
        matches in the match object (given in 'match'). Replies are sent via
        the given 'msg' (so either to the room or original sender).

        The regular expressions support full Python regex syntax; the
        replacement group supports backreferences using \1 or \g<1> syntax; two
        flags are supported: i for case-insensitive, and g for global
        replacements.
        """
        if r'\0' in match.group(3):
            return msg.reply_to_sender(ERROR + r"'\0' not valid group reference."
                                             + " Indices start at one.")
        
        opts = match.group(4) if match.group(4) else ""
        count = 0 if "g" in opts else 1
        flags = "(?i)" if "i" in opts else ""

        try:
            newstr = re.sub(flags + match.group(2), match.group(3), body, count)
        except Exception as e:
            return msg.reply_to_sender(ERROR + str(e))

        if newstr == body:
            # This is unexpected. Probably a mistake on the user's part?
            msg.unhandled()
        else:
            sendernick = self.rosters.nickname(msg.sender_full)
            who = sendernick if self.place == "room" else "You"
            msg.reply("%s meant: %s" % (who, newstr))
