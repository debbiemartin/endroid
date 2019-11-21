# -----------------------------------------------------------------------------
# Endroid - Webex Bot
# Copyright 2012, Ensoft Ltd.
# Created by Martin Morrison
# -----------------------------------------------------------------------------

from endroid.pluginmanager import Plugin
from endroid.database import Database
from endroid.cron import Cron

# DB constants
DB_NAME = "Blacklist"
DB_TABLE = "Blacklist"
CRON_UNBLACKLIST = "Blacklist_UnBlacklist"

class Blacklist(Plugin):
    """
    Plugin to provide blacklisting capabilities for EnDroid.

    This plugin provides a mechanism for administrators (specified in config)
    to manage a blacklist of JIDs. Any messages sent to or from any JID in this
    list is silently dropped, without allowing any handlers to be called for
    them.
    """
    help = "Maintain a blacklist of users who get ignored by EnDroid."
    hidden = True

    _blacklist = set()

    def endroid_init(self):
        """
        Initialise the plugin, and recover the blacklist from the DB.
        """
        self.admins = set(map(str.strip, self.vars.get("admins", [])))

        self.task = self.cron.register(self.unblacklist, CRON_UNBLACKLIST)

        self.messages.register(self.checklist, recv_filter=True)
        self.messages.register(self.command, chat_only=True)
        self.messages.register(self.checksend, send_filter=True, chat_only=True)

        if not self.database.table_exists(DB_TABLE):
            self.database.create_table(DB_TABLE, ("userjid",))
        for row in self.database.fetch(DB_TABLE, ("userjid",)):
            self.blacklist(row["userjid"])

    def get_blacklist(self):
        return self._blacklist
        
    def checklist(self, msg):
        """
        Receive filter callback - checks the message sender against the
        blacklist
        """
        return msg.sender not in self.get_blacklist()

    def checksend(self, msg):
        """
        Send filter callback - checks the message recipient against the
        blacklist
        """
        return msg.recipient not in self.get_blacklist()

    def command(self, msg):
        """
        Command callback handler. Provides support for the "blacklist" command,
        which can only be used by people configured as admins, and supports
        "add", "remove" and "list" arguments to manage the list.
        """
        parts = msg.body.split()
        while len(parts) < 3:
            parts.append(None)
        bl, cmd, user = parts[:3]

        if msg.sender in self.admins and bl == "blacklist":
            if cmd == "add" and user not in self.get_blacklist():
                self.blacklist(user)
            elif cmd == "remove" and user in self.get_blacklist():
                self.unblacklist(user)
            elif cmd == "list":
                msg.reply("Blacklist: " + ", ".join(self.get_blacklist() or ['None']))
            else:
                msg.unhandled()
        else:
            msg.unhandled()

    def blacklist(self, user, duration=0):
        """
        Add the specified user to the blacklist. If the optional duration
        argument is passed, the user is removed after the specified number of
        seconds.
        """
        self.database.delete(DB_TABLE, {"userjid": user})
        self.database.insert(DB_TABLE, {"userjid": user})
        self._blacklist.add(user)
        if duration != 0:
            self.task.setTimeout(duration, user)

    def unblacklist(self, user):
        """
        Remove the specified user from the blacklist.
        """
        self.database.delete(DB_TABLE, {"userjid": user})
        self._blacklist.remove(user)
