# -----------------------------------------------------------------------------
# EnDroid - Brainy Quote of the moment plugin
# Copyright 2013, Ensoft Ltd
# -----------------------------------------------------------------------------

import re
from HTMLParser import HTMLParser
from twisted.web.client import getPage
from endroid.plugins.command import CommandPlugin, command

QURE = re.compile(r'<div class="bq_fq"[^>]*>\s*<p>(.*?)</p>.*?<a[^>]*>(.*?)</a>',
                  re.S)

class BrainyQuote(CommandPlugin):
    help = "Get the Quote of the Moment from brainyquote.com."

    @command(synonyms=("brainy quote", "brainyquote"))
    def cmd_quote(self, msg, arg):
        def extract_quote(data):
            quote, author = map(str.strip, QURE.search(data).groups())
            hp = HTMLParser()
            msg.reply("Quote of the moment: {} -- {}".format(
                      hp.unescape(quote), hp.unescape(author)))

        getPage("http://www.brainyquote.com/").addCallbacks(extract_quote,
                                                            msg.unhandled)
