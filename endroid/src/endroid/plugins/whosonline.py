# -----------------------------------------
# Endroid - XMPP Bot
# Copyright 2012, Ensoft Ltd.
# Created by Jonathan Millican, updated to CommandPlugin by Patrick Stevens
# -----------------------------------------

from endroid.plugins.command import CommandPlugin, command

class WhosOnline(CommandPlugin):
    name = "whosonline"
    dependencies = ('endroid.plugins.command',)
    help = ("List who is online with whosonline; list the available rooms with listrooms; "
            "ask if a user is online with isonline <username>")

    @command
    def whosonline(self, msg, arg):
        msg.reply('\n'.join(self.online_list()))

    def is_online(self, jid):
        return self.rosters.is_online(jid)

    def online_list(self):
        return self.usermanagement.get_available_users()

    @command
    def listrooms(self, msg, arg):
        # Only list rooms that the user is allowed in
        rooms = [room
                 for room in self.usermanagement.get_available_rooms()
                 if msg.sender in self.usermanagement.get_users(room)] or [
                                                       "I'm not in any rooms!"]
        msg.reply('\n'.join(rooms))

    @command(synonyms=('isonline',), helphint='{user}')
    def online(self, msg, arg):
        msg.reply('Yes, online' if self.is_online(arg) else 'Not online')
