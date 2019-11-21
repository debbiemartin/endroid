# -----------------------------------------------------------------------------
# EnDroid - Chuck Norris fact plugin
# Copyright 2012, Ensoft Ltd
# -----------------------------------------------------------------------------

import re
from HTMLParser import HTMLParser
from twisted.web.client import getPage
from endroid.plugins.command import CommandPlugin

FACTRE = re.compile(r'<div id="wia_factBox">(.*?)</p>', re.S)

class ChuckNorris(CommandPlugin):
    help = "Get a random Chuck Norris fact."

    def cmd_chuck(self, msg, arg):
        def extract_fact(data):
            fact = re.sub(r"<.*?>", "", FACTRE.search(data).group(1)).strip()
            msg.reply("Fact: {0}".format(HTMLParser().unescape(fact.strip())))

        getPage("http://www.whatisawesome.com/chuck").addCallbacks(extract_fact,
                                                                   msg.unhandled)
    cmd_chuck.synonyms = ('norris', 'chucknorris')
