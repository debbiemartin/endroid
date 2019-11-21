# -----------------------------------------
# Endroid - XMPP Bot
# Copyright 2012, Ensoft Ltd.
# Created by Jonathan Millican
# -----------------------------------------

import logging
import twisted.words.protocols.jabber.jid
from twisted.words.protocols.jabber.jid import InvalidFormat
from twisted.words.protocols.jabber.error import StanzaError
from endroid.pluginmanager import PluginManager
from random import choice
from collections import namedtuple
from collections import defaultdict

from twisted.internet import defer

# we use ADJECTIVES to generate a random new nick if endroid's is taken
ADJECTIVES = [
    "affronted", "annoyed", "antagonized", "bitter", "chafed", "convulsed",
    "cross", "displeased", "enraged", "exasperated", "ferocious", "fierce",
    "fiery", "fuming", "furious", "galled", "hateful", "heated", "impassioned",
    "incensed", "indignant", "inflamed", "infuriated", "irascible", "irate",
    "ireful", "irritated", "maddened", "offended", "outraged", "provoked", 
    "raging", "resentful", "splenetic", "storming", "vexed", "wrathful"]

MUC = "muc#roomconfig_"

Place = namedtuple("Place", ("type", "name"))


class JID(twisted.words.protocols.jabber.jid.JID):
    """
    Wrapper around twisteds JID class to provide more functionality.


    Attributes:
        Inherited from twisted:
          user - the user part of the JID
          host - the host part of the JID
          resource - the resource part of the JID
        Added by this class:
          nick - nickname of this JID if in a room

    Methods:
        Inherited from twisted:
          full - string representation of the JID - use str(JID) instead
          userhost - string representation of just the user and host
                     parts of this JID
          userhostJID - a new JID object representing just the user and 
                        host parts of this JID
          
    """

    def __init__(self, str=None, tuple=None, nick=None, **kwargs):
        self.nick = nick
        super(JID, self).__init__(str=str, tuple=tuple, **kwargs)

    def __str__(self):
        return self.full()


class Roster(object):
    """
    Provides functions for maintaining sets of users registered with and
    available in a contact list, user group or room.

    """
    def __init__(self, name=None, registration_cb=None, deregistration_cb=None):
        self.name = name or "contacts"

        self._members = {}  # dict of userhosts to resources
        self.registration_cb = registration_cb or (lambda a, b: None)
        self.deregistration_cb = deregistration_cb or (lambda a, b: None)

    @property
    def available(self):
        # jids is a set of the resources on which a user is available
        # if jids is empty then the user is unavailable 
        return set(u for (u, avs) in self._members.items() if avs)

    @property
    def registered(self):
        return set(self._members.keys())

    def is_available(self, user):
        """
        Return TRUE if the user is available in this place.

        user should be a JID object. This function will consider resource if
        user has one.

        """

        if user.userhost() in self._members:
            if user.resource:
                return user.resource in self._members[user.userhost()]
            else:
                return len(self._members[user.userhost()]) > 0
        else:
            return False

    def get_resources(self, name):
        return self._members.get(name, {})

    def set_registration_list(self, names):
        # if we have a list callback then don't do sub-callbacks
        for name in self.registered:
            if not name in names:
                self.deregister_user(name)
        for name in names:
            self.register_user(name)

    def register_user(self, name):
        if not name in self._members:
            self._members[name] = {}
            self.registration_cb(name, self.name)

    def deregister_user(self, name):
        self._members.pop(name, None)
        self.deregistration_cb(name, self.name)

    def set_available(self, jid, show=None, priority=0):
        """
        Mark a JID as available.

        jid should be a JID object

        """

        logging.debug("{} available at resource {}".format(jid.userhost(), jid.resource))

        if jid.userhost() in self._members:
            self._members[jid.userhost()][jid.resource] = Resource(show, priority)

    def set_unavailable(self, jid):
        """
        Mark a JID as unavailable.

        jid should be a JID object

        """

        logging.debug("{} unavailable at resource {}".format(jid.userhost(), jid.resource))

        if jid.userhost() in self._members:
            self._members[jid.userhost()].pop(jid.resource, None)

    def __repr__(self):
        name = self.name or "contacts"
        users = [u + ("(available)" if jids else "") 
                    for (u, jids) in self._members.items()]
        return "{}({}: {})".format(type(self).__name__, name, ', '.join(users))


