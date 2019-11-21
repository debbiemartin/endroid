# -----------------------------------------------------------------------------
# Endroid - XMPP Bot - Spell plugin
# Copyright 2012, Ensoft Ltd.
# Created by Martin Morrison
# -----------------------------------------------------------------------------

# NOTE: This will not work, because the Google spellchecking API was discontinued in 2013.

import re
from functools import partial

from twisted.web.client import getPage
from endroid.pluginmanager import Plugin

REGEX = r"(\w+)\W?\(sp\??\)"
REOBJ = re.compile(REGEX)

POSTFORM = """<?xml version="1.0" encoding="utf-8" ?>
<spellrequest textalreadyclipped="0" ignoredups="0" ignoredigits="1" ignoreallcaps="1">
<text><![CDATA[%s]]></text>
</spellrequest>"""

class Spell(Plugin):
    """
    Spell checking plugin that uses Google's service to verify spelling of any
    words marked with a '(sp?)' after them.
    """
    name = "spell"
    dependencies = ("endroid.plugins.patternmatcher",)
    help = "Check spelling of words by typing '(sp?)' after them."

    def endroid_init(self):
        pat = self.get("endroid.plugins.patternmatcher")
        pat.register_both(self.heard, REOBJ)

    def heard(self, msg):
        """
        Checks spelling of all the matches.
        """
        matches = REOBJ.findall(msg.body)

        for word in matches:
            self.checkspelling(msg, word)

    def checkspelling(self, msg, word):
        getPage("https://www.google.com/tbproxy/spell?lang=en:",
                method="POST",
                postdata=POSTFORM % str(word.replace(']', '')),
                headers={"Content-Type":
                             "application/x-www-form-urlencoded"} # Really?
                ).addCallbacks(partial(self.spell, msg, word), msg.unhandled)

    def spell(self, msg, word, data):
        # Cheap and dirty: the response format is an XML document, where the
        # only plain text is a tab-separated list of the suggested spellings.
        # So we just get rid of XML, and split.
        opts = re.sub("<.*?>", "", data).split()
        if opts:
            msg.reply('"{0}" suggestions: {1}'.format(word, ", ".join(opts)))
        else:
            # Note: Google doesn't seem to distinguish "word is correctly
            # spelt" from "I have no suggestions for this". :-(
            msg.reply('"{0}" is spelt correctly (or complete gibberish!)'
                      .format(word))
