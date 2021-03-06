# -----------------------------------------
# Endroid - Webex Bot
# Copyright 2012, Ensoft Ltd.
# Created by Jonathan Millican
# -----------------------------------------

import re, logging
import webexteamssdk

import twisted.internet.reactor as reactor


from endroid.messagehandler import Message
from endroid.cron import Cron

MAX_MESSAGE_LEN = 7439

# Provides messaging and room handling
class WebexHandler(object): 
    def __init__(self):
        self.messagehandler = None
        self.usermanagement = None
        self.client = None

    @property
    def my_emails(self):
        return self.client.my_emails

    def set_message_handler(self, mh): 
        self.messagehandler = mh
        # Can only join groups once the message handler is initialized. 
        self.usermanagement.join_all_groups()

    def set_user_management(self, um): 
        self.usermanagement = um

    def setHandlerParent(self, client):
        self.client = client

    def getMemberList(self, room):
        logging.info("Getting member list for room: %s", room)
        if self.client is not None: 
            users = self.client.webex_api.memberships.list(roomId=room)
            members = list([user.personEmail for user in users])
        else:
            members = list()

        return members

    def getOwnerList(self, room):
        logging.info("Getting owner list for room")
        if self.client is not None: 
            users = self.client.webex_api.memberships.list(roomId=room)
            owners = list([user.personEmail 
                                        for user in users if user.isModerator])
        else:
            owners = list()

        return owners

    def invite(self, user, room, reason):
        logging.info("Adding person %s to room %s, reason: %s", 
                     user, room, reason)
        if self.client is not None and self._is_moderator(room):
            self.client.webex_api.memberships.create(roomId=room, 
                                                     personEmail=user)

    def kick(self, user, room, reason): 
        logging.info("Kicking person %s from room %s, reason: %s",
                      user, room, reason)

        if self.client is not None and \
           (user in self.my_emails or self._is_moderator(room)):
            memberships = self.client.webex_api.memberships.list(
                                                              roomId=room,
                                                              personEmail=user)
            for membership in memberships:
                try:
                    self.client.webex_api.memberships.delete(
                                                    membershipId=membership.id)
                except Exception:
                    logging.exception("Got exception deleting user from room")

    def chat(self, user, text):
        logging.info("Sending chat to user: %s", user)

        if self.client is not None:
            self._send_message(text=text, toPersonEmail=user)

    def groupChat(self, room, text):
        logging.info("Sending chat to room: %s", room)
        if self.client is not None:
            self._send_message(text=text, roomId=room)

    def _send_message(self, text, **kwargs):
        chunk = text[0:MAX_MESSAGE_LEN]
        self.client.webex_api.messages.create(text=chunk, **kwargs)
        if len(text) > MAX_MESSAGE_LEN:
            reactor.callLater(0, self._send_message, text[MAX_MESSAGE_LEN:],
                              **kwargs)

    def _is_moderator(self, room):
        if self.client is None:
            return False
        elif self.client.webex_api.rooms.get(room).isLocked and not \
             self.my_emails[0] in self.getOwnerList(room):
            logging.info("Endroid is not a moderator for room %s", room)
            logging.info(self.getMemberList(room))
            return False
        else:
            return True

    def _remove_tag(self, message):
        prefix = '>'
        suffix = '</spark-mention>'
        regex = re.compile(prefix + '[A-Za-z0-9\-_ @]+' + suffix)
        start_index, end_index = regex.search(message.html).span()
        tag = message.html[start_index + len(prefix):end_index - len(suffix)]
        logging.info("Tag found: %s", str(tag))

        if message.text.startswith(tag):
            text = re.sub('^' + tag, '', message.text) 
            text = re.sub('^ ', '', text)
        elif message.text.endswith(tag):
            text = re.sub(tag + '$', '', message.text)
        else:
            text = None

        return text

    def connected(self):
        if self.client is not None:
            rooms = self.client.webex_api.rooms.list()
            # rejoin and sanitize multi-person rooms
            for room in rooms:
                if room.type == 'group':
                    self.usermanagement.self_joined_room(room.id, remove=True)

    # called by Webex client
    # we use it to pass the message onto our messagehandler
    def onMessage(self, message): 
        self_message = message.personEmail in self.client.my_emails

        if self.client is not None:
            if message.roomType == 'group':
                if self_message:
                    m = Message('muc', message.personEmail, message.text, 
                                self.messagehandler, message.roomId)
                    self.messagehandler.receive_self_muc(m)
                else:
                    logging.info("Group message received from %s", 
                                message.personEmail)
                    
                    text = self._remove_tag(message)
                    if text is not None:
                        logging.info("New message: %s", text)
                        m = Message('muc', message.personEmail, text, 
                                    self.messagehandler, message.roomId)
                        self.messagehandler.receive_muc(m)
                    else: 
                        self.groupChat(message.roomId, 
                                       'Endroid expects its tag to be at the '
                                       'start or end of the message')
            else:
                # Insert endroid's email for the recipient - in 
                # the case of a self direct message the recipient information
                # is not included in the message - could be retrieved by a room
                # info retrieval. @@@ needs to be extended if any plugins use 
                # the recipient field of endroid-sent messages
                m = Message('chat', message.personEmail, message.text,
                            self.messagehandler, self.my_emails[0])
                if self_message:
                    self.messagehandler.receive_self_chat(m)
                else:
                    logging.info("Direct message received from %s",
                                 message.personEmail)
                    self.messagehandler.receive_chat(m)

    # called by Webex client
    # we use it to pass the membership notification onto our usermanagement
    def onMembership(self, room, user):
        logging.info("User %s added to room %s",
                     user,
                     self.client.webex_api.rooms.get(room).title)

        if user in self.client.my_emails:
            self.usermanagement.self_joined_room(room, remove=True)
        else:
            self.usermanagement.user_joined_room(room, user, remove=True)