class Room(Roster):
    config_default = {MUC + k : v for (k, v) in [
            ("allowinvites", False),
            ("changesubject",True),
            ("membersonly", True),
            ("moderatedroom", True),
            ("passwordprotectedroom", False),
            ("persistentroom", False),
            ("publicroom", False),
            ("roomdesc", "An Endroid chatroom"),
            ("roomname", "Ensoft"),
        ]
    }
    # these are the user configurable options
    config_options = {
        'password' : "roomsecret",
        'persistent' : "persistentroom",
        'name' : "roomname",
        'description' : "roomdesc",
    }

    @staticmethod
    def translate_options(options):
        def translate(key):
            return MUC + Room.config_options[key]

        do_password = options.get('password', False)
        options = {translate(k): v for (k, v) in options.items() 
                        if k in Room.config_options}
        if do_password:
            options[MUC + "passwordprotectedroom"] = True
        return options

    def __init__(self, name, nick, password, um, *args, **kwargs):
        self.nick = nick
        self.password = password

        # Allow endroid to change its nickname if it fails to join a chat 
        # (in case it was due to a nickname collision).
        #
        # Currently set to False, as True will not work with servers that do 
        # not allow nickname changes (Wokkel doesn't 'see' the join response 
        # in this case as the server replies using the full jid whereas Wokkel 
        # is waiting for a reply using the nickname). Could add a config option
        # to control this behaviour in the future.
        self.allow_nick_change = False

        # Keep a reference to the usermanagement object
        # @@@ Evil hack until the roomowner plugin can register for
        # presence notifications - the UM ref is needed to kick
        # unwanted members
        self.um = um

        super(Room, self).__init__(name, *args, **kwargs)

    def set_available(self, user):
        """
        Mark a user as being available in a room.

        user is a JID object.
        If the user isn't registered with the room they are kicked.

        """

        logging.debug("{} ({}) joined room {}".format(
                      user.nick, user, self.name))
        if user.userhost() in self._members:
            self._members[user.userhost()][user.resource] = Resource(False, 1)
        else:
            # This person shouldn't be here, kick
            self.um.kick(room=self.name, nick=user.nick, reason="You are "
                         "not on the memberlist, sorry.")

    def set_unavailable(self, user):
        """Process a user leaving a room."""

        logging.debug("{} ({}) left room {}".format(
                      user.nick, user, self.name))
        if user.userhost() in self._members:
            self._members[user.userhost()].pop(user.resource, None)


class Resource(object):
    __slots__ = ("show", "priority")

    def __init__(self, show=None, priority=0):
        self.show = show
        self.priority = priority

    def __repr__(self):
        name = type(self).__name__
        return "{0}(show='{1.show}', priority='{1.priority}'".format(name, self)

