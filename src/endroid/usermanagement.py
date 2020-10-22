# -----------------------------------------
# Endroid - Webex Bot
# Copyright 2012, Ensoft Ltd.
# Created by Jonathan Millican
# -----------------------------------------

import logging
from endroid.pluginmanager import PluginManager
from random import choice
from collections import namedtuple
from collections import defaultdict

from twisted.internet import defer

MUC = "muc#roomconfig_"

Place = namedtuple("Place", ("type", "name"))


class Roster(object):
    """
    Provides functions for maintaining sets of users registered with and
    available in a contact list, user group or room.

    """
    def __init__(self, name=None, registration_cb=None, deregistration_cb=None):
        self.name = name or "contacts"

        self._members = set()  # list of names 
        self.registration_cb = registration_cb or (lambda a, b: None)
        self.deregistration_cb = deregistration_cb or (lambda a, b: None)

    @property
    def registered(self):
        return self._members

    def set_registration_list(self, names):
        # if we have a list callback then don't do sub-callbacks
        for name in self.registered:
            if not name in names:
                self.deregister_user(name)
        for name in names:
            self.register_user(name)

    def register_user(self, name):
        if not name in self._members:
            self._members.add(name) 
            self.registration_cb(name, self.name)

    def deregister_user(self, name):
        self._members.pop(name, None)
        self.deregistration_cb(name, self.name)

    def __repr__(self):
        name = self.name or "contacts"

        users = [u for u in self._members] 
        return "{}({}: {})".format(type(self).__name__, name, ', '.join(users))


class Resource(object):
    __slots__ = ("show", "priority")

    def __init__(self, show=None, priority=0):
        self.show = show
        self.priority = priority

    def __repr__(self):
        name = type(self).__name__
        return "{0}(show='{1.show}', priority='{1.priority}'".format(name, self)

