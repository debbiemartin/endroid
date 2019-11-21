# Endroid - Webex Bot
# Copyright 2012, Ensoft Ltd.
# Created by Jonathan Millican, and mangled beyond recognition by SimonC

import logging, re, time
from twisted.internet import defer, error, protocol, reactor
from endroid.plugins.command import CommandPlugin, command

HI5_TABLE = 'hi5s'

class FilterProtocol(protocol.ProcessProtocol):
    """
    Send some data to a process via its stdin, close it, and reap the output
    from its stdout. Twisted arguably ought to provide a utility function for
    this - there's nothing specific to GPG or high-fiving here.
    """
    def __init__(self, in_data, deferred, args):
        self.in_data = in_data
        self.deferred = deferred
        self.args = args
        self.out_data= ''

    def connectionMade(self):
        self.transport.write(self.in_data.encode('utf-8'))
        self.transport.closeStdin()

    def outReceived(self, out_data):
        self.out_data += out_data.decode('utf-8')

    def outConnectionLost(self):
        d, self.deferred = self.deferred, None
        d.callback(self.out_data)

    def processEnded(self, reason):
        if isinstance(reason.value, error.ProcessTerminated):
            logging.error("Problem running filter ({}): {}".
                format(self.args, reason.value))
            d, self.deferred = self.deferred, None
            d.errback(reason.value)

class Hi5(CommandPlugin):
    """
    The Hi5 plugin lets you send anonymous 'High Five!' messages to other
    users known to Endroid. The idea is that it makes it easy to send a
    compliment to somebody. The most basic usage is:

      hi5 user@example.com Nice presentation dude!

    which, if user@example.com is known to EnDroid and currently logged in,
    sends both a unicast chat to that user with the anonymous compliment,
    and also anonymously announces to one or more configured chatrooms that
    user@example.com got the High Five 'Nice presentation dude!'.

    Slightly more complicated examples: it's possible to send a compliment
    to multiple users at once, by using comma-separation, and also omit
    the domain part of the JID if the user is unambiguous given all the
    users known to EnDroid. So for example:

      hi5 bilbo@baggins.org, frodo, sam Good work with the Nazgul guys :-)

    There is some basic anonymous logging performed by default, that includes
    only the time/date and recipient JID. However, if you configure a GPG
    public key, then an asymmetrically encrypted log that also includes the
    sender and message is done. That provides a last-resort mechanism should
    someone use the mechanism for poisonous purposes, but requires the private
    key and passphrase. The 'spelunk_hi5' script can be used for this.
    """

    name = "hi5"
    help = ("Send anonymous 'hi5s' to folks! Your message is sent from EnDroid"
            " direct to the recipient, as well as being broadcast in any "
            "configured public chat rooms.")
    
    def endroid_init(self):
        if 'gpg' in self.vars:
            self.gpg = ('/usr/bin/gpg', '--encrypt', '--armor',
                        '--batch', '--trust-model', 'always',
                        '--keyring', self.vars['gpg'][0],
                        '--recipient', self.vars['gpg'][1])
        else:
            self.gpg = None
        if not self.database.table_exists(HI5_TABLE):
            self.database.create_table(HI5_TABLE, ['jids', 'date', 'encrypted'])

    @command(helphint="{user}[,{user}] {message}")
    def hi5(self, msg, arg):
        # Parse the request
        try:
            jids, text = self._parse(arg)
            assert len(text) > 0
        except Exception:
            msg.reply("Sorry, couldn't spot a message to send in there. Use "
                      "something like:\n"
                      "hi5 frodo@shire.org, sam, bilbo@rivendell Nice job!")
            return

        # Sanity checks, and also expand out 'user' to 'user@host' 
        # if we can do so unambiguously
        fulljids = []
        for jid in jids:
            if '/' in jid:
                msg.reply("Recipients can't contain '/'s".format(jid))
                return
            fulljid = self._get_fulljid(jid)
            if not fulljid:
                msg.reply("{0} is not a currently online valid receipient. "
                          "Sorry.".format(jid))
                return
            elif fulljid == msg.sender:
                msg.reply("You really don't have to resort to complimenting "
                          "yourself. I already think you're great")
                return
            fulljids.append(fulljid)

        # Do it
        self._do_hi5(jids, fulljids, text, msg)
    
    def _do_hi5(self, jids, fulljids, text, msg):
        """
        Actually send the hi5
        """
        # jidlist is a nice human-readable representation of the lucky
        # receipients, like 'Tom, Dick & Harry'
        if len(jids) > 1:
            jidlist = ', '.join(jids[:-1]) + ' & ' + jids[-1]
        else:
            jidlist = jids[0]

        msg.reply('A High Five "' + text + '" is being sent to ' + jidlist)
        self._log_hi5(','.join(fulljids), msg.sender, text)

        for jid in fulljids:
            self.messagehandler.send_chat(jid, "You've been sent an anonymous "
                                               "High Five: " + text)
        for group in self.vars.get('broadcast', []):
            groupmsg = '{} {} been sent an anonymous High Five: {}'.format(
                jidlist, 'have' if len(jids) > 1 else 'has', text)
            self.messagehandler.send_muc(group, groupmsg)
    
    @staticmethod
    def _parse(msg):
        """
        Parse something like ' bilbo@baggins.org, frodo, sam great job! ' into
        (['bilbo@baggsins.org', 'frodo', 'sam'], 'great job!')
        """
        jids = []
        msg = msg.strip()
        while True:
            m = re.match(r'([^ ,]+)( *,? *)(.*)', msg)
            jid, sep, rest = m.groups(1)
            jids.append(jid)
            if sep.strip():
                msg = rest
            else:
                return jids, rest

    def _get_fulljid(self, jid):
        """
        Expand a simple 'user' JID to 'user@host' if we can do so unambiguously
        """
        users = self.usermanagement.get_available_users()
        if jid in users:
            return jid
        expansions = []
        for user in users:
            if user.startswith(jid + '@'):
                expansions.append(user)
        if len(expansions) == 1:
            return expansions[0]

    def _log_hi5(self, jidlist, sender, text):
        """
        Log the hi5. This either means spawning a GPG process to do an
        asymmetric encryption of the whole thing, or just writing a basic
        summary straight away.
        """
        now = time.ctime()
        def db_insert(encrypted):
            self.database.insert(HI5_TABLE, {'jids':jidlist, 
                                 'date':now, 'encrypted': encrypted})
        def db_insert_err(err):
            logging.error("Error with hi5 database entry: {}".format(err))
            db_insert(None)
        if self.gpg:
            d = defer.Deferred()
            d.addCallbacks(db_insert, db_insert_err)
            gpg_log = '{}: {} -> {}: {}'.format(now, sender, jidlist, text) 
            fp = FilterProtocol(gpg_log, d, self.gpg)
            reactor.spawnProcess(fp, self.gpg[0], self.gpg, {})
        else:
            db_insert(None)