class UserManagement(object):
    """An abstraction of XMPP's presence protocols."""

    JOIN_ATTEMPTS_MAX = 5

    def __init__(self, wh, rh, config, ping_sender):
        self.wh = wh
        self.rh = rh
        # as yet unused - is analagous to the _handlers attribute of
        # messagehandler but will respond to presence notifications
        self._handlers = {}

        self._pms = {}  # a dict of {room/group names : pluginmanager objects}

        self.jid = None
        self.jid_obj = None
        # our contact list and room list
        self._users = Roster(None, self._cb_add_contact, self._cb_rem_contact)
        self._rooms = Roster()
        # dictionaries of Roster objects for our groups and rooms
        self.group_rosters = {}
        self.room_rosters = {}

        self.conf = config
        self._read_config(config)

        self._callbacks_when_available = defaultdict(list)
        # contains key-value pairs jid, [callbacks]
        self._callbacks_when_unavailable = defaultdict(list)

        self._ping_sender = ping_sender

    def ping(self, jid):
        """
        XMPP Pings a string JID.
        :param JID: string JID of the user to ping.
        """
        return self._ping_sender.ping(JID(jid))

    def _allowed_users(self, r_g, name):
        """Get the set of allowed users for this room or group."""
    
        # The config get could return an empty list e.g. if 'users='
        users = set(self.conf.get(r_g, name, "users", default=self.users()))
        return users & self.users()

    def _read_config(self, config):
        # Set our contact list and room list
        self.jid = config.get("setup", "jid")
        self.jid_obj = JID(self.jid)
        self._users.set_registration_list(config.get("setup", "users", default=[]))
        self._rooms.set_registration_list(config.get("setup", "rooms", default=[]))

        self.join_attempts = config.get("setup", "join_attempts", 
                                        default=self.JOIN_ATTEMPTS_MAX)

        nick = config.get("setup", "nick", default=self.jid_obj.full())
        # Set contact lists for our rooms
        for room in config.get("setup", "rooms", default=[]):
            # What we need to join the room
            # @@@ Evil hack until roomowner can be made a global plugin
            # that triggers room joins
            password = config.get("room", room, "plugin", 
                                  "endroid.plugins.roomowner", "password",
                                  default="")
            try:
                users = config.get("room", room, "plugin",
                                   "endroid.plugins.roomowner", "users")
                users = set(users) & self.users()
            except KeyError:
                # User list may have been specified old style:
                users = self._allowed_users('room', room)
            self.room_rosters[room] = Room(room, nick, password, self)
            self.room_rosters[room].set_registration_list(users)

        for group in config.get("setup", "groups", default=['all']):
            self.group_rosters[group] = Roster(group)
            users = self._allowed_users("group", group)
            self.group_rosters[group].set_registration_list(users)

        # rosterhandler receives presence notifications and gives them to us
        self.rh.set_presence_handler(self)
        self.wh.set_presence_handler(self)

    ### Function about users and groups ###

    # given a group or room or None (our contact list), return list of users 
    # registered/available there
    def users(self, name=None):
        """
        Return an iterable of users registered with 'name'.

        If name is None, look in contact list.

        """
        if name is None:
            return self._users.registered
        elif name in self.group_rosters:
            return self.group_rosters[name].registered
        elif name in self.room_rosters:
            return self.room_rosters[name].registered
    get_users = users

    def resources(self, name=None):
        """
        Return an iterable of full jids at which 'name' is available.

        """
        if name is None:
            return self.jid
        else:
            return self._users.get_resources(name)

    def available_users(self, name=None):
        """
        Return an iterable of users present in 'name'.

        If name is None, look in contact list.

        """
        if name is None:
            return self._users.available
        elif name in self.group_rosters:
            return self.group_rosters[name].available
        elif name in self.room_rosters:
            return self.room_rosters[name].available
    get_available_users = available_users

    # given a user or None (us), return list of groups/rooms the user is 
    # registered/available in
    def groups(self, user=None):
        """
        Return an iterable of groups 'user' is registered with.

        If user is None, return all registered groups.

        """
        return self._get_user_place(user, self.group_rosters, get_available=False)
    get_groups = groups

    def available_groups(self, user=None):
        """
        Return an iterable of groups 'user' is present in.

        If user is None, return all groups EnDroid is available in.

        """
        return self._get_user_place(user, self.group_rosters, get_available=True)
    get_available_groups = available_groups

    def rooms(self, user=None):
        """
        Return an iterable of rooms 'user' is registered with.

        If user is None, return all registered rooms.

        """
        return self._get_user_place(user, self.room_rosters, get_available=False)
    get_rooms = rooms

    def available_rooms(self, user=None):
        """
        Return an iterable of rooms 'user' is present in.

        If user is None, return all rooms EnDroid is available in.

        """
        return self._get_user_place(user, self.room_rosters, get_available=True)
    get_available_rooms = available_rooms

    def _get_user_place(self, user, dct, get_available):
        """
        Return the list of places in dct 'user' is available in
        (if get_available) or registered with.

        """
        user = self.get_userhost(user)
        if user is None:
            return dct.keys()
        elif user in self.users():
            attr = "available" if get_available else "registered"
            return [p for p, roster in dct.items() if user in getattr(roster, attr)]
        else:
            return []

    def nickname(self, user, place=None):
        """
        Given a user jid (user@ho.s.t) return the user's nickname in place,
        or if place is None (default), the user part of the jid.

        """
        user_jid = JID(user)
        if place is None or place in self.group_rosters:
            return user_jid.user
        elif place in self.room_rosters:
            for (nick, rosteritem) in self.wh._rooms[JID(place)].roster.items():
                if user_jid.userhost() == rosteritem.entity.userhost():
                    return nick
        return "unknown"
    get_nickname = nickname

    ### Functions for managing contact lists ###

    def register_user(self, name, place=None):
        """
        Add a user to the 'member' list for our contacts (place=None) or in a
        group or room.

        """
        if place is None:
            self._users.register_user(name)
        elif place in self.group_rosters:
            self.group_rosters[place].register_user(name)
        elif place in self.room_rosters:
            self.room_rosters[place].register_user(name)

    def deregister_user(self, name, place=None):
        """
        Remove a user from the 'member' list for our contacts (place=None) or
        in a group or room.

        """
        if place is None:
            self._users.deregister_user(name)
        elif place in self.group_rosters:
            self.group_rosters[place].deregister_user(name)
        elif place in self.room_rosters:
            self.room_rosters[place].deregister_user(name)

    def _register_presence_callback(self, user, callback,
                                    available=False, unavailable=False):
        """
        Register a callback that is to fire when the user changes presence.
        This is a one-shot event: when the user next changes presence in the
        specified way, the callback will fire and then be forgotten.
        The "specified way" is determined by which combination of available=True
        and unavailable=True is supplied to register_presence_callback.
        Raises ValueError if neither available nor unavailable is passed as True.
        :param user: partial JID of the user to associate this callback with
        :param callback: a callback, no arguments, to be called when the user changes presence
        :param available: set True to have callback fire when user comes online
        :param unavailable: set True to have callback fire when user goes offline
        """
        if not (unavailable or available):
            raise ValueError('Callback specified neither available nor unavailable')

        if user not in self.users():
            raise ValueError('Invalid user {}'.format(user))

        if available:
            self._callbacks_when_available[user].append(callback)
        if unavailable:
            self._callbacks_when_unavailable[user].append(callback)


    def set_available(self, user, place=None, show=None, priority=0):
        """
        Add a user to the 'available' list for our contacts (place=None) or in a
        group or room.

        user should be a JID object

        """

        # call all our relevant callbacks we've been assigned for when this user
        # becomes available
        if place is None:
            username = user.userhost()
            callbacks_to_call = self._callbacks_when_available.pop(username, [])

            for cb in callbacks_to_call:
                cb()

        if place is None:
            self._users.set_available(user, show, priority)
        elif place in self.group_rosters:
            self.group_rosters[place].set_available(user, show, priority)
        elif place in self.room_rosters:
            self.room_rosters[place].set_available(user)
        else:
            logging.error("User {} available but {} not in any roster".format(
                          user, place))

    def set_unavailable(self, user, place=None):
        """
        Add a user to the 'available' list for our contacts (place=None) or in a
        group or room.

        user should be a JID object
        """

        if place is None:
            username = user.userhost()
            callbacks_to_call = self._callbacks_when_unavailable.pop(username, [])

            for cb in callbacks_to_call:
                cb()

        if place is None:
            self._users.set_unavailable(user)
        elif place in self.group_rosters:
            self.group_rosters[place].set_unavailable(user)
        elif place in self.room_rosters:
            self.room_rosters[place].set_unavailable(user)
        else:
            logging.error("User {} unavailable but {} not in any roster".format(
                          user, room))

    # callbacks for adding/removing from our main contact list
    def _cb_add_contact(self, name, _):
        logging.info("Adding contact: {}".format(name))
        self.rh.setItem(name)
        # send a subscribe request - confirmation in rosterhandler.subscribeReceived
        self.rh.subscribe(JID(name))
        self.rh.available(JID(name))

    def _cb_rem_contact(self, name, _):
        logging.debug("Removing contact: {}".format(name))
        self.rh.removeItem(name)  # sets the subscription to None both ways
        logging.info("Removed {} from {}".format(name, "contacts"))

    ### Room functions

    def join_room(self, name, nick=None, max_attempts=0):
        """
        Attempt to join the room 'name'.

        Retries the join up to 'max_attempts' times. If 'max_attempts' is 0,
        uses the configured value of 'join_attempts'.

        Returns a Deferred that fires with the room name on success, or the
        latest reason for failure if all attempts are exhausted.

        """
        logging.debug("Attempting to join {} (max attempts {})".format(
                      name, max_attempts))
        if not name in self.room_rosters:
            return defer.fail(ValueError("{} not in configured rooms"
                                         .format(name)))

        if max_attempts == 0:
            max_attempts = self.join_attempts
        room = self.room_rosters[name]
        if nick is None:
            nick = room.nick

        def _retry(failure, room, nick, attempts):
            logging.debug("Failed to join {}: {}".format(room.name, 
                                                         str(failure.value)))
            attempts -= 1
            if attempts > 0:
                # Try a different nickname (if we are allowed to) in case we
                # failed to join due to name collision
                if room.allow_nick_change:
                    nick = "{} ({} and {})".format(room.nick, 
                                                   choice(ADJECTIVES), 
                                                   choice(ADJECTIVES))
                return self.join_room(room.name, nick, max_attempts=attempts)
            else:
                return failure
        @defer.inlineCallbacks
        def _joined(_, room, nick, attempts):
            if nick != room.nick:
                yield self.kick(room.name, room.nick, "You've taken EnDroid's "
                                "nick, please reconnect with another nick")
                self.wh.nick(JID(room.name), room.nick)
            defer.returnValue(room.name)

        d = self.wh.join(JID(name), nick, password=room.password)
        # Use addCallbacks here so only one _joined is called in the event of
        # potentially multiple retries
        d.addCallbacks(_joined, _retry,
                       callbackArgs=(room, nick, max_attempts),
                       errbackArgs=(room, nick, max_attempts))
        
        return d

    def kick(self, room, nick, reason=None):
        """
        Kick the user with the specified nick from the room.

        Returns a deferred which can be monitored to determine if the kick was
        successful.

        """

        def success(_):
            logging.info("Kicked {} from {} ({})".format(nick, room, reason))
        def failure(_):
            logging.error("Failed to kick {} from {} ({})".format(
                          nick, room, reason))
            #@@@ This swallows errors. Seems expected at the moment, but future
            # callers may want to see the error. Make sure to update all
            # current callers if this is ever changed.

        return self.wh.kick(JID(room), nick, reason).addCallbacks(success, failure)

    def joined_room(self, name):
        logging.info("Joined room {}".format(name))
        self._rooms.set_available(JID(name))
        if name not in self._pms:
            self.start_pm(None, "room", name)

    def joined_group(self, name):
        logging.info("Initialised group {}".format(name))
        if not name in self._pms:
            self.start_pm(None, "group", name)

    # register a new pluginmanager (which will initialise plugins) in room or
    # group 'name'
    def start_pm(self, _, place, name):
        self._pms[name] = PluginManager(self.wh.messagehandler, self, place, 
                                        name, self.conf)

    def connected(self):
        self._pms[None] = PluginManager(self.wh.messagehandler, self, "global",
                                        None, self.conf)
        # Should join all rooms and groups here
        # Currently called from elsewhere

    def join_all_rooms(self):
        def _fail(fail, room):
            logging.error("Failed to join room ({}): {}"
                          .format(room, str(fail.value)))
        for room in self.get_rooms():
            d = self.join_room(room)
            d.addCallback(lambda _, r: self.joined_room(r), room)
            d.addErrback(_fail, room)

    def handle_room_invite(self, name):
        """Handle an invitation to join room name."""
        def _fail(fail, room):
            logging.error("Failed to accept invitation to room {}: {}"
                          .format(room, str(fail.value)))

        # We only want to attempt to join the room once, to avoid retrying
        # multiple times in the case where we are invited to a 'bad' room.
        # User can manually retry in other error conditions by sending another
        # invite request
        d = self.join_room(name, max_attempts=1)
        d.addCallback(lambda r: self.joined_room(r))
        d.addErrback(_fail, name)

    # @@@ This function is in the wrong place. This is the room section
    def join_all_groups(self):
        for group in self.get_groups():
            self.joined_group(group)

    def room_modify_affiliation(self, room, users, affiliation):
        """Update the affiliation list for this room."""

        # Check that only EnDroid's contacts can be added to rooms
        user_set = set(users)
        un_reg_users = user_set - self.users()
        if len(un_reg_users) > 0 and affiliation != 'none':
            logging.warning('Attempt to allow {} unregistered user(s) '
                            'access to {}'.format(len(un_reg_users), room))

        allowed_users = user_set & self.users()
        
        jids = [JID(user) for user in allowed_users]
        d = self.wh.modifyAffiliationList(JID(room), jids, affiliation)
        log_fmt = '{} affiliation for {} users in room {} to {}'
        d.addCallback(lambda _: logging.info(
                      log_fmt.format('Changed', len(users), room, affiliation)))
        d.addErrback(lambda _: logging.error(
                     log_fmt.format('Failed to change', len(users), room, 
                     affiliation)))
        return d

    def room_memberlist_change(self, room, users, remove=False):
        if remove:
            return self.room_modify_affiliation(room, users, 'none')
        else:
            return self.room_modify_affiliation(room, users, 'member')

    def configure_room(self, name, options):
        """
        Set/modify the configuration of room 'name'. Options is a dictionary
        of option names to values. Currently configurable options 
        (Room.config_options) are: password, persistent, name (roomname) and 
        description.

        """
        def conf_failed(failure):
            failure.trap(StanzaError)
            logging.error("Failure configuring {}: code {}".format(name,
                          failure.value.code))

        def cb(value):
            logging.info("Configured {}".format(name))

        mucoptions = Room.config_default.copy()
        # options is a human-readable dict, we intersect with Room.config_options
        # and translate into muc#roomconfig_xxx terms in translate_options
        mucoptions.update(Room.translate_options(options))
        d = self.wh.configure(JID(name), mucoptions)
        d.addCallback(cb)
        d.addErrback(conf_failed)
        return d

    def get_configuration(self, name):
        """
        Get a MUC's configuration.

        Return a deferred which will receive the config.

        """

        if name in self.get_rooms():
            return self.wh.getConfiguration(JID(name))

    def is_room_owner(self, room):
        """Find out if EnDroid is an owner for the specified room. """

        def determine_if_owner(owner_list):
            """True if EnDroid's userhost is in the owner list."""

            return self.jid_obj.userhost() in owner_list

        def error_determining_ownership(failure):
            # Re-raise the failure if its not a StanzaError
            failure.trap(StanzaError)
            
            if failure.value.code == '403':
                # This is the forbidden code - so no EnDroid doesn't own the
                # room
                return False
            else:
                # If it's any other error let the caller deal with it
                logging.error("Error determining ownership of {}. Code "
                              "{}".format(room, failure.value.code))
                return failure

        if room in self.get_rooms():
            return self.get_room_ownerlist(room).addCallbacks(
                determine_if_owner, error_determining_ownership)
        else:
            # Always return a deferred
            return twisted.internet.defer.fail()

    def get_configured_room_memberlist(self, room):
        """
        Return the list (if any) of configured members for this room.

        This is to support old style config where the user list was owned by
        EnDroid core.

        """
        return self._allowed_users('room', room)

    def _convert_admin_list(self, admin_list):
        """Convert the list of AdminItems into userhosts."""

        return [admin.entity.userhost() for admin in admin_list]

    def get_room_ownerlist(self, room):
        """
        Get the owner list for a room.

        Note: EnDroid must be room owner for this to work.

        """

        if room in self.get_rooms():
            return self.wh.getOwnerList(JID(room)).addCallback(
                self._convert_admin_list)
        else:
            # Always return a deferred
            return twisted.internet.defer.fail()

    def get_room_memberlist(self, room):
        """
        Get the member list for a room.

        Note: EnDroid must be room owner for this to work.

        """

        if room in self.get_rooms():
            return self.wh.getMemberList(JID(room)).addCallback(
                self._convert_admin_list)
        else:
            # Always return a deferred
            return twisted.internet.defer.fail()

    def invite(self, user, room, reason=None):
        """
        Invite a user to a room.

        Will only send invitation if the user is in our contact list, online,
        registered in the room and not currently in it.

        Returns a tuple (success, message)

        """

        user_jid = JID(user)
        userhost = user_jid.userhost()
        if userhost not in self.users():
            return (False, "User not registered")
        elif userhost not in self.available_users():
            return (False, "User not available")
        elif room not in self.get_rooms(userhost):
            if room not in self.get_rooms():
                reason = "Room not registered"
            else:
                reason = "User not registered in room"
            return (False, reason)
        else:
            room_roster = self.room_rosters[room]
            if room_roster.is_available(user_jid):
                return (False, "User already in room")
            else:
                self.wh.invite(JID(room), user_jid, reason)
                return (True, "Invitation sent")

    @staticmethod
    def get_userhost(item):
        """
        This is usually applied to a Message's sender attribute which we expect
        to be a string or None. It will attempt to return a userhost string but
        if it fails will just return the input.

        """
        try:
            return JID(item).userhost()
            # will raise a RuntimeError if item is None
            # or an InvalidFormat if item is a string but not formatted properly
            # If the item is not even a string, will raise AttributeError
        except (RuntimeError, InvalidFormat, AttributeError):
            return item

    @staticmethod
    def get_host(item):
        """
        Given a string JID, returns the host part.
        For example, in abc@de.f/resource, it would return de.f.
        """
        return item.split('@')[1].split('/')[0]

    def for_plugin(self, pluginmanager, plugin):
        return PluginUserManagement(self, pluginmanager, plugin)

