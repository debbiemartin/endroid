# -----------------------------------------
# Endroid - XMPP Bot
# Copyright 2012, Ensoft Ltd.
# Created by Jonathan Millican
# -----------------------------------------

import os
import sys
import getpass
import logging
import argparse

from twisted.application import service
from twisted.internet import reactor
from twisted.internet.defer import Deferred, DeferredList, inlineCallbacks
from twisted.words.protocols.jabber.jid import JID
from twisted.python import log  # used for xml logging

import wokkel.ping
import wokkel.client

# endroid base layer
from endroid.rosterhandler import RosterHandler
from endroid.wokkelhandler import WokkelHandler
# top layer
from endroid.usermanagement import UserManagement
from endroid.messagehandler import MessageHandler
# utilities
from endroid.confparser import Parser
from endroid.database import Database
import endroid.manhole


__version__ = "1.4.8"

LOGGING_FORMAT = '%(asctime)-8s %(name)-20s %(levelname)-8s %(message)s'
LOGGING_DATE_FORMAT = '%Y-%m-%d %H:%M:%S'
# LOGGING_FORMAT = '%(levelname)-5s: %(message)s'


class Endroid(object):
    def __init__(self, conffile, args):
        self.application = service.Application("EnDroid")

        self.conf = Parser(conffile)

        if args.logfile:
            # CLI should take precendece over config
            logfile = args.logfile
        else:
            logfile = self.conf.get("setup", "logfile",
                                    default="")

        if args.logtwisted or args.logtraffic:
            # Twisted logging is needed for traffic logging
            observer = log.PythonLoggingObserver()
            observer.start()

        if logfile:
            logfile = os.path.expanduser(logfile)
            logging.basicConfig(filename=logfile, level=args.level,
                                format=LOGGING_FORMAT,
                                datefmt=LOGGING_DATE_FORMAT)
            console = logging.StreamHandler()
            console.setLevel(args.level)
            console.setFormatter(logging.Formatter(LOGGING_FORMAT, "%H:%M:%S"))
            logging.getLogger().addHandler(console)
            logging.info("Logging to STDOUT and {}".format(logfile))
        else:
            logging.basicConfig(level=args.level, format=LOGGING_FORMAT,
                                datefmt=LOGGING_DATE_FORMAT)
            logging.info("Logging to STDOUT")

        self.jid = self.conf.get("setup", "jid")
        logging.info("Found JID: " + self.jid)

        self.secret = self.conf.get("setup", "password")
        logging.info("Found Secret: **********")

        rooms = self.conf.get("setup", "rooms", default=[])
        for room in rooms:
            logging.info("Found Room to Join: " + room)

        groups = self.conf.get("setup", "groups", default=['all'])
        for group in groups:
            logging.info("Found Group: " + group)

        try:
            dbfile = self.conf.get("setup", "dbfile")
        except KeyError:
            # Try the old location in 'database' section, also use a default
            dbfile = self.conf.get("database", "dbfile", 
                                   default="~/.endroid/endroid.db")
        logging.info("Using " + dbfile + " as database file")
        Database.setFile(dbfile)

        self.client = wokkel.client.XMPPClient(JID(self.jid), self.secret)
        logging.info("Setting traffic logging to " + str(args.logtraffic))
        self.client.logTraffic = args.logtraffic

        self.client.setServiceParent(self.application)

        self.rosterhandler = RosterHandler()
        self.rosterhandler.setHandlerParent(self.client)

        self.wokkelhandler = WokkelHandler()
        self.wokkelhandler.setHandlerParent(self.client)

        # Some servers require that we respond to pings so add a ping handler
        self.ping_handler = wokkel.ping.PingHandler()
        self.ping_handler.setHandlerParent(self.client)

        self.ping_sender = wokkel.ping.PingClientProtocol()
        self.ping_sender.setHandlerParent(self.client)

        self.usermanagement = UserManagement(self.wokkelhandler,
                                             self.rosterhandler,
                                             self.conf,
                                             self.ping_sender)
        self.messagehandler = MessageHandler(self.wokkelhandler,
                                             self.usermanagement,
                                             config=self.conf)

        # Fire off our startup flow (once the reactor is running)
        reactor.callWhenRunning(self.startup_flow)

    @inlineCallbacks
    def startup_flow(self):
        # Start the client!
        self.client.startService()

        # wait for the wokkelhandler and rosterhandler to connect
        whd = Deferred()
        rhd = Deferred()
        self.wokkelhandler.set_connected_handler(whd)
        self.rosterhandler.set_connected_handler(rhd)
        yield DeferredList([whd, rhd])

    def run(self):
        reactor.run()


def manhole_setup(argument, config, manhole_dict):
    """
    Perform all manhole specific argument processing.

    This involves extracting user, host and port from the argument
    (if they have been specified). Reading any unspecified arguments
    from config and resorting to defaults if necessary (as below).
    There is no default password, instead the user is prompted to 
    enter one.

    Defaults:
        user - endroid
        password - No default password
        host - 127.0.0.1
        port - 42000

    """

    if not argument:
        # User doesn't want to start a manhole so nothing to do
        return

    if isinstance(argument, basestring):
        # Extract the 3 parts (if present)
        to_decode, _, port = argument.partition(':') 
        user, _, host = to_decode.partition('@') 
    else:
        user = None
        host = None
        port = None

    if not user:
        user = config.get("setup", "manhole_user", default="endroid")
    if not host:
        host = config.get("setup", "manhole_host", default="127.0.0.1")
    if not port:
        port = config.get("setup", "manhole_port", default="42000")

    # Try getting password from config file otherwise prompt for it
    try:
        password = config.get("setup", "manhole_password")
    except KeyError:
        password = getpass.getpass("Enter a manhole password for EnDroid: ")

    endroid.manhole.start_manhole(manhole_dict, user, password, host, port)


def main(args):
    parser = argparse.ArgumentParser(
        prog="endroid", epilog="I'm a robot. I'm not a refrigerator.",
        description="EnDroid: Extensible XMPP Bot")
    parser.add_argument("-c", "--config", default="",
                        help="Configuration file to use.")
    parser.add_argument("-l", "--level", type=int, default=logging.INFO,
                        help="Logging level. Lower is more verbose.")
    parser.add_argument("-L", "--logfile", default=None,
                        help="File for logging output.")
    parser.add_argument("-t", "--logtraffic", action='store_true',
                        help="Additionally log all traffic.")
    parser.add_argument("-w", "--logtwisted", action='store_true',
                        help="Additionally include twisted logging.")
    parser.add_argument("-m", "--manhole", const=True, nargs='?', 
                        metavar="user@host:port", 
                        help="Login name, host and port for ssh access. "
                        "Any (or none) of the 3 parts can be specified "
                        "as follows: [user][@host][:port]")
    args = parser.parse_args(args)

    cmd = args.config
    env = os.environ.get("ENDROID_CONF", "")
    usr = os.path.expanduser(os.path.join("~", ".endroid", "endroid.conf"))
    gbl = "/etc/endroid/endroid.conf"

    try:
        conffile = (p for p in (cmd, env, usr, gbl) if os.path.exists(p)).next()
    except StopIteration:
        sys.stderr.write("EnDroid requires a configuration file.\n")
        sys.exit(1)

    print("EnDroid starting up with config file {}".format(conffile))

    droid = Endroid(conffile, args=args)

    manhole_dict = dict([('droid', droid)] + globals().items())
    manhole_setup(args.manhole, droid.conf, manhole_dict)

    # Start the reactor
    droid.run()

