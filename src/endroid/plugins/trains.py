# -----------------------------------------
# Endroid - Trains Live Departures
# Copyright 2013, Ensoft Ltd.
# Created by Martin Morrison
# -----------------------------------------

import re
import urllib
from HTMLParser import HTMLParser
from twisted.web.client import getPage

from endroid.plugins.command import CommandPlugin, command

TIMERE_STR = r'(\d+)(?::(\d+))? *(am|pm)?'
ULRE = re.compile(r'<ul class="results">(.*)', re.S)
CMDRE = re.compile(r"((?:from (.*) )?to (.*?)|home)(?:(?: (arriving|leaving))?(?: (tomorrow|(?:next )?\w*day))?(?: at ({}))?)?$".format(TIMERE_STR))
RESULTRE = re.compile(r"<strong> *(.*?) *</strong>")
TIMERE = re.compile(TIMERE_STR)

STATION_TABLE = "Stations"
HOME_TABLE = "Home"

class TrainTimes(CommandPlugin):
    name = "traintimes"

    def endroid_init(self):
        if not self.database.table_exists(STATION_TABLE):
            self.database.create_table(STATION_TABLE, ("jid", "station"))
        if not self.database.table_exists(HOME_TABLE):
            self.database.create_table(HOME_TABLE, ("jid", "station"))

    def help(self):
        return "When do trains leave?"

    def _station_update(self, msg, args, table, jid, display):
        if not args:
            rows = self.database.fetch(table, ("station",),
                                       {"jid": jid})
            if rows:
                msg.reply_to_sender("Your {} station is set to: {}"
                                    .format(display, rows[0]['station']))
            else:
                msg.reply_to_sender("You don't have a {} station set."
                                    .format(display))
            return
        self.database.delete(table, {"jid" : jid})
        if args != "delete":
            self.database.insert(table, {"jid": jid, "station": args})
            msg.reply_to_sender("Your new {} station is: {}"
                                .format(display, args))
        else:
            msg.reply_to_sender("{} station deleted."
                                .format(display.capitalize()))

    @command(helphint="{<station name>|delete}")
    def nearest_station(self, msg, args):
        # Use msg.sender_full (with resource) because a person might
        # be in different locations with different resources
        self._station_update(msg, args, STATION_TABLE, msg.sender,
                             "nearest")

    @command(helphint="{<station name>|delete}")
    def home_station(self, msg, args):
        # Use msg.sender (no resource) because a person probably
        # lives in the same place regardless of Webex resource
        self._station_update(msg, args, HOME_TABLE, msg.sender, "home")

    @command(helphint="from <stn> to <stn> [[arriving|leaving] at <time>]",
             synonyms=("next train",))
    def train(self, msg, args):
        match = CMDRE.match(args)
        if not match:
            msg.reply("Brain the size of a planet, but I can't parse that request")
            return

        def extract_results(data):
            result = None
            m = ULRE.search(data)
            if m:
                results = RESULTRE.findall(m.group(1))
            if results:
                msg.reply(u"Trains from {} to {}: {}"
                          .format(src, dst,
                                  HTMLParser().unescape(u", ".join(results))))
            else:
                msg.reply("Either your request is malformed, or there are no matching trains")

        home, src, dst, typ, when, raw_time, _,_,_ = match.groups()
        time = self._canonical_time(raw_time) if raw_time is not None else None
        if raw_time and not time:
            msg.reply("I can't understand the time you've entered can you try another way?")
            return

        if dst == "home" or home == "home":
            rows = self.database.fetch(HOME_TABLE, ("station",),
                                       {"jid": msg.sender})
            if rows:
                dst = rows[0]['station']
            else:
                msg.reply("You must save a home station with the 'home station'"
                          " command")
                return
        if src is None:
            rows = self.database.fetch(STATION_TABLE, ("station",),
                                       {"jid": msg.sender})
            if rows:
                src = rows[0]['station']
            else:
                msg.reply("You must either specify a source station, or save "
                          "a nearest station (with the 'nearest station' "
                          "command)")
                return
        url = "/{}/{}{}{}{}".format(
                src, dst, ("/" + time) if time else "",
                "a" if typ == "arriving" else "",
                ("/" + when.replace(" ", "-")) if when else "")
        getPage("http://www.traintimes.org.uk" + urllib.quote(url)
                ).addCallbacks(extract_results, lambda x: msg.reply("Bad train request"))

    @staticmethod
    def _canonical_time(time):
        match = TIMERE.match(time.strip())
        assert match, "We've already checked this - how can it fail?!"
        hour, minute, half = match.groups()
        if len(hour) == 4 and not minute and not half:
            # This is just a 4 digit number, treat as if its a time in 24h
            minute = hour[2:]
            hour = hour[:2]
        hour, minute = map(lambda n: int(n) if n else 0, (hour, minute))
        if hour > 24:
            return None
          
        if half and half == 'pm':
            if hour <= 12:
                hour += 12
        return "{}:{:02}".format(hour, minute)
