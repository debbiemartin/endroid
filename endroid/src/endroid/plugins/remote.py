# -----------------------------------------------------------------------------
# EnDroid - Remote notification plugin
# Copyright 2012, Ensoft Ltd
# -----------------------------------------------------------------------------

import random
import string
import UserDict

from endroid.database import Database
from endroid.pluginmanager import Plugin

# Database and table names for the key database.
DB_NAME = "Remote"
DB_TABLE = "Keys"

# Length and set of characters that make up keys.
KEY_LENGTH = 16
KEY_CHARS = string.ascii_uppercase + string.digits

# Templates for HTML responses.
FORM_PAGE = """
<!DOCTYPE html>
<html>
    <body>
        <form method="POST">
            {header_msg}
            User: <input name="user" type="text" />
            Key: <input name="key" type="text" /> <br />
            SMS: <input name="sms" type="checkbox" /> <br />
            Message: <input name="message" type="text" /><br />
            <input name="submit" value="submit" type="submit" /><br />
        </form>
    </body>
</html>
"""

ERROR_PAGE = """
<!DOCTYPE html>
<html>
    <head><title>Error</title></head>
    <body>
        <h1>Error</h1>
        Error: {error_string}
    </body>
</html>
"""

# Message displayed by the help message.
HELP_MESSAGE = """
Send messages to users via a web interface. A key is required to send
a user messages. The following commands are supported:
    - allow remote: Generate a key to allow others to message you.
    - deny remote: Delete a previously generated key.
"""

class RemoteError(Exception):
    """Base class for errors that will be passed up to the HTTP client."""


class InputError(RemoteError):
    """Invalid input from the HTTP client."""


class UnavailableError(RemoteError):
    """The requested user is not available for messaging."""


class DatabaseDict(object, UserDict.DictMixin):
    """
    Dict-like object backed by a sqlite DB.
    """
    def __init__(self, db, table, key_column, val_column):
        """
        db: Database to store the dictionary data.
        table: Name of the table to store the dictionary data.
        key_column: Name of the column to store dictionary keys.
        val_column: Name of the column to store dictionary values.
        """

        self.db = db
        self.table = table
        self.key_column = key_column
        self.val_column = val_column

        if not self.db.table_exists(self.table):
            self.db.create_table(self.table, (key_column, val_column))

    def keys(self):
        return (result[self.key_column] for result
                    in self.db.fetch(self.table, [self.key_column]))

    def __delitem__(self, key):
        if key in self:
            c = self.db.delete(self.table, {self.key_column: key})
            assert c == 1

    def __setitem__(self, key, val):
        if key in self:
            c = self.db.update(self.table,
                              {self.key_column: key, self.val_column: val},
                              {self.key_column: key})
            assert c == 1
        else:
            self.db.insert(self.table,
                           {self.key_column: key, self.val_column: val})

    def __getitem__(self, key):
        results = self.db.fetch(self.table,
                                [self.key_column, self.val_column],
                                {self.key_column: key})
        assert len(results) <= 1
        if len(results) == 0:
            raise KeyError(key)
        return results[0][self.val_column]

