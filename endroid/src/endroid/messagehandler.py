# -----------------------------------------
# Endroid - XMPP Bot
# Copyright 2012, Ensoft Ltd.
# Created by Jonathan Millican
# -----------------------------------------

import logging
from collections import namedtuple

import twisted.internet.reactor as reactor
from twisted.words.protocols.jabber.jid import JID


class Handler(object):
    __slots__ = ("name", "priority", "callback")
    def __init__(self, priority, callback):
        self.name = callback.__name__
        self.priority = priority
        self.callback = callback

    def __str__(self):
        return "{}: {}".format(self.priority, self.name)

class Priority(object):
    NORMAL = 0
    URGENT = -1
    BULK = 1


ResponseCallback = namedtuple('ResponseCallback', ['callback', 
                                                   'call_later_deferred'])


class MessageHandler(object):
    """An abstraction of XMPP's message protocols."""

    PRIORITY_NORMAL = Priority.NORMAL
    PRIORITY_URGENT = Priority.URGENT
    PRIORITY_BULK = Priority.BULK

    FALLBACK_CONTEXT_TIMEOUT = 30
    # for if it's not even specified in the config file


    def __init__(self, wh, um, config=None):
        self.wh = wh
        self.um = um
        # wh translates messages and gives them to us, needs to know who we are
        self.wh.set_message_handler(self)
        self._handlers = {}
        self.response_callbacks = {}

        if config is not None:
            self.context_awareness_timeout = config.get("setup",
                                                        "context_response_timeout",
                                                        default=self.FALLBACK_CONTEXT_TIMEOUT)
        else:
            self.context_awareness_timeout = self.FALLBACK_CONTEXT_TIMEOUT

    def _register_context_callback(self, user, callback=None,
                                   noresponse_callback=None, timeout_time=0):
        """
        Create context-awareness by giving a callback to handle the user's next message.
        Raises self.ValueError if timeout_time is not a positive time or None.
        :param user: JID of the user whose next message we handle differently
        :param callback: callback to handle the message, taking <msg> a Message
        :param noresponse_callback: callback if the message goes unhandled, taking <user>
        :param timeout_time: time in seconds before we forget about this callback.
          0 for the configured default.
        """

        # architecture: self.response_callbacks is a dict with key "j@i.d"
        # and entry [callback_when_response]. If a timeout_time is given
        # then we call noresponse_callback with argument 'j@i.d' after
        # timeout_time seconds, by means of the helper function
        # self.unregister_context_callback. In that case, the entry [callback]
        # has a second element, <later>, suitable for later.cancel().

        if timeout_time <= 0:
            timeout_time = self.context_awareness_timeout

        # _handle_context_timeout checks whether its argument is not None
        # before calling it, so it's safe to get _handle_context_timeout just
        # calling noresponse_callback.

        later = reactor.callLater(timeout_time,
                                  self._handle_context_timeout,
                                  user, noresponse_callback)

        self.response_callbacks[user] = ResponseCallback(callback=callback,
                                                         call_later_deferred=later)

    def _handle_context_timeout(self, user, noresponse_callback):
        """
        Make Endroid forget about context callbacks for the user.
        :param user: JID of the user we're forgetting about
        :param message: chat message to send to the user.
        :param noresponse_callback: callback to call afterwards,
          taking one User argument
        """
        self.response_callbacks.pop(user, None)  # forget the entry

        if noresponse_callback is not None:
            noresponse_callback(user)

    def _handle_context_callback(self, msg):
        """
        Internal function: runs callbacks for the sender of the msg object.

        :param msg: message object with a .sender JID whose callbacks we run
        """
        if msg.sender in self.response_callbacks:
            msg.start_context_processing()
            response = self.response_callbacks.pop(msg.sender)
            if response is not None:
                logging.debug("Calling response callback {} for user {}".format(
                              response, msg.sender))
                try:
                    response.callback(msg)
                except Exception as e:
                    # if we failed to do the callback, pretend it wasn't a
                    # context-aware thing in the first place
                    msg.unhandled()
                    raise e

                if response.call_later_deferred is not None:
                    # do we have an on-timeout-do-this-callback running?
                    # if so, get rid of it
                    response.call_later_deferred.cancel()

            msg.stop_context_processing()

    def _register_callback(self, name, typ, cat, callback,
                           including_self=False, priority=Priority.NORMAL):
        """
        Register a function to be called on receipt of a message of type
        'typ' (muc/chat), category 'cat' (recv, send, unhandled, *_self, *_filter)
        sent from user or room 'name'.

        """
        # self._handlers is a dictionary of form:
        # { type : { category : { room/groupname : [Handler objects]}}}
        typhndlrs = self._handlers.setdefault(typ, {})
        cathndlrs = typhndlrs.setdefault(cat, {})
        handlers = cathndlrs.setdefault(name, [])
        handlers.append(Handler(priority, callback))
        handlers.sort(key=lambda h: h.priority)

        # this callback be called when we get messages sent by ourself
        if including_self:
            self._register_callback(name, typ, cat + "_self", callback,
                                    priority=priority)

    def _get_handlers(self, typ, cat, name):
        dct = self._handlers.get(typ, {}).get(cat, {})
        if typ == 'chat':  # we need to lookup name's groups
            # we may have either a full jid or just a userhost,
            # groups are referenced by userhost
            name = self.um.get_userhost(name)
            handlers = []
            for name in self.um.get_groups(name):
                handlers.extend(dct.get(name, []))
            handlers.sort(key=lambda h: h.priority)
            return handlers
        else:  # we are in a room so only one set of handlers to read
            return dct.get(name, [])

    def _get_filters(self, typ, cat, name):
        return self._get_handlers(typ, cat + "_filter", name)

    def _do_callback(self, cat, msg, failback=lambda m: None):
        if msg.place == "muc":
            # get the handlers active in the room - note that these are already
            # sorted (sorting is done in the register_callback method)
            handlers = self._get_handlers(msg.place, cat, msg.recipient)
            filters = self._get_filters(msg.place, cat, msg.recipient)
        else:
            # combine the handlers from each group the user is registered with
            # note that if the same plugin is registered for more than one of
            # the user's groups, the plugin's instance in each group will be
            # called
            handlers = self._get_handlers(msg.place, cat, msg.sender)
            filters = self._get_filters(msg.place, cat, msg.sender)

        log_list = []
        if handlers and all(f.callback(msg) for f in filters):
            msg.set_unhandled_cb(failback)

            for i in handlers:
                msg.inc_handlers()

            log_list.append("Did {} {} handlers (priority: cb):".format(len(handlers), cat))
            for handler in handlers:
                try:
                    handler.callback(msg)
                    log_list.append(str(handler))
                except Exception as e:
                    log_list.append("Exception in {}:\n{}".format(handler.name, e))
                    msg.dec_handlers()
                    raise
        else:
            failback(msg)
        if log_list:
            logging.info("Finished plugin callback: {}".format(
                         "\n\t".join(log_list)))
        else:
            logging.info("Finished plugin callback - no plugins called.")

    def _unhandled(self, msg):
        self._do_callback("unhandled", msg)

    def _unhandled_self(self, msg):
        self._do_callback("unhandled_self", msg)

    # Do normal (recv) callbacks on msg. If no callbacks handle the message
    # then call unhandled callbacks (msg's failback is set self._unhandled_...
    # by the last argument to _do_callback).
    def receive_muc(self, msg):
        self._do_callback("recv", msg, self._unhandled)

    def receive_self_muc(self, msg):
        self._do_callback("recv_self", msg, self._unhandled_self)

    def receive_chat(self, msg):
        self._handle_context_callback(msg)  # attempt to use context callbacks

        # msg._context_dealt_with is:
        # False if context callbacks existed but didn't handle the msg,
        #       or didn't exist,
        # True if context callbacks handled the msg.
        # msg is still a context-reply (msg.context_response is True) if
        # msg._context_dealt_with is False or True.
        if not msg._context_dealt_with:
            self._do_callback("recv", msg, self._unhandled)

    def receive_self_chat(self, msg):
        self._do_callback("recv_self", msg, self._unhandled_self)

    def for_plugin(self, pluginmanager, plugin):
        return PluginMessageHandler(self, pluginmanager, plugin)

    # API for global plugins

    def register(self, name, callback, priority=Priority.NORMAL, muc_only=False,
                 chat_only=False, include_self=False, unhandled=False,
                 send_filter=False, recv_filter=False):
        if sum(1 for i in (unhandled, send_filter, recv_filter) if i) > 1:
            raise TypeError("Only one of unhandled, send_filter or recv_filter "
                            "may be specified")
        if chat_only and muc_only:
            raise TypeError("Only one of chat_only or muc_only may be "
                            "specified")

        if unhandled:
            cat = "unhandled"
        elif send_filter:
            cat = "send_filter"
        elif recv_filter:
            cat = "recv_filter"
        else:
            cat = "recv"

        if not muc_only:
            self._register_callback(name, "chat", cat, callback,
                                    include_self, priority)
        if not chat_only:
            self._register_callback(name, "muc", cat, callback,
                                    include_self, priority)

    def send_muc(self, room, body, source=None, priority=Priority.NORMAL):
        """
        Send muc message to room.

        The message will be run through any registered filters before it is
        sent.

        """
        # Verify this is a room EnDroid knows about
        msg = Message('muc', source, body, self, recipient=room)
        # when sending messages we check the filters registered with the
        # _recipient_. Cf. when we receive messages we check filters registered
        # with the _sender_.
        filters = self._get_filters('muc', 'send', msg.recipient)

        if all(f.callback(msg) for f in filters):
            logging.info("Sending message to {}".format(room))
            self.wh.groupChat(JID(room), body)
        else:
            # Need to rely on filters providing more detailed information
            # on why a message was filtered
            logging.debug("Filtered out message to {}".format(room))

    def send_chat(self, user, body, source=None, priority=Priority.NORMAL,
                  response_cb=None, no_response_cb=None, timeout=None):
        """
        Send chat message to person with address user.

        The message will be run through any registered filters before it is
        sent.

        response_cb is an optional callback to be called to handle the next
        message received from the user. (Note that only the latest such callback
        will be executed: if you call send_chat twice in quick succession,
        only the final send_chat's callback will be called.)
        This callback must take one argument (a Message object).
        no_response_cb is an optional callback to be called if the user does
        not give a response in <timeout> seconds. It takes only a <sender> JID
        string. <timeout> defaults to config option context_response_timeout.
        Either response_cb or no_response_cb can be provided without the other.
        If response_cb is not specified but no_response_cb is, Endroid
        effectively waits for the timeout to elapse; if the user didn't reply
        in that time, it calls no_response_cb.
        """

        # Verify user is known to EnDroid
        msg = Message('chat', source, body, self, recipient=user)
        filters = self._get_filters('chat', 'send', msg.recipient)

        if response_cb or no_response_cb:
            # set up context callbacks before the message gets sent, so that the
            # filter callbacks can't mess up our timeout-timing *too* much
            self._register_context_callback(user, response_cb, no_response_cb,
                                            timeout)

        if all(f.callback(msg) for f in filters):
            logging.info("Sending message to {}".format(user))
            self.wh.chat(JID(user), body)
        else:
            # Need to rely on filters providing more detailed information
            # on why a message was filtered
            logging.debug("Filtered out message to {0}".format(user))