class PluginUserManagement(object):
    """
    One of these exists per plugin, provides the API to handle rosters.
    """
    def __init__(self, usermanagement, pluginmanager, plugin):
        self._usermanagement = usermanagement
        self._pluginmanager = pluginmanager
        self._plugin = plugin

    @property
    def users(self):
        return self._usermanagement.users(self._pluginmanager.name)

    @property
    def available_users(self):
        return self._usermanagement.available_users(self._pluginmanager.name)

    def is_online(self, user):
        """
        Return True/False if the JID user is on/offline.

        Optional argument name, to specify which roster to look in; None to
        look only in the contact list.
        """
        return user in self.available_users

    def nickname(self, user):
        return self._usermanagement.nickname(user, self._pluginmanager.name)

    def invite(self, user, reason=None):
        if self._pluginmanager.place != "room":
            raise ValueError("Must be in a room to invite users")
        return self._usermanagement.invite(user, self._pluginmanager.name,
                                           reason=reason)

    def register_presence_callback(self, user, callback,
                                   available=False, unavailable=False):
        """
        Register a callback that is to fire when the user changes presence.
        This is a one-shot event: when the user next changes presence in the
        specified way, the callback will fire and then be forgotten.
        The "specified way" is determined by which combination of available=True
        and unavailable=True is supplied to register_presence_callback.
        Raises ValueError if neither available nor unavailable is passed as True.
        :param user: partial JID of the user to associate this callback with
        :param callback: a callback, no arguments, to be called when the user changes presence
        :param available: set True to have callback fire when user comes online
        :param unavailable: set True to have callback fire when user goes offline
        """

        if user not in self.users:
            raise ValueError('Invalid user {}'.format(user))
        self._usermanagement._register_presence_callback(user, callback,
                                                         available=available,
                                                         unavailable=unavailable)