class RemoteNotification(Plugin):
    name = "remote"

    def endroid_init(self):
        com = self.get('endroid.plugins.command')

        com.register_chat(self.allow, ('allow', 'remote'))
        com.register_chat(self.deny, ('deny', 'remote'))

        http = self.get('endroid.plugins.httpinterface')
        http.register_path(self, self.http_request_handler, '')

        self.sms = self.get('endroid.plugins.sms')

        self.keys = DatabaseDict(Database(DB_NAME), DB_TABLE, "users", "keys")

    def help(self):
        return HELP_MESSAGE

    dependencies = ['endroid.plugins.command',
                    'endroid.plugins.httpinterface']

    preferences = ['endroid.plugins.sms']

    @staticmethod
    def _make_key():
        return ''.join(random.choice(KEY_CHARS) for x in range(KEY_LENGTH))

    def allow(self, msg, arg):
        jid = msg.sender
        if jid in self.keys:
            msg.reply("Remote notifications already allowed. (Your key is %s.)"
                        % self.keys[jid])
        else:
            key = RemoteNotification._make_key()
            self.keys[jid] = key
            msg.reply("Remote notifications allowed. Your key is %s." % key)

    def deny(self, msg, arg):
        jid = msg.sender
        if jid in self.keys:
            del self.keys[jid]
            msg.reply("Remote notifications denied.")
        else:
            msg.reply("Remote notifications already denied. Nothing to do.")

    def _parse_args(self, args):
        """
        Parse the HTML post args into python args.

        Returns: user, key, urgent (a bool) and message
        Validation includes:
            * Checking expected arguments are present.
            * Checking the user is in the database.
            * Checking the key matches the user's.

        Raises:
            InputError: If the args are invalid

        """

        req_args = ['user', 'key', 'message']
        missing_args = list(set(req_args) - set(args.keys()))

        if len(missing_args) > 0:
            raise InputError("Missing arguments: %s" % ' '.join(missing_args))

        # Arguments come in the form of singleton arrays. Do some preprocessing
        # to extract only the first element.
        args = dict((key, val[0]) for key, val in args.iteritems())

        if args['user'] not in self.keys:
            raise InputError("User {user} has not allowed remote messaging. "
                             "{user} can generate a key with "
                             "'allow remote'".format(**args))

        if self.keys[args['user']] != args['key']:
            raise InputError("Incorrect key provided for {user}"
                                .format(**args))

        urgent = False 
        if args.get('sms', 'false') in ("true", "on"):
            urgent = True

        return args['user'], args['key'], urgent, args['message']

    def send_sms(self, recipient, message, on_error):
        """
        Send message to recipient using SMS, on failure call on_error.
        """

        # Shorten the message because SMS is precious
        if len(message) > 320:
            sms_message_to_send = message[:317] + "..."
        else:
            sms_message_to_send = message
        send = self.sms.send_sms(sender=recipient,
                                 jid=recipient,
                                 message=sms_message_to_send)
        send.addErrback(on_error)

    def wait_for_ack(self, user, msg):
        """Send msg to user, if no ack received try SMS."""

        def sms_failed(failure):
            self.messagehandler.send_chat(
                user, "My SMS attempt failed, sorry.")

        def no_ack(recipient):
            self.messagehandler.send_chat(
                recipient, "I didn't get a response so I'll try SMS.")
            self.send_sms(recipient, msg, on_error=sms_failed)

        def ack(message):
            message.reply('Receipt acknowledged.')

        self.messagehandler.send_chat(
            user, msg + '\n\nPlease acknowledge by replying to this.',
            response_cb=ack, 
            no_response_cb=no_ack,
            timeout=30)

    def http_request_handler(self, request):
        """
        A callback from the httpinterface plugin. Renders a form to allow
        sending a user a message. If POST data from the form is included
        a message is sent, unless the input is invalid in which case an
        error page is displayed.  We only allow 320 character messages to be
        sent over text. Any more than that is shortened.
        """

        try:
            header_msg = ''
            if request.method == 'POST':
                user, key_not_used, urgent, msg = self._parse_args(request.args)
                msg = "Remote notification received: {}".format(msg)

                if self.sms.number_known(user) and urgent:
                    # If the user is online Webex the message and get an ack
                    # otherwise try SMS
                    if self.rosters.is_online(user):
                        self.wait_for_ack(user, msg)
                    else:
                        def sms_failed(failure):
                            self.messagehandler.send_chat(
                                user=user, source=user, 
                                body=msg + '\n\nPlease acknowledge by replying to this.',
                                response_cb=ack, 
                                no_response_cb=no_ack,
                                timeout=30)
                        self.send_sms(user, msg, on_error=sms_failed)
                else:
                    if urgent and not self.sms.number_known(user):
                        msg = ("I would have sent this via SMS but I don't have "
                               "your number: {}".format(msg))
                    # Don't try SMS (we don't know the number or the ugent 
                    # isn't true) just reliably send the msg
                    self.messagehandler.send_chat(user=user, source=user, 
                                                  body=msg)

                header_msg = "<strong>Message delivered to {}</strong> <br />".format(user)

            return FORM_PAGE.format(header_msg=header_msg)
        except RemoteError as e:
            return ERROR_PAGE.format(error_string=str(e))

