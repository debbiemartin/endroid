from endroid.plugins.command import CommandPlugin
from endroid.database import Database
import logging


DB_NAME = "BROADCAST"
DB_TABLE = "BROADCAST"


class Levels(object):
    NONE = "none"
    ALL = "all"
    POSITIVE = "positive"
    MAX = "max"

    @classmethod
    def __contains__(cls, key):
        return key in (cls.NONE, cls.ALL, cls.POSITIVE, cls.MAX)


class Broadcast(CommandPlugin):
    """
    This plugin partially solves the problem with XMPP that if a user is logged
    in on multiple devices (resources) then messages sent by EnDroid may not 
    arrive at all of them.

    When broadcasting is enabled by a user, any messages sent by EnDroid to them
    will be intercepted and replaced by several identical messages sent 
    individually to a selection of their resources.

    Note:
    - this plugin only applies to chat messages (room messages do not suffer
    the same problem)
    - the plugin may be configured to broadcast at levels:
      - all: send to all the recipient's available resources
      - positive: send to the recipient's available resources with priority >=0
      - max: send to the recipient's maximum priority resource
      - none (default): disable broadcasting

    """
    help = "Plugin to enable the broadcasting of messages to all resources."
    users = {}

    levels = Levels()
    
    ID = "broadcast_plugin"  # this will be set as the source of sent messages

    def endroid_init(self):
        self.register_chat_send_filter(self.do_broadcast)
        self.db = Database(DB_NAME)
        if not self.db.table_exists(DB_TABLE):
            self.db.create_table(DB_TABLE, ('user', 'do_broadcast'))

        # make a local copy of the registration database
        data = self.db.fetch(DB_TABLE, ['user', 'do_broadcast'])
        for row in data:
            self.users[row['user']] = row['do_broadcast']

    def do_broadcast(self, msg):
        sender = msg.sender
        if sender == self.ID:  # we sent this message
            return True

        recipient = msg.recipient
        recip_host = self.usermanagement.get_userhost(recipient)

        logging.debug("Broadcast got message {} -> {}".format(sender, recipient))
        # Check the broadcast level for recip_host (if they are not 
        # registered return levels.NONE).
        level = self.users.get(recip_host, self.levels.NONE)

        if level == self.levels.NONE:
            # we are not broadcasting to this user, let the original message
            # through and do nothing
            return True
        else:
            # we have some broadcasting to do
            rs = self._get_resources(recip_host, level)

            sent_num = 0
            for resource in rs:
                self.messagehandler.send_chat(resource, msg.body, self.ID)
                sent_num += 1

            fmt = "Broadcast '{}' sent {} messages to {}"
            logging.debug(fmt.format(level, sent_num, recip_host))
            # drop the original message
            return False


    def cmd_set_broadcast(self, msg, arg):
        """
        When this is called, messages EnDroid sends will be sent to _all_
        the user's available resources.

        """
        level = arg.split()[0]
        level = level if level in self.levels else self.levels.ALL
        # this will be broadcasted
        msg.reply("Setting broadcast level '{}'.".format(level))
        if not msg.sender in self.users:
            self._register_user(msg.sender, level=level)
        else:
            self._update_user(msg.sender, level=level)
        # this may not be broadcasted, depending on what level has been set to
        msg.reply("Set broadcast level '{}'.".format(level))

    cmd_set_broadcast.helphint = ("{all|positive|max|none} (all, positive, max "
                                  "process resource priorities.")


    def cmd_disable_broadcast(self, msg, arg):
        """Disable broadcasting."""
        self.cmd_set_broadcast(msg, self.levels.NONE)
        # msg.reply("Disabling broadcast.")
        # if self.users[msg.sender]:
        #     self._update_user(msg.sender, level=self.levels.NONE)
        # msg.reply("Disabled broadcast.")

    cmd_disable_broadcast.helphint = ("Equivalent to 'set broadcast none'.")

    def cmd_get_broadcast(self, msg, arg):
        """Get broadcast level."""
        level = self.users.get(msg.sender, self.levels.NONE)
        message = "Broadcast level '{}'".format(level)
        if arg and arg.split()[0] in ("ls", "list"):
            rs = self._get_resources(msg.sender, level)
            message += ':'
            msg.reply('\n'.join([message] + (rs or ["none"])))
        else:
            message += '.'
            msg.reply(message)

    cmd_get_broadcast.helphint = ("{ls|list}?")

    def cmd_get_resources(self, msg, arg):
        """Return msg.sender's available resources.

        If arg is "broadcast", return those we are broadcasting to.

        """
        message = ["Available resources:"]
        rs = self._get_resources(msg.sender)
        msg.reply('\n'.join(message + (rs or ["none"])))

    cmd_get_resources.helphint = ("Report all available resources.")

    def _register_user(self, user, level=levels.NONE):
        self.db.insert(DB_TABLE, {'user' : user, 'do_broadcast' : level})
        self.users[user] = level

    def _update_user(self, user, level=levels.NONE):
        self.db.update(DB_TABLE, {'do_broadcast' : level}, {'user' : user})
        self.users[user] = level

    def _get_resources(self, user, level=levels.ALL):
        resources = self.usermanagement.resources(user)
        addresses = []

        if level == self.levels.ALL:
            addresses = resources.keys()
        elif level == self.levels.POSITIVE:
            addresses = [j for j, r in resources.items() if r.priority >= 0]
        elif level == self.levels.MAX:
            # resources.items is a list of tuples of form: (jid : Resource)
            # sort on Resource.priority
            # this returns the tuple (jid : max_priority_resource)
            # get just the jid by indexing with [0]
            addresses = [max(resources.items(), key=lambda (j,r): r.priority)[0]]

        return addresses    
