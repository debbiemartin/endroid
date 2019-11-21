# -----------------------------------------
# Endroid - Room inviter
# Copyright 2013, Ensoft Ltd.
# Created by Ben Hutchings
# -----------------------------------------

from endroid.plugins.command import CommandPlugin, command
import shlex
import re

def parse_string(string, options=None):
    """
    Parse a shell command like string into an args tuple and a kwargs dict.

    Options is an iterable of string tuples, each tuple representing a keyword
    followed by its synonyms.

    Words in string will be appended to the args tuple until a keyword is
    reached, at which point they will be appended to a list in kwargs.

    Eg parse_string("a b c -u 1 2 3 -r 5 6", [("-u",), ("room", "-r")])
    will return: ('a', 'b', 'c'), {'-u': ['1','2','3'], 'room': ['5','6']}

    """
    options = options or []
    aliases = {}

    keys = []
    # build the kwargs dict with all the keywords and an aliases dict for synonyms
    for option in options:
        if isinstance(option, (list, tuple)):
            main = option[0]
            keys.append(main)
            for alias in option[1:]:
                aliases[alias] = main
        elif isinstance(option, (str, unicode)):
            keys.append(option)

    args = []
    kwargs = {}
    current = None
    # parse the string - first split into shell 'words'
    parts = shlex.split(string)
    # then add to args or the kwargs dictionary as appropriate
    for part in parts:
        # if it's a synonym get the main command, else leave it
        part = aliases.get(part, part)
        if part in keys:
            # we have come to a keyword argument - create its list
            kwargs[part] = []
            # keep track of where we are sending non-keyword words to
            current = kwargs[part]
        elif current is not None:
            # we are adding words to a keyword's list
            current.append(part)
        else:
            # no keywords has been found yet - we are still in args
            args.append(part)

    return args, kwargs

def replace(l, search, replace):
    return [replace if item == search else item for item in l]


class Invite(CommandPlugin):
    help = "Invite users to rooms"
    name = "invite"
    PARSE_OPTIONS = (("to", "into"),)

    @command(helphint="{to|into}? <room>+")
    def invite_me(self, msg, arg):
        """
        Invite user to the rooms listed in args, or to all their rooms 
        if args is empty.

        """
        args, kwargs = parse_string(arg, self.PARSE_OPTIONS)
        users = [msg.sender_full]
        rooms = set(args + kwargs.get("to", [])) or ["all"]

        results = self._do_invites(users, rooms)
        msg.reply(results)

    @command(helphint="<reason>", muc_only=True)
    def invite_all(self, msg, arg):
        """Invite all of a room's registered users to the room."""
        reg_users = set(self.usermanagement.get_users(self.place_name))
        avail_users = set(self.usermanagement.get_available_users(self.place_name))
        users = reg_users - avail_users
        rooms = [self.place_name]

        if len(users) > 0:
            results = self._do_invites(users, rooms)
        else:
            results = "All registered users are available in the room."
        msg.reply(results)

    @command(helphint="<user>+ {to|into} <room>+")
    def invite_users(self, msg, arg):
        """Invite a list of users to a list of rooms."""
        args, kwargs = parse_string(arg, self.PARSE_OPTIONS)
        users = replace(args, "me", msg.sender_full)
        rooms = kwargs.get("to", [])

        results = self._do_invites(users, rooms)
        msg.reply(results)

    def _do_invites(self, users, rooms):
        if 'all' in users:
            if len(rooms) == 1 and 'all' not in rooms:
                users = self.usermanagement.get_users(rooms[0])
            else:
                return "Can only invite 'all' users to a single room"

        users = self._fuzzy_match(users, self.usermanagement.get_users())

        if 'all' in rooms:
            if len(users) == 1:
                rooms = self.usermanagement.get_rooms(users[0])
                if not rooms:
                    return ("There are no rooms to invite user '{}' "
                            "to.".format(users[0]))
            else:
                return "Can only invite a single user to 'all' rooms"

        rooms = self._fuzzy_match(rooms, self.usermanagement.get_rooms())

        if not users:
            return "User not found."
        if not rooms:
            return "Room not found."

        results = []
        invitations = 0
        for room in rooms:
            for user in users:
                s, reason = self.usermanagement.invite(user, room)
                if not s:
                    results.append("{} to {} failed: {}".format(user, room, reason))
                else:
                    invitations += 1

        reply = "Sent {} invitations.".format(invitations)
        if results:
            reply +=  '\n' + '\n'.join(results)
        return reply

    @staticmethod
    def _fuzzy_match(partials, fulls):
        """
        For lists 'partials' and 'fulls', elements of partials (<p>) are
        mapped to elements of fulls (<f>) by the following rules:

        1) If <p> has a '/' that suggests a resource has been specified.
           Fulls will just be userhost so assume <p> exact
        2) If <p> is in <fulls>, then return <p> (exact_match)
        3) If "<p>@.*" matches exactly one <f> then return <p> (startswith_at)
        4) If "<p>.*" matches exactly one <f> then return <p> (startswith)
        5) If ".*<p>.*" matches exactly one <f> then return <p> (contains)

        """
        result = []

        for partial in partials:
            exact_match = None  # an exact match for '<partial>' in fulls
            startswith_at = []  # list of fulls starting with '<partial>@'
            startswith = []  # list of fulls starting with '<partial>'
            contains = []  # list of fulls containing '<partial>'

            if '/' in partial:
                # Assume resource specified. This function doesn't need to
                # to verify each room/user is correct as UM does that
                result.append(partial)
                continue

            for full in fulls:
                if partial == full:
                    # we have found an exact match, don't look at other fulls
                    exact_match = full
                    break
                # eg room will match room@serv.er
                elif full.startswith(partial + '@'):
                    startswith_at.append(full)
                # eg room will match room@serv.er, room1@serv.er etc
                elif full.startswith(partial):
                    startswith.append(full)
                # eg room will match aroom@serv.er, broom1@serv.er etc
                elif partial in full:
                    contains.append(full)

            # case 1
            if exact_match:
                result.append(exact_match)
            # cases 2, 3, 4: for each check that there is exactly one match
            elif len(startswith_at) == 1:
                result.extend(startswith_at)
            elif len(startswith) == 1:
                result.extend(startswith)
            elif len(contains) == 1:
                result.extend(contains)
            # else: we have multiple possible matches, so ignore them

        return result
