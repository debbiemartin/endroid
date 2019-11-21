from twisted.cred import portal, checkers
from twisted.conch import manhole, manhole_ssh
from twisted.internet import reactor
import logging


def manhole_factory(nmspace, **passwords):
    realm = manhole_ssh.TerminalRealm()

    def getManhole(_):
        return manhole.Manhole(nmspace)

    realm.chainedProtocolFactory.protocolFactory = getManhole
    p = portal.Portal(realm)
    p.registerChecker(
        checkers.InMemoryUsernamePasswordDatabaseDontUse(**passwords)
    )
    f = manhole_ssh.ConchFactory(p)
    return f


def start_manhole(nmspace, user, password, host, port):
    """
    Start EnDroid listening for an ssh connection.

    Logging in via ssh gives access to a python prompt from which EnDroid's
    internals can be investigated. Connect to the manhole using e.g.
       ssh user@host -p port

    nmspace - The namespace to make available to the manhole
    user - Logon username. 
    password - Password to use for the manhole
    host - Host where the manhoe connection will be made.
    port - The port to open for the manhole. 

    """

    logging.info("Starting manhole with user: %s, host: %s and port: %s",
                 user, host, port)
    
    reactor.listenTCP(int(port), manhole_factory(nmspace, **{user: password}),
                      interface=host)
 
