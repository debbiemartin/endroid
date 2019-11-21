# -----------------------------------------------------------------------------
# Endroid - Webex Bot - Rate Limiting plugin
# Copyright 2012, Ensoft Ltd.
# Created by Martin Morrison
# -----------------------------------------------------------------------------


import time
import logging
from collections import defaultdict, deque
import trace

from endroid.pluginmanager import Plugin
from endroid.messagehandler import Priority
from endroid.cron import task

# Cron constants
CRON_SENDAGAIN = "RateLimit_SendAgain"


class Bucket(object):
    """
    Implementation of a Token Bucket.
    """
    __slots__ = ('capacity', 'tokens', 'fillrate', 'timestamp')

    def __init__(self, capacity, fillrate):
        """
        Initialise the bucket with the given capacity (or burst rate), and
        fillrate.

        capacity is the max number of "tokens" to hold, and thus the maximum
        burst rate that can be triggered.
        fillrate is a value in tokens-per-second, at which the bucket fills up.
        """
        self.capacity = capacity
        self.tokens = capacity
        self.fillrate = fillrate
        self.timestamp = time.time()

    def use_token(self, useup=1, now=None):
        """
        Attempt to use some tokens from the bucket.

        useup is the number of tokens to try to use (defaults to 1).  now is a
        float representing the time (returned by time.time()) at which to take
        the tokens. If not specified or None, the current time is used.

        This method will update the number of tokens in the Bucket based on the
        elapsed time since the last use_token call, then attempt to remove the
        specified number of tokens. The return value is whether there were
        sufficient tokens in the Bucket.
        """
        if now is None:
            now = time.time()
        self.tokens = min(self.capacity,
                          self.tokens + ((now - self.timestamp) * self.fillrate))
        self.timestamp = now
        if self.tokens >= useup:
            self.tokens -= useup
            return True
        else:
            return False

    def __repr__(self):
        return "<Bucket({0}/{1}, {2}, {3})>".format(self.tokens, self.capacity,
                                                    self.fillrate, self.timestamp)


class SendClass(object):
    """
    Represents an independently rate limited sender class. Usually, there is one
    instance of this class for each destination JID.
    """
    __slots__ = ('queue', 'maxlen', 'bucket')

    def __init__(self, bucket, maxlen=None):
        """
        Initialise the sender class with the given TokenBucket, and the specified
        maxiumum queue length.
        """
        # Don't use maxlen in the deque - it drops from the wrong end!
        self.queue = deque()
        self.maxlen = maxlen
        self.bucket = bucket

    def append(self, msg):
        """
        Append the given message to the queue, assuming there is room
        (i.e. there aren't already maxlen messages in it). This should only be
        called if the caller will later call pop() to remove messages, and
        generally only via the accept() method.
        """
        if self.maxlen is not None or len(self.queue) < self.maxlen:
            self.queue.append(msg)

    def pop(self):
        """
        Pop a message of the queue, after checking there are enough tokens in
        the TokenBucket to allow message sending, otherwise return None.

        Note that calls to this function consume tokens in the bucket.
        """
        if len(self.queue) > 0 and self._accept():
            return self.queue.popleft()

    def _accept(self, now=None):
        """
        Check whether this sender class will accept sending a message, by
        checking the TokenBucket. If a msg is specified, and there are not
        sufficient tokens, then the messages is appended to the queue for later
        processing. Returns a bool indicating whether the message can be
        sent immediately.

        now may be specified to be passed on to the TokenBucket.
        """
        if now is None:
            now = time.time()

        return self.bucket.use_token(now=now)

    def accept_msg(self, msg):
        accept = self._accept()
        if accept:
            # We can send a message, now lets find out which message
            if len(self.queue) > 0:
                # There are already msgs on the queue. Queue this message
                # and return the first message from the queue to preserve
                # ordering
                self.append(msg)
                msg_to_send = self.queue.popleft()
            else:
                msg_to_send = msg
        else:
            # Can't send a message so queue it
            self.append(msg)
            msg_to_send = None

        return msg_to_send


