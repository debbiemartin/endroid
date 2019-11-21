# -----------------------------------------
# Endroid - XMPP Bot
# Copyright 2012, Ensoft Ltd.
# Created by Jonathan Millican
# -----------------------------------------

import re, logging

from twisted.internet.task import LoopingCall
from wokkel.muc import MUCClient
from wokkel.xmppim import MessageProtocol

from endroid.messagehandler import Message
from endroid.usermanagement import JID
from endroid.cron import Cron

# See Section 2.2 of XML spec
_naughty_xml = re.compile(
    u'[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff\ufffe\uffff]')

def sanitize_xml(stanza):
    """
    Turn any body output that doesn't conform to section 2.2 of the XML
    standard into a '__?__' string, rather than provoke our XMPP
    peer into kicking us out with an xml-not-well-formed error.
    """
    sanitized = _naughty_xml.sub('__?__', stanza)
    if sanitized != stanza:
        logging.error("Correcting XML '{}' to '{}'".format(stanza, sanitized))
    return sanitized


# MUCClient provides muc messaging + room handling
# MessageProtocol provides suc messaging
class WokkelHandler(MUCClient, MessageProtocol):
    def __init__(self):
        MUCClient.__init__(self)
        MessageProtocol.__init__(self)

        self.messagehandler = None
        self.usermanagement = None
        self.deferred = None
        self.keepalive = LoopingCall(self.send, " ")

        self.jid = None

    def set_connected_handler(self, d):
        self.deferred = d

    def set_message_handler(self, mh):
        self.messagehandler = mh

    def set_presence_handler(self, um):
        self.usermanagement = um
        self.jid = self.usermanagement.jid_obj

    # called when the xml stream has been initialized
    # use to do further initialization work
    def connectionInitialized(self):
        # adds MUCClientProtocol._onGroupChat to the xmlstream observers
        # notified by GROUPCHAT = "/message[@type="groupchat"]"
        MUCClient.connectionInitialized(self)
        # adds MessageProtocol._onMessage to the xmlstream observers
        # notified by "/message" i.e. anything
        MessageProtocol.connectionInitialized(self)
        self.keepalive.start(300)
        logging.info("Connected to XMPP")

        self.usermanagement.join_all_rooms()
        self.usermanagement.join_all_groups()


        # we start the cron here, then cancel it in connectionLost
        Cron.get().do_crons()

        if self.deferred:
            d, self.deferred = self.deferred, None
            d.callback(self)

    def connectionLost(self, reason):
        self.keepalive.stop()
        logging.warning("Lost connection to XMPP")
        Cron.get().cancel()


    # called by _onMessage whenever a stanza of type "/message" is received
    # we use it to pass the message onto our messagehandler
    def onMessage(self, message):
        MessageProtocol.onMessage(self, message)
        if message.hasAttribute('type'):
            if message.attributes['type'] == u'chat':
                body = None
                sender = JID(message.attributes['from'])
                recipient = JID(message.attributes['to'])
                for i in message.children:
                    # Note: in theory multiple bodies are allowed; in practice,
                    # this isn't seen, so just get the first one.
                    if getattr(i, "name", "") == 'body':
                        body = i.children[0]
                        break

                if not (body is None or sender is None or recipient is None):
                    # Use the full JIDs here so that if a user is logged on
                    # from multiple resources, we know which one sent the
                    # message
                    m = Message("chat", sender.full(), body, 
                                self.messagehandler, recipient.full())
                    # Only check the userhost for self because we might not
                    # know endroid's resource
                    if sender.userhost() == self.jid.userhost():
                        logging.info('SUC Message received from self')
                        self.messagehandler.receive_self_chat(m)
                    else:
                        logging.info('SUC Message received from {}'.format(
                                     sender.full()))
                        self.messagehandler.receive_chat(m)
        elif len(message.children) > 0:
            # Try and identify this message type
            msg_child = message.children[0]
            if (msg_child.name == 'x' and len(msg_child.children) > 0 and
                msg_child.children[0].name == 'invite'):
                # Looks like an invite
                ujid = msg_child.children[0].attributes['from']
                rjid = message.attributes['from']
                logging.info("Invitation received to " + rjid + " from " + ujid)
                # Try to join the room
                self.usermanagement.handle_room_invite(rjid)
            elif (msg_child.name == 'body' and len(msg_child.children) > 0 and
                  'granted' in msg_child.children[0]): 
                logging.info("Received affiliation change message: {}".format(
                             msg_child.children[0]))
            else:
                logging.error("Received unknown message with child: "
                              "{}".format(message.toXml()))
        else:
            logging.error("Received unknown message: {}".format(message.toXml()))

    # MUCClient methods to be overridden

    def userJoinedRoom(self, room, user):
        user_obj = JID(user.entity.full(), nick=user.nick)
        if user_obj.userhost() == self.jid.userhost():
            # This is EnDroid joining a room nothing to do
            pass
        else:
            self.usermanagement.set_available(user_obj, 
                                              room.roomJID.userhost())

    def userLeftRoom(self, room, user):
        user_obj = JID(user.entity.full(), nick=user.nick)
        self.usermanagement.set_unavailable(user_obj,
                                            room.roomJID.userhost())

    def userUpdatedStatus(self, room, user, show, status):
        pass

    # new room subject received
    def receivedSubject(self, room, user, subject):
        pass

    def receivedGroupChat(self, room, user, message):
        MUCClient.receivedGroupChat(self, room, user, message)
        if user is None:
            logging.info('Received group chat with none user - '
                         'perhaps from a room? : {}'.format(message.body))
            return

        sender_jid = user.entity.full()
        room_userhost = room.roomJID.userhost()

        m = Message("muc", sender_jid, message.body, 
                    self.messagehandler, room_userhost)

        if user.entity.userhost() == self.jid.userhost():
            logging.info('MUC Message received in {} from self'.format(room_userhost))
            self.messagehandler.receive_self_muc(m)
        else:
            logging.info('MUC Message received in {} from: {} ({})'.format(
                         room_userhost, sender_jid, user.nick))
            self.messagehandler.receive_muc(m)

    def receivedHistory(self, room, user, message):
        pass

    def chat(self, jid, body):
        return super(WokkelHandler, self).chat(jid, sanitize_xml(body))

    def groupChat(self, jid, body):
        return super(WokkelHandler, self).groupChat(jid, sanitize_xml(body))        
