# -----------------------------------------------------------------------------
# EnDroid - ReliableSend Plugin (based off the original Memo plugin)
# Copyright 2014, James Harkin and Patrick Stevens (original: 2012, Ben Eills)
# -----------------------------------------------------------------------------

"""
Plugin to send messages between users even if the recipient is not online.
"""
import time

from endroid.plugins.command import CommandPlugin, command
from endroid.database import Database

DB_NAME = "Message"
DB_TABLE = "Messages"
DB_COLUMNS = ("sender", "recipient", "text", "date")
SUMMARY_WIDTH = 60


class ReliableSend(CommandPlugin):
    """Plugin to send messages to a user, storing them if they are offline."""

    name = "reliable"

    help = ("Send a message, storing it to be sent automatically later if the "
            "recipient is not online. \n "
            "Commands: reliable message <recipient> <message> to send message "
            "to given person, storing it if necessary.")

    def endroid_init(self):
        self.db = Database(DB_NAME)
        if not self.db.table_exists(DB_TABLE):
            self.db.create_table(DB_TABLE, DB_COLUMNS)

    def _delete_messages(self, recipient):
        """
        Deletes all message that were stored for later sending.
        Take care with this: it will allow you to delete even messages your
        plugin didn't send.
        :param recipient: JID of the person in question
        """
        self.db.delete(DB_TABLE, {'recipient': recipient})

    def _send_stored_messages(self, recipient):
        """
        Sends all the stored messages for a given recipient.
        Note that we delete them from storage afterwards.
        :param recipient: the JID of the person we want to receive the messages
        """
        cond = {'recipient': recipient}
        rows = self.db.fetch(DB_TABLE, DB_COLUMNS, cond)

        for row in rows:
            message = "Message received from {} on {}:\n{}".format(row['sender'],
                                                                   row['date'],
                                                                   row['text'])
            self.messages.send_chat(recipient, message)
        self._delete_messages(recipient)

    def send_reliably(self, sender, message_text, recipient):
        """
        Sends a message to a user so that they will receive it eventually.
        If the user is offline, stores the message and sends it when they come
        online next.
        :param sender: who sent the message (JID)
        :param message_text: text of the message
        :param recipient: who is to receive the message (JID)
        :return: False if the recipient was already online and so we sent the
         messages immediately; True if we stored them.
        """
        self.db.insert(DB_TABLE, {'sender': sender,
                                  'recipient': recipient,
                                  'text': message_text,
                                  'date': time.asctime(time.localtime())})

        if self.rosters.is_online(recipient):
            self._send_stored_messages(recipient)
            return False
        else:
            cb = lambda: self._send_stored_messages(recipient)
            self.rosters.register_presence_callback(recipient,
                                                    callback=cb,
                                                    available=True)
            return True

    @command(helphint="<recipient> <message>", synonyms=('reliable send',))
    def reliable_message(self, msg, args):
        args = args.split()
        if len(args) < 2:
            msg.reply("reliable message <recipient> <message> \t Send a message")
            return
        recipient, message = args[0], ' '.join(args[1:])

        if not self.send_reliably(msg.sender, message, recipient):
            msg.reply('{} was already online; I sent the message immediately.'.format(recipient))
        else:
            msg.reply('I will send the message to {} when they come online.'.format(recipient))