class RateLimit(Plugin):
    """
    Provides a Token Bucket-based rate limiter for EnDroid.
    """
    name = "ratelimit"
    hidden = True
    help = "Implements a Token Bucket rate limiter, per recipient user"
    preferences = ("endroid.plugins.blacklist",)

    def endroid_init(self):
        """
        Initialise the plugin. Registers required Crons, and extracts
        configuration.
        """
        self.maxburst = float(self.vars.get('maxburst', 5.0))
        self.fillrate = float(self.vars.get('fillrate', 1.0))
        self.maxqueuelen = int(self.vars.get('maxqueuelen', 20))

        self.abuseallowance = float(self.vars.get('abuseallowance', 30.0))
        self.abuserecovery = float(self.vars.get('abuserecovery', 0.5))
        self.abusecooloff = int(self.vars.get('abusecooloff', 3600))
        self.blacklist = self.get("endroid.plugins.blacklist")

        self.messages.register(self.ratelimit, priority=10, send_filter=True)
        self.messages.register(self.checkabuse, priority=10, recv_filter=True)

        # Make all the state attributes class attributes
        # This means that users are limited globally accross all usergroups and
        # rooms rather than on a per room/user basis.
        # It also means that it doesn't matter which instance is called back
        # by the cron module
        RateLimit.limiters = defaultdict(
            lambda: SendClass(Bucket(self.maxburst, self.fillrate),
                              self.maxqueuelen))
        RateLimit.abusers = defaultdict(
            lambda: Bucket(self.abuseallowance, self.abuserecovery))

        RateLimit.waitingusers = set()

    def ratelimit(self, msg):
        """
        Send message filter. Rate limits based on the message recipient, using
        a TokenBucket, queuing and overflowing message (up to a limit).

        It then uses the Cron module to schedule a retry for any queued
        messages. TODO: store queued messages in the DB so they survive a
        process restart?

        Priority.URGENT messages are not rate limited.
        """
        sc = self.limiters[msg.recipient]

        # Don't ratelimit things we're sending ourselves, or URGENT messages
        if (msg.sender == self.name or
            msg.priority == Priority.URGENT):
            accept = True
        else:
            # Otherwise always return false because either: we'll send the msg
            # ourselves or we're queuing the message for later sending
            accept = False
            msg_to_send = sc.accept_msg(msg)
            if msg_to_send:
                self.send(msg_to_send)
            else:
                logging.info("Ratelimiting msgs to {}".format(msg.recipient))

        self.set_timeout(msg.recipient)

        return accept

    def checkabuse(self, msg):
        """
        Check for abuse of the EnDroid. Users who exceed the limit imposed here
        are placed on the blacklist (if that plugin is available) for an hour.
        """
        if not self.abusers[msg.sender].use_token():
            if self.blacklist is not None:
                logging.info("Blacklisting abusive user {}".format(msg.sender))
                self.blacklist.blacklist(msg.sender, 
                                         self.abusecooloff)
            else:
                logging.info("Detected abusive user ({}) but unable to "
                             "blacklist. Dropping message instead".format(
                             msg.sender))
                return False

        return True

    @task(CRON_SENDAGAIN)
    def sendagain(self, user):
        """
        Cron callback handler. Attempts to send as many messages as it can from
        the queue for the given user.
        """
        sc = self.limiters[user]
        self.waitingusers.discard(user)
        logging.info("Draining msg queue for {}, current len {}".format(
                     user, len(sc.queue)))
        while True:
            msg = sc.pop()
            if msg:
                self.send(msg)
            else:
                break
        self.set_timeout(user)

    def send(self, msg):
        # Update the message to indicate it's sent from us (so we don't
        # rate limit it again!
        msg.sender = self.name
        msg.send()

    def set_timeout(self, user):
        """
        Starts a cron timer if there are any messages queued for the given
        user.

        The timer is set for 1 / fillrate i.e. the time it takes for a single
        token to be added to the bucket.
        """

        sc = self.limiters[user]
        if len(sc.queue) > 0 and user not in self.waitingusers:
            self.waitingusers.add(user)
            timedelta = 1.0 / self.fillrate
            self.sendagain.setTimeout(timedelta, user)

    def create_bucket(self, capacity, fillrate):
        """
        Returns a Bucket, which implements a token bucket.
        :param capacity: maximum number of tokens in bucket
        :param fillrate: number of tokens per second refilled
        :return: Bucket object
        """
        return Bucket(capacity, fillrate)