class PluginMessageHandler(object):
    """
    One of these exists per plugin, providing the API to handle messsages.
    """
    def __init__(self, messagehandler, pluginmanager, plugin):
        self._messagehandler = messagehandler
        self._pluginmanager = pluginmanager
        self._plugin = plugin

    def send_muc(self, body, source=None, priority=Priority.NORMAL):
        if self._pluginmanager.place != "room":
            raise ValueError("Not in a room")
        self._messagehandler.send_muc(self._pluginmanager.name, body,
                                      source=source, priority=priority)

    def send_chat(self, user, body, source=None, priority=Priority.NORMAL):
        if self._pluginmanager.place != "group":
            raise ValueError("Not in a group")
        if user not in self._pluginmanager.usermanagement.users(
                                                    self._pluginmanager.name):
            raise ValueError("Target user is not in this group")
        # Verify user is in the group we are in
        self._messagehandler.send_chat(user, body,
                                       source=source, priority=priority)

    def register(self, callback, priority=Priority.NORMAL, muc_only=False,
                 chat_only=False, include_self=False, unhandled=False,
                 send_filter=False, recv_filter=False):
        if self._pluginmanager.place == "room" and not chat_only:
            muc_only = True
        if self._pluginmanager.place == "group" and not muc_only:
            chat_only = True
        self._messagehandler.register(self._pluginmanager.name, callback,
                                      priority=priority, muc_only=muc_only,
                                      chat_only=chat_only,
                                      include_self=include_self,
                                      unhandled=unhandled,
                                      send_filter=send_filter,
                                      recv_filter=recv_filter)


