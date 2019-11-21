# -----------------------------------------------------------------------------
# Endroid - XMPP Bot - PeriodicPinger plugin
# Copyright 2014, Ensoft Ltd.
# Created by Patrick Stevens
# -----------------------------------------------------------------------------

"""
Periodically XMPP-pings each XMPP server Endroid is communicating with.
It is hoped that this will alleviate problems related to servers dropping our
connections.
"""


import logging
import functools
import itertools

import twisted.internet.task
from twisted.words.protocols.jabber.error import StanzaError

from endroid.pluginmanager import Plugin


class PeriodicPinger(Plugin):
    """
    Wrapper to a Cron job which periodically pings a user on each server.
    This plugin has no XMPP-interface by which the user may interact with it.
    """

    # Class variable to synchronise plugin so that even if we 
    # instantiate more than once, we still only have one Cron job
    task = None

    # Add the hidden attribute so that this plugin doesn't appear in help
    hidden = True

    def endroid_init(self):
        cls = type(self)
        if cls.task is None:
            # Get the set of servers that endroid could communicate to. This
            # is static so we do this once at init time.
            self.servers = self._get_servers()
            self.log = logging.getLogger(__name__)
            self.interval = self.vars.get('interval', 10)
            cls.task = twisted.internet.task.LoopingCall(self._ping_servers)
            cls.task.start(self.interval)
            self.log.info("Periodic pinger set up for every {} seconds"
                          .format(self.interval))

    def _get_servers(self):
        """
        Get the set of servers that endroid could communicate to (using the
        list of registered users and rooms)
        """
        servers = set()
        for user in self.usermanagement.users():
            servers.add(self.usermanagement.get_host(user))
        for room in self.usermanagement.rooms():
            servers.add(self.usermanagement.get_host(room))

        return servers

    def _ping_servers(self):
        """Pings each server Endroid knows about."""
        self.log.debug('PeriodicPinger: Pinging {}...'.format(self.servers))

        for server in self.servers:
            def _fail(fail, server):
                if fail.check(StanzaError):
                    # Some servers that don't support c2s pings return 'bad
                    # request' rather than 'not supported'. This still serves
                    # the keep-the-connection alive purpose, so don't log as an
                    # error.
                    logger = self.log.debug
                else:
                    logger = self.log.error
                logger("Failed to ping {}: {}".format(server, fail.value))
            def _success(response):
                pass
            try:
                d = self.usermanagement.ping(server)
            except Exception:
                self.log.exception("Failed to send ping to {}:".format(server))
            else:
                d.addCallbacks(_success,
                               functools.partial(_fail, server=server))


