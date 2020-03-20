from endroid.plugins.command import CommandPlugin
from endroid.cron import Cron
from collections import defaultdict
from endroid.database import Database

DB_NAME = "PTB"
DB_TABLE = "PTB"

class User(object):
    __slots__ = ('name', 'kills', 'shield')
    def __init__(self, name, kills=0, shield=True):
        self.name = name
        self.kills = kills
        self.shield = shield

    def __repr__(self):
        fmt = "User(name={}, kills={}, shield={})"
        return fmt.format(self.name, self.kills, self.shield)

class Bomb(object):
    ID = 0
    def __init__(self, source, fuse, plugin):
        self.source = source  # who lit the bomb?
        self.user = None  # our current holder
        self.plugin = plugin  # plugin instance we belong to
        self.history = set()  # who has held us?

        idstring = self.get_id()  # get a unique registration_name
        plugin.cron.register(self.explode, idstring)
        plugin.cron.setTimeout(fuse, idstring, None)  # schedule detonation

    # this function is called by Cron and given an argument. We don't need an
    # argument so just ignore it
    def explode(self, _):
        # some shorthands
        get_rooms = self.plugin.usermanagement.get_available_rooms
        send_muc = self.plugin.messagehandler.send_muc
        send_chat = self.plugin.messagehandler.send_chat

        msg_explode = "!!!BOOM!!!"
        msg_farexplode = "You hear a distant boom"
        msg_kill = "{} was got by the bomb"

        rooms = get_rooms(self.user)
        for room in rooms:
            # let everyone in a room with self.user here the explosion
            send_muc(room, msg_explode)
            send_muc(room, msg_kill.format(self.user))

        # alert those who passed the bomb that it has exploded
        for user in self.history:
            if user == self.user:
                send_chat(self.user, msg_explode)
                send_chat(self.user, msg_kill.format("You"))
            else:
                send_chat(user, msg_farexplode)
                send_chat(user, msg_kill.format(self.user))

        self.plugin.register_kill(self.source)
        self.plugin.bombs[self.user].discard(self)


    def throw(self, user):
        # remove this bomb from our current user
        self.plugin.bombs[self.user].discard(self)

        self.history.add(user)
        self.user = user

        # add it to the new user
        self.plugin.bombs[self.user].add(self)

    @classmethod
    def get_id(cls):
        # generate a unique id string to register our explode method against
        result = Bomb.ID
        cls.ID += 1
        return "bomb" + str(result)


class PassTheBomb(CommandPlugin):
    help = "Pass the bomb game for EnDroid"
    bombs = defaultdict(set)  # users : set of bombs
    users = dict()  # user strings : User objects

    def endroid_init(self):
        self.db = Database(DB_NAME)
        if not self.db.table_exists(DB_TABLE):
            self.db.create_table(DB_TABLE, ('user', 'kills'))

        # make a local copy of the registration database
        data = self.db.fetch(DB_TABLE, ['user', 'kills'])
        for dct in data:
            self.users[dct['user']] = User(dct['user'], dct['kills'])

    def cmd_furl_umbrella(self, msg, arg):
        """This is how a user enters the game - allows them to be targeted
        and to create and throw bombs"""
        user = msg.sender
        if not self.get_shielded(user):
            msg.reply("Your umbrella is already furled!")
        else:
            if self.get_registered(user):
                self.users[user].shield = False
            else:  # they are not - register them
                self.db.insert(DB_TABLE, {'user': user, 'kills': 0})
                self.users[user] = User(user, kills=0, shield=False)
            msg.reply("You furl your umbrella!")
    cmd_furl_umbrella.helphint = ("Furl your umbrella to participate in the "
                                  "noble game of pass the bomb!")

    def cmd_unfurl_umbrella(self, msg, arg):
        """A user with an unfurled umbrella cannot create or receive bombs"""
        user = msg.sender
        if self.get_shielded(user):
            msg.reply("Your umbrella is already unfurled!")
        else:
            # to get user must not have been shielded ie they must have furled
            # so they will be in the database
            self.users[user].shield = True
            msg.reply("You unfurl your umbrella! No bomb can reach you now!")
    cmd_unfurl_umbrella.helphint = ("Unfurl your umbrella to cower from the "
                                    "rain of boms!")

    def cmd_bomb(self, msg, arg):
        """Create a bomb with a specified timer.

        eg: 'bomb 1.5' for a 1.5 second fuse

        """

        holder = msg.sender
        if self.get_shielded(holder):
            return msg.reply("Your sense of honour insists that you furl your "
                              "umbrella before lighting the fuse")
        # otherwise get a time from the first word of arg
        try:
            time = float(arg.split(' ', 1)[0])
            # make a new bomb and throw it to its creator
            Bomb(msg.sender, time, self).throw(msg.sender)
            msg.reply("Sniggering evilly, you light the fuse...")
        # provision for a failure to read a time float...
        except ValueError:
            msg.reply("You struggle with the matches")
    cmd_bomb.helphint = ("Light the fuse!")

    def cmd_throw(self, msg, arg):
        """Throw a bomb to a user, eg: 'throw benh@ensoft.co.uk'"""
        target = arg.split(' ')[0]
        # we need a bomb to thrown
        if not self.bombs[msg.sender]: 
            msg.reply("You idly throw your hat, wishing you had something " 
                       "rounder, heavier and with more smoking fuses.")
        # need our umbrella to be furled
        elif self.get_shielded(msg.sender):
            msg.reply("You notice that your unfurled umbrella would hinder "
                       "your throw.")
        # check that target is online
        elif not target in self.usermanagement.get_available_users():
            msg.reply("You look around but cannot spot your target")
        elif self.get_shielded(target):  # target registered/vulnerable?
            msg.reply("You see your target hunkered down under their umbrella. "
                       "No doubt a bomb would have little effect on that "
                       "monstrosity.")
        else:
            self.bombs[msg.sender].pop().throw(target)
            msg.reply("You throw the bomb!")
            self.messagehandler.send_chat(target, "A bomb lands by your feet!")
    cmd_throw.helphint = ("Throw a bomb!")

    def cmd_kills(self, msg, arg):
        kills = self.get_kills(msg.sender)
        nick = self.usermanagement.get_nickname(msg.sender, 
                                                     self.place_name)
        level = self.get_level(kills)

        text = "{} the {} has {} kill".format(nick, level, kills)
        text += ("" if kills == 1 else "s")
        msg.reply(text)
    cmd_kills.helphint = ("Receive and gloat over you score!")

    def register_kill(self, user):
        kills = self.get_kills(user)
        # change the value of 'kills' to kills+1 in the row where 'user' = user
        self.users[user].kills += 1
        self.db.update(DB_TABLE, {'kills': kills+1}, {'user': user})

    def get_kills(self, user):
        return self.users[user].kills if user in self.users else 0

    def get_shielded(self, user):
        return self.users[user].shield if user in self.users else True

    def get_registered(self, user):
        return user in self.users

    @staticmethod
    def get_level(kills):
        if kills < 5:
            level = 'novice'
        elif kills < 15:
            level = 'apprentice'
        elif kills < 35:
            level = 'journeyman'
        elif kills < 65:
            level = 'expert'
        elif kills < 100:
            level = 'master'
        else:
            level = 'grand-master'
        return level
