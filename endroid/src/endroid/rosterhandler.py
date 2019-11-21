# -----------------------------------------
# Endroid - XMPP Bot
# Copyright 2012, Ensoft Ltd.
# Created by Jonathan Millican
# -----------------------------------------

import logging

from endroid.usermanagement import JID
from wokkel.xmppim import RosterClientProtocol, PresenceClientProtocol, RosterItem


class RosterHandler(RosterClientProtocol, PresenceClientProtocol):
    def __init__(self):
        RosterClientProtocol.__init__(self)
        PresenceClientProtocol.__init__(self)
        self.deferred = None

    def set_presence_handler(self, um):
        self.um = um

    def setHandlerParent(self, parent):
        RosterClientProtocol.setHandlerParent(self, parent)
        PresenceClientProtocol.setHandlerParent(self, parent)

    def set_connected_handler(self, d):
        self.deferred = d
    
    def connectionInitialized(self):
        RosterClientProtocol.connectionInitialized(self)
        PresenceClientProtocol.connectionInitialized(self)

        def purge_roster(roster, self):
            # roster.keys() is a list of the users we are currently friends with.
            for user in (item.userhost() for item in roster.keys()):
                # if they have been removed from config since our last start
                if not user in self.um.users(): 
                    # get rid of them
                    self.um.deregister_user(user)  
            return roster  # pass the roster on for further callbacks

        rosterd = self.reRoster()
        rosterd.addCallback(purge_roster, self)

        if self.deferred:
            d, self.deferred = self.deferred, None
            rosterd.addCallback(d.callback)
        # Advertises as available - otherwise MUC will probably work
        # but SUC clients won't send messages on to EnDroid
        self.available()

    def reRoster(self):
        return self.getRoster()

    def setItem(self, name):
        if isinstance(name, RosterItem):
            super(RosterHandler, self).setItem(name)
        elif isinstance(name, (str, unicode)):
            super(RosterHandler, self).setItem(RosterItem(JID(name)))
        else:
            raise TypeError("RosterHandler.setItem got invalid type")

    def removeItem(self, name):
        logging.info("removeItem {}".format(name))
        super(RosterHandler, self).removeItem(JID(name))

    def subscribedReceived(self, presence):
        PresenceClientProtocol.subscribedReceived(self, presence)
        logging.info("Subscription request from {}".format(presence.userhost()))
        if presence.userhost() in self.um.users():
            # this is generated when someone has confirmed our subscription request
            # send a subscription _confirmation_ back (== authorizing in pidgin)
            # (a wokkel API)
            self.subscribed(presence)
        # let the presence know that we are available (this does not affect 
        # subscription status)
        self.available(presence)
        
    def probeReceived(self, presence):
        PresenceClientProtocol.probeReceived(self, presence)
        self.available()

    def availableReceived(self, entity, show=None, statuses=None, priority=0):
        jid = JID(entity.full())
        userhost = jid.userhost()
        logging.info("Available from {} '{}' priority: '{}'".format(jid, show, priority))
        # entity has come online - update our online set
        if userhost in self.um.users():
            self.um.set_available(jid, show=show, priority=priority)
            # make them available in their groups
            for group in self.um.get_groups(userhost):
                self.um.set_available(jid, group, show=show, priority=priority)
        else:
            # Probably a user entering a room EnDroid is in.
            # If this is the case EnDroid will find out via a userJoinedRoom call
            # on wokkelhandler
            pass

    def unavailableReceived(self, entity, statuses=None):
        jid = JID(entity.full())
        userhost = jid.userhost()
        logging.info("Unavailable from {}".format(str(jid)))
        # entity has gone offline - update our online set
        if userhost in self.um.available_users():
            self.um.set_unavailable(jid)
            # make them unavailable in their groups
            for group in self.um.get_groups(userhost):
                self.um.set_unavailable(jid, group)
        else:
            # Probably a user leaving a room EnDroid is in.
            # If this is the case EnDroid will find out via a userLeftRoom call
            # on wokkelhandler
            pass