class Message(object):

    # Private variables:
    # - _context_response - whether or not this message is in response to a
    #    context-aware callback.
    # - _context_dealt_with - whether or not this message has been handled by a
    #   context callback. None if the message has never undergone handling by
    #   context callbacks; False if no context callback handled it despite being
    #   called; True if a context callback handled it."""

    def __init__(self, place, sender, body, messagehandler, recipient, handlers=0,
                 priority=Priority.NORMAL, context_response=False):
        self.place = place

        # sender_full is a string representing the full jid (including resource)
        # of the message's sender. Used in reply methods so that if a user is
        # logged in on several resources, the reply will be sent to the right
        # one
        self.sender_full = sender
        # a string representing the userhost of the message's sender. Used to
        # lookup resource-independant user properties eg their registered rooms
        self.sender = messagehandler.um.get_userhost(sender)
        self.body = body
        self.recipient = recipient

        # a count of plugins which will try to process this message
        self.__handlers = handlers
        self._messagehandler = messagehandler
        self.priority = priority

        # are we going to have to contextually respond?
        self._context_response = context_response
        self._context_dealt_with = False

    def send(self):
        if self.place == "chat":
            self._messagehandler.send_chat(self.recipient, self.body, self.sender)
        elif self.place == "muc":
            self._messagehandler.send_muc(self.recipient, self.body, self.sender)

    def reply(self, body):
        if self.place == "chat":
            self._messagehandler.send_chat(self.sender_full, body, self.recipient)
        elif self.place == "muc":
            # we send to the room (the recipient), not the message's sender
            self._messagehandler.send_muc(self.recipient, body, self.recipient)

    def reply_to_sender(self, body):
        self._messagehandler.send_chat(self.sender_full, body, self.recipient)

    def inc_handlers(self):
        self.__handlers += 1

    def dec_handlers(self):
        self.__handlers -= 1
        self.do_unhandled()

    def start_context_processing(self):
        self._context_response = True
        self._context_dealt_with = True

    def stop_context_processing(self):
        self._context_response = False

    def unhandled(self, *args):
        """
        Notify the message that the caller hasn't handled it. This should only
        be called by plugins that have registered as a handler (and thus have
        incremented the handler count for this message).

        This method takes arbitrary arguments so it can be used as deferred
        callback or errback.

        """
        if self._context_response:
            # we asked a context-aware plugin to deal with the message, but it
            # did not
            self._context_dealt_with = False
        else:
            self.dec_handlers()

    def do_unhandled(self):
        if self.__handlers == 0 and hasattr(self, '_unhandled_cb'):
            self._unhandled_cb(self)

    def set_unhandled_cb(self, cb):
        self._unhandled_cb = cb