class UserManagement(object):
    """An abstraction of Webex's presence protocols."""

    JOIN_ATTEMPTS_MAX = 5

    def __init__(self, wh, config):
        self.wh = wh

        # as yet unused - is analagous to the _handlers attribute of
        # messagehandler but will respond to presence notifications
        self._handlers = {}

        self._pms = {}  # a dict of {room/group names : pluginmanager objects}

        # our contact list and room list
        self._users = Roster(None)
        self._rooms = Roster()
        # dictionaries of Roster objects for our groups and rooms
        self.group_rosters = {}
        self.room_rosters = {}

        self.conf = config
        self._read_config(config)

        self._callbacks_when_available = defaultdict(list)
        # contains key-value pairs user, [callbacks] 
        self._callbacks_when_unavailable = defaultdict(list)

    def _allowed_users(self, r_g, name):
        """Get the set of allowed users for this room or group."""
    
        # The config get could return an empty list e.g. if 'users='
        users = set(self.conf.get(r_g, name, "users", default=self.users()))
        return users & self.users()

    def _read_config(self, config):
        # Set our contact list and room list
        self._users.set_registration_list(config.get("setup", "users", default=[]))
        self._rooms.set_registration_list(config.get("setup", "rooms", default=[]))

        # Set contact lists for our rooms
        for room in config.get("setup", "rooms", default=[]):
            # What we need to join the room
            # @@@ Evil hack until roomowner can be made a global plugin
            # that triggers room joins
            try:
                users = config.get("room", room, "plugin",
                                   "endroid.plugins.roomowner", "users")
                users = set(users) & self.users()
            except KeyError:
                # User list may have been specified old style:
                users = self._allowed_users('room', room)
            self.room_rosters[room] = Roster(room)
            self.room_rosters[room].set_registration_list(users)

        for group in config.get("setup", "groups", default=['all']):
            self.group_rosters[group] = Roster(group)
            users = self._allowed_users("group", group)
            self.group_rosters[group].set_registration_list(users)

        self.wh.set_user_management(self) 

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

    def available_users(self, name=None):
        """
        Return an iterable of users present in 'name'.

        If name is None, look in contact list.

        """
        if name is None:
            return self._users.registered
        elif name in self.group_rosters:
            return self.group_rosters[name].registered
        elif name in self.room_rosters:
            # Find the union of the room's member list and the room roster 
            # read in from config 
            members = self.wh.getMemberList(name)
            return self.room_rosters[name].registered.intersection(set(members))
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
        if user is None:
            return dct.keys()
        elif user in self.users():
            attr = "available" if get_available else "registered"
            return [p for p, roster in dct.items() if user in getattr(roster, attr)]
        else:
            return []

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
        :param user: the user to associate this callback with 
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

    ### Room functions

    def kick(self, room, user, reason=None): 
        """
        Kick the specified user from the room.

        Returns a deferred which can be monitored to determine if the kick was
        successful.

        """

        def success(_):
            logging.info("Kicked {} from {} ({})".format(user, room, reason))
        def failure(_):
            logging.error("Failed to kick {} from {} ({})".format(
                          user, room, reason))
            #@@@ This swallows errors. Seems expected at the moment, but future
            # callers may want to see the error. Make sure to update all
            # current callers if this is ever changed.

        return self.wh.kick(user, room, reason).addCallbacks(success, failure)

    def self_joined_room(self, room, remove=False):
        """
        Notify of Endroid joining a room.

        If the room is known, sanitizes the members in the room. Otherwise,
        removes self from the room.
        """
        logging.info("Joined room %s", room)
        
        if room not in self._rooms.registered:
            if remove:
                self.wh.messagehandler.send_muc(
                    room,
                    "Hello! If you'd like me to stay in this room please get "
                    "an EnDroid admin to add this RoomID ({}) to the "
                    "config!".format(room), self.wh.my_emails[0])
                self.wh.kick(self.wh.my_emails[0], room,
                             "Added to unrecognised room")
        else:
            # We are being added to a room - sanitize all members against
            # config
            members = self.wh.getMemberList(room)
            for member in members:
                if (member not in self.get_users(room) and
                    member not in self.wh.my_emails and remove):
                    self.wh.kick(member, room, 
                                 "Unexpected user present in room when added")

            if room not in self._pms: 
                self.start_pm(None, "room", room)

    def user_joined_room(self, room, user, remove=False):
        """
        Notify of a user joining a room Endroid is in.

        Kicks the user from the room if not in the set of registered members
        for the room.
        """
        if room in self._rooms.registered and \
           user not in self.get_users(room) and remove:
            self.wh.kick(user, room, "Unexpected user added to room")

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

    # @@@ This function is in the wrong place. This is the room section
    def join_all_groups(self): 
        for group in self.get_groups():
            self.joined_group(group)

    def is_room_owner(self, room):
        """Find out if EnDroid is an owner for the specified room. """

        def determine_if_owner(owner_list):
            """True if EnDroid's email is in the owner list."""
            
            return any(email in owner_list for email in self.wh.my_emails)

        def error_determining_ownership(failure):
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
            return defer.fail()

    def get_configured_room_memberlist(self, room):
        """
        Return the list (if any) of configured members for this room.

        This is to support old style config where the user list was owned by
        EnDroid core.

        """
        return self._allowed_users('room', room) 

    def get_room_ownerlist(self, room):
        """
        Get the owner list for a room.

        """
        # get_rooms returns a list of string versions of room IDs therefore 
        # convert the room ID under query to a string before comparison
        if str(room) in self.get_rooms():
            return defer.succeed(self.wh.getOwnerList(room)) 
        else:
            # Always return a deferred
            return defer.fail()

    def get_room_memberlist(self, room):
        """
        Get the member list for a room.

        """

        if room in self.get_rooms(): #@@@ this gives a string out?? 
            return self.wh.getMemberList(room)
        else:
            # Always return a deferred
            return defer.fail()

    def invite(self, user, room, reason=None):
        """
        Invite a user to a room.

        Will only send invitation if the user is in our contact list, online,
        registered in the room and not currently in it.

        Returns a tuple (success, message)

        """

        if user not in self.users():
            return (False, "User not registered")
        elif user not in self.available_users():
            return (False, "User not available")
        elif room not in self.get_rooms(user):
            if room not in self.get_rooms():
                reason = "Room not registered"
            else:
                reason = "User not registered in room"
            return (False, reason)
        else:
            room_roster = self.room_rosters[room]
            if room_roster[user] in self.wh.getMemberList(room):
                return (False, "User already in room")
            else:
                self.wh.invite(user, room, reason)
                return (True, "Invitation sent")

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
        Return True/False if the user is on/offline. 

        Optional argument name, to specify which roster to look in; None to
        look only in the contact list.
        """
        return user in self.available_users

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
        :param user: the user to associate this callback with 
        :param callback: a callback, no arguments, to be called when the user changes presence
        :param available: set True to have callback fire when user comes online
        :param unavailable: set True to have callback fire when user goes offline
        """

        if user not in self.users:
            raise ValueError('Invalid user {}'.format(user))
        self._usermanagement._register_presence_callback(user, callback,
                                                         available=available,
                                                         unavailable=unavailable)
