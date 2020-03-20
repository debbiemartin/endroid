# -----------------------------------------------------------------------------
# EnDroid - Pub Picker Plugin
# Copyright 2012, Martin Morrison
# -----------------------------------------------------------------------------

import random, re

from endroid.pluginmanager import Plugin
from endroid.database import Database

# Constants for the DB values we use
DB_NAME = "PubPicker"
DB_TABLE = "PubList"
DB_ALIAS = "PubAlias"

# Some regular expressions for the alias command
ALIAS_FOR = re.compile("(.*?) for (.*)", re.I)
ALIAS_TO = re.compile("(.*?) to (.*)", re.I)
ALIAS_ERROR = "Alias loop detected! (starts at '{}')"

class AliasError(Exception):
    pass

class AliasEmptyError(Exception):
    pass

class PubPicker(Plugin):
    name = "pubpicker"

    def enInit(self):
        self.venuetype = self.vars.get("venuetype", "pub")
        if ":" in self.venuetype:
            self.venuetype, self.pluraltype = self.venuetype.split(":")
        else:
            self.pluraltype = self.venuetype + "s"
        com = self.get('endroid.plugins.command')
        com.register_both(self.register, ('register', self.venuetype), '<name>',
                          synonyms=(('register', 'new', self.venuetype),
                                    ('register', 'a', 'new', self.venuetype)))
        com.register_both(self.picker, ('pick', 'a', self.venuetype),
                          synonyms=(('pick', self.venuetype),))
        com.register_both(self.vote_up, ('vote', self.venuetype, 'up'),
                          '<name>')
        com.register_both(self.vote_down, ('vote', self.venuetype, 'down'),
                          '<name>')
        com.register_both(self.alias, ('alias', self.venuetype),
                          '<name> to <alias>')
        com.register_both(self.list, ('list', self.pluraltype),
                          synonyms=(('list', self.venuetype),))
        com.register_both(self.list_aliases, ('list', self.venuetype, 'aliases'))
        com.register_both(self.rename, ('rename', self.venuetype),
                          '<oldname> to <newname>')

        self.db = Database(DB_NAME)
        self.setup_db()
        self.load_db()

    def help(self):
        return "Let EnDroid pick a " + self.venuetype + " for you!"

    def load_db(self):
        self.pubs = {}
        self.aliases = {}
        for row in self.db.fetch(DB_TABLE, ("name", "score")):
            self.pubs[row["name"]] = int(row["score"])
        for row in self.db.fetch(DB_ALIAS, ("name", "alias")):
            self.aliases[row["alias"]] = row["name"]

    def setup_db(self):
        if not self.db.table_exists(DB_TABLE):
            self.db.create_table(DB_TABLE, ("name", "score"))
        if not self.db.table_exists(DB_ALIAS):
            self.db.create_table(DB_ALIAS, ("name", "alias"))

    def add_alias(self, pub, alias):
        if not alias:
            raise AliasEmptyError('Pub name cannot be empty.')
        if pub == alias:
            return # loops are bad :-)
        if alias in self.aliases:
            self.db.delete(DB_ALIAS, {"alias": alias})
        self.aliases[alias] = pub
        self.db.insert(DB_ALIAS, {"alias": alias, "name": pub})
        self.add_alias(alias, alias.lower())

    def resolve_alias(self, alias):
        seen = set()
        while alias in self.aliases:
            if alias in seen:
                raise AliasError(alias)
            alias = self.aliases[alias]
            seen.add(alias)
        if not alias:
            raise AliasEmptyError('Pub string cannot be empty.')
        return alias

    # command
    def vote_up(self, msg, pub):
        if not pub:
            msg.reply('Pub string should not be empty.')
            return
        try:
            pub = self.resolve_alias(pub)
        except AliasError as e:
            return msg.reply(ALIAS_ERROR.format(e))
        except AliasEmptyError:
            return msg.reply('Pub name cannot be empty.')
        if pub not in self.pubs:
            self.pubs[pub] = 10
            self.db.insert(DB_TABLE, {"name": pub, "score": 10})
            self.add_alias(pub, pub.lower())
        else:
            self.pubs[pub] += 1
            self.save_pub(pub)

    # command
    def vote_down(self, msg, pub):
        if not pub:
            msg.reply('Pub string should not be empty.')
            return
        try:
            pub = self.resolve_alias(pub)
        except AliasError as e:
            return msg.reply(ALIAS_ERROR.format(e))
        except AliasEmptyError:
            return msg.reply('Pub name cannot be empty.')
        if pub in self.pubs:
            self.pubs[pub] = max(self.pubs[pub] - 1, 0)
            self.save_pub(pub)

    def rename_pub(self, oldname, newname):
        if not newname:
            raise AliasEmptyError('Pub name must not be empty.')
        self.add_alias(newname, oldname)
        score = self.pubs[oldname]
        self.db.delete(DB_TABLE, {"name": oldname})
        del self.pubs[oldname]
        self.pubs[newname] = score
        self.db.insert(DB_TABLE, {"name": newname, "score": score})
        self.add_alias(newname, newname.lower())

    def save_pub(self, pub):
        self.db.update(DB_TABLE, {"score": self.pubs[pub]}, {"name": pub})
        self.add_alias(pub, pub.lower())

    def pick_a_pub(self):
        # I imagine this can be done more cheaply...
        pubs = []
        for pub, score in self.pubs.items():
            if pub:  # if someone enters an empty pub and we pick that pub,
                     # we'll end up reacting as if we didn't know any pubs
                     # if we test for "if not __" rather than "if __ is None"
                pubs += [pub] * score
        if pubs:
            return random.choice(pubs)
        else:
            return None

    # command
    def register(self, msg, arg):
        try:
            self.vote_up(msg, self.resolve_alias(arg))
        except AliasError as e:
            msg.reply(ALIAS_ERROR.format(e))
        except AliasEmptyError:
            msg.reply('Pub name cannot be empty.')

    # command
    def picker(self, msg, arg):
        pub = self.pick_a_pub()
        if pub is not None:
            msg.reply("Today, you should definitely go to %s" % pub)
        else:
            msg.reply("Unfortunately, I don't seem to know about any pubs "
                      "that anyone wants to go to")

    # command
    def alias(self, msg, arg):
        mf = ALIAS_FOR.match(arg)
        mt = ALIAS_TO.match(arg)
        if mf:
            self.add_alias(mf.group(2), mf.group(1))
        elif mt:
            self.add_alias(mt.group(1), mt.group(2))
        else:
            msg.unhandled()

    # command
    def rename(self, msg, arg):
        mt = ALIAS_TO.match(arg)
        if mt:
            try:
                self.rename_pub(self.resolve_alias(mt.group(1)), mt.group(2))
            except AliasError as e:
                msg.reply(ALIAS_ERROR.format(e))
            except AliasEmptyError:
                msg.reply('Pub name cannot be empty.')
        else:
            msg.unhandled()

    # command
    def list(self, msg, arg):
        reply = ["Registered " + self.pluraltype + " (and their scores):"]
        reply.extend("%s (%d)" % (p, s) for p, s in self.pubs.items())
        msg.reply("\n".join(reply))

    # command
    def list_aliases(self, msg, arg):
        reply = ["Known " + self.venuetype + " aliases:"]
        reply.extend("%s -> %s" % (a, p) for a, p in self.aliases.items())
        msg.reply("\n".join(reply))        

    def dependencies(self):
        return ['endroid.plugins.command']
