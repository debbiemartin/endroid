# -----------------------------------------------------------------------------
# EnDroid - SMS Plugin
# Copyright 2014, Ensoft Ltd, written by Patrick Stevens
# -----------------------------------------------------------------------------

from endroid.plugins.command import CommandPlugin, command
from endroid.database import Database
from . import smslib

import re
import os
import math
import time
import logging
from collections import defaultdict
from endroid.cron import Cron

DB_NAME = "SMS"
DB_TABLE = "SMS"
DB_LIMIT_TABLE = "SMS_LIMIT"
DB_BLOCK_TABLE = "SMS_BLOCK"

MESSAGES = {'help': "Sends an SMS to a user.",
            'user-not-found': "I don't have a number for that user."
            }

PHONE_REGEX = re.compile(r"[0-9]{11}|\+[0-9]{11}|\+[0-9]{12}|\+[0-9]{13}")
# that is, an 11-digit number, or +1 (ten-digits), or +11 (ten-digits), or
# +111 (ten-digits), to account for area codes of length 1,2,3.


class SMS(CommandPlugin):
    """Sends SMS messages to users; exposes relevant functions in Webex."""

    class UserNotFoundError(Exception):
        """When we try to get the number of a user who hasn't given Endroid a number."""

    class PersonalSMSLimitError(Exception):
        """SMS send limit reached; please wait a little to send a text."""

    class GlobalSMSLimitError(Exception):
        """Global SMS send limit reached; please wait a bit to send a text."""

    class SMSPeriodSendLimit(Exception):
        """Personal SMS send limit for this period has been reached."""

    class InvalidConfigError(Exception):
        """Something in the config file is of an invalid format"""

    class TwilioSMSLengthLimit(Exception):
        """The SMS message is longer than 1600 characters - don't bother
        sending it since Twilio won't allow it.
        """

    class InvalidJIDError(Exception):
        """Raise if JID is of an incorrect format"""

    class SMSBlock(Exception):
        """
        Raise if you try and send a message to
        someone who has blocked you from sending messages.
        """

    name = "sms"
    help = ("Send an SMS to someone. \n" 
            "'sms set number <num>' set your phone number.\n"
            "'sms whoami' find out what I think your number is.\n"
            "'sms forget me' make me forget your number.\n"
            "Aliases: setnum, getnum, delnum.\n"
            "'sms send <user> <message>' send an SMS to a user.\n"
            "'sms block <user>' prevent <user> from sending you messages.\n"
            "'sms unblock <user>' unblock a user.\n"
            "'sms blocked' display the users you have blocked.\n")
         

    dependencies = ['endroid.plugins.ratelimit']

    # to allow other plugins access to smslib's errors, we copy them to here
    SMSError = smslib.SMSError
    SMSAuthError = smslib.SMSAuthError
    SMSInvalidNumberError = smslib.SMSInvalidNumberError

    def endroid_init(self):
        # set up database, creating it if it doesn't exist
        if not all([self.vars["country_code"], self.vars["phone_number"],
                    self.vars["auth_token"], self.vars["twilio_sid"]]):
            raise ValueError("Specify country_code, phone_number, auth_token "
                             "and twilio_sid in the Endroid config file.")

        self._config = {"time_between_sms_resets" : 1, "user_bucket_capacity" : 3,
                        "user_bucket_fillrate" : 0.05, "global_bucket_capacity" : 20,
                        "global_bucket_fillrate" : 1, "period_limit" : 30}

        for key in self._config:
            user_value = self.vars.get(key, "")
            if user_value:
                # Check user_value is a number
                try:
                    a = user_value / 2
                    self._config[key] = user_value
                except TypeError:
                    logging.info("{} must be a number".format(key))

        self.ratelimit = self.get('endroid.plugins.ratelimit')
        self.user_buckets = defaultdict(lambda:
            self.ratelimit.create_bucket(
                self._config["user_bucket_capacity"],
                self._config["user_bucket_fillrate"]))
        self.global_bucket = self.ratelimit.create_bucket(
            self._config["global_bucket_capacity"],
            self._config["global_bucket_fillrate"])

        self.db = Database(DB_NAME)
        # Create a table to store user's phone numbers
        if not self.db.table_exists(DB_TABLE):
            self.db.create_table(DB_TABLE, ("user", "phone"))
        # Create a table to record the number of SMSs sent per user
        if not self.db.table_exists(DB_LIMIT_TABLE):
            self.db.create_table(DB_LIMIT_TABLE, ("user", "texts_sent_this_period"))
        # Create a table to record any users and a user wants to block
        if not self.db.table_exists(DB_BLOCK_TABLE):
            self.db.create_table(DB_BLOCK_TABLE, ("user", "users_blocked"))

        # logging file stuff
        self.log = logging.getLogger(__name__)
        logfile = os.path.expanduser(self.vars.get('logfile', '~/.endroid/sms.log'))
        self.log.info("Logging SMS activity to {}".format(logfile))
        handler = logging.FileHandler(logfile)
        formatter = logging.Formatter('%(asctime)s %(levelname)s %(message)s')
        handler.setFormatter(formatter)
        self.log.addHandler(handler)
        self.log.setLevel(logging.INFO)
        self.cron_name = "SMS_PERIOD_LIMIT"

        self.cron.register(self._sms_reset_number_sent, self.cron_name)
        if self.cron_name not in self.cron.getTimeouts():
            # Set number sent to reset at some time in the future for the first
            # time unless there is already a reset time set.
            # Convert days to seconds
            time_between = 60 * 60 * 24 * self._config["time_between_sms_resets"]
            self.cron.setTimeout(time_between, self.cron_name, None)

    def sms_add_sender(self, user):
        """
        Adds someone to the sms database so the
        number of messages sent is monitored.
        """
        try:
            self.get_number_sms_sent(user)
            logging.error("User {} already in database".format(user))
        except self.UserNotFoundError:
            self.db.insert(DB_LIMIT_TABLE,
                                 {'user': user, 'texts_sent_this_period': 0})

    def get_number_sms_sent(self, user):
        """Returns the number of SMS messages sent by a user in a period."""

        results = self.db.fetch(DB_LIMIT_TABLE, ['texts_sent_this_period'], {'user': user})
        if not results:
            raise self.UserNotFoundError
        return results[0]['texts_sent_this_period']

    @command()
    def sms_blocked(self, msg, arg):
        users_blocked = self.whos_blocked(msg.sender)
        if users_blocked:
            msg.reply("The following users are prevented from sending you "
                      "SMS messages:\n{}".format(", ".join(users_blocked)))
        else:
            msg.reply("You haven't blocked anyone at the moment.")

    @command(helphint="[{sender}]")
    def sms_block(self, msg, arg):
        """
        Blocks a JID from sending sms messages to this person.
        msg.sender: this person
        arg: JID
        """
        user = msg.sender
        user_to_block = arg.strip()

        if not user_to_block:
            msg.reply("You don't appear to have specified a user to block.")
            return

        # JID for user_to_block cannot have white space in it
        if " " in user_to_block:
            msg.reply("The user you wish to block can't have whitespace in it.")
            return

        people_blocked = self.whos_blocked(user)
        if user_to_block in people_blocked:
            msg.reply("User {} already blocked".format(user_to_block))
        else:
            people_blocked.add(user_to_block)
            self.set_blocked_users(user, people_blocked)
            msg.reply("{} has been blocked from sending SMS to "
                      "you.".format(user_to_block))

    @command(helphint="{sender}")
    def sms_unblock(self, msg, arg):
        """
        Unblocks the sender from sending SMS messages to the receiver
        """
        user = msg.sender
        user_to_unblock = arg.strip()
        if not user_to_unblock:
            msg.reply("You don't appear to have specified a user to unblock.")
            return
        people_blocked = self.whos_blocked(user)
        if user_to_unblock not in people_blocked:
            msg.reply("User {} already not blocked".format(user_to_unblock))
        else:
            people_blocked.remove(user_to_unblock)
            self.set_blocked_users(user, people_blocked)
            msg.reply("{} has been unblocked from sending SMS to "
                      "you.".format(user_to_unblock))

    def set_blocked_users(self, receiver, senders):
        """Prevent senders from being able to send SMSs to receiver."""

        senders_str = ",".join(senders)
        am_in_db = self.db.count(DB_BLOCK_TABLE, {'user' : receiver})
        if am_in_db > 0:
            self.db.update(DB_BLOCK_TABLE, 
                           {'users_blocked' : senders_str},
                           {'user' : receiver})
        else:
            # This receiver doesn't have an entry in the DB yet
            self.db.insert(DB_BLOCK_TABLE,
                           {'user' : receiver, 'users_blocked': senders_str})

    def whos_blocked(self, receiver):
        """Which users are not allowed to send SMSs to receiver."""

        results = self.db.fetch(DB_BLOCK_TABLE, ['users_blocked'], {'user': receiver})
        users_blocked = set()
        if results:
            # @@@UNICODE I don't even know where to start...
            users_blocked_str = results[0]['users_blocked'].encode('ascii')
            if users_blocked_str:
                users_blocked = set(users_blocked_str.split(","))

        return users_blocked

    def _sms_reset_number_sent(self, unused_params):
        """Resets the number of texts sent in the database."""

        self.db.empty_table(DB_LIMIT_TABLE)
        logging.info("Reset the number of SMS messages sent this period "
                     "for all users")
        self.cron.setTimeout(60 * 60 * 24 * self._config["time_between_sms_resets"],
                             self.cron_name, 
                             None)

    @command(helphint="{number}", synonyms=("setnum",))
    def sms_set_number(self, msg, arg):
        """
        Sets the stored phone number of the sender.
        """
        user = msg.sender
        number = arg

        if number[0] == '0':
            number = self.vars['country_code'] + number[1:]

        if not PHONE_REGEX.match(number):
            msg.reply("I don't recognise a number there. Use 11 digits, "
                      "no spaces, or a + followed by 11 to 13 digits. "
                      "I haven't done anything with your request.")
            return

        try:
            self.get_phone_number(user)
            self.db.update(DB_TABLE, {'phone': number}, {'user': user})
        except self.UserNotFoundError:
            self.db.insert(DB_TABLE, {'user': user, 'phone': number})

        msg.reply('Phone number for user {} set to {}.'.format(user, number))

    @command(helphint="", synonyms=("getnum", 'sms get number'))
    def sms_whoami(self, msg, arg):
        """
        Tells the user what Endroid thinks their phone number is.
        """
        user = msg.sender
        try:
            msg.reply(self.get_phone_number(user))
            return
        except self.UserNotFoundError:
            msg.reply("I don't know your number.")

    @command(helphint="", synonyms=("delnum", "sms forgetme"))
    def sms_forget_me(self, msg, arg):
        """
        Tells Endroid to clear its stored number for the sender of the message
        """
        user = msg.sender
        self.db.delete(DB_TABLE, {'user': user})
        msg.reply("I've forgotten your phone number.")

    def number_known(self, user):
        """
        Returns bool(we have a number stored for this JID user).
        :param user: JID string of user to check
        :return: True/False if we do/don't know their number.
        """
        try:
            self.get_phone_number(user)
        except self.UserNotFoundError:
            return False
        return True

    def get_phone_number(self, user):
        """
        Fetch stored number for a JID; raise UserNotFoundError if it doesn't exibzr resolvest
        :param user: the JID string of the user to search for
        :return: a string phone number
        """
        results = self.db.fetch(DB_TABLE, ['phone'], {'user': user})
        if not results:
            raise self.UserNotFoundError(user)
        return results[0]['phone']

    def send_sms(self, sender, jid, message):
        """
        Sends an SMS to the user with the specified JID.
        Returns a Deferred which acts as a string containing the server's
        response.
        Raises self.SMSError or its descendants if there is an error.
        Checks the user is allowed to send a message and they haven't gone over
        their allowed SMS messages for this time period and that there are
        enough tokens in their user bucket and the global bucket.
        :param sender: hashable object identifying the sender of the SMS
        :param jid: the user we're sending the SMS to
        :param message: the message body to send to them
        :return: output of Twilio, as a Deferred
        """
        self.log.info("Attempting send of SMS from {} to {}.".format(sender, jid))
        number_messages = math.ceil(float(len(message))/160)
        if number_messages > 10:
            raise self.TwilioSMSLengthLimit("You can only send a message which "
                                            "is less than or equal to 1600 "
                                            "characters long.  Your message is "
                                            "{} characters "
                                            "long".format(len(message)))

        try:
            number_sent = self.get_number_sms_sent(sender)
            number_sent += number_messages
        except self.UserNotFoundError:
            self.sms_add_sender(sender)
            number_sent = number_messages

        if sender not in self.whos_blocked(jid):
            if number_sent <= self._config["period_limit"]:
                if self.global_bucket.use_token():
                    if self.user_buckets[sender].use_token():
                        self.db.update(DB_LIMIT_TABLE,
                                       {"texts_sent_this_period": number_sent},
                                       {"user": sender})
                        number = self.get_phone_number(jid)
                        auth_token = self.vars['auth_token']
                        endroid_number = self.vars['phone_number']
                        sid = self.vars['twilio_sid']

                        response = smslib.send(endroid_number, number,
                                               message, sid, auth_token)
                        def log_success(resp):
                            self.log.info("{} to {} succeeded.".format(sender, jid))
                            return resp

                        def log_failure(fail):
                            self.log.info("{} to {} failed.".format(sender, jid))
                            return fail

                        response.addCallbacks(log_success, log_failure)
                        return response

                    else:
                        self.log.info("{} to {} was personally ratelimited.".format(sender, jid))
                        if number_messages == 1:
                            raise self.PersonalSMSLimitError('Personal SMS limit reached')
                        else:
                            raise self.PersonalSMSLimitError('Personal SMS limit '
                                                             'will be reached. Your '
                                                             'message will be split '
                                                             'into {} '
                                                             'messages'.format(int(number_messages)))
                else:
                    self.log.info("{} to {} was globally ratelimited.".format(sender, jid))
                    raise self.GlobalSMSLimitError('Global SMS limit reached')
            else:
                self.log.info("{} has reached their SMS limit "
                              "for the period.".format(sender))
                if self._config["period_limit"] <= self.get_number_sms_sent(sender):
                    raise self.SMSPeriodSendLimit("SMS period limit reached.")
                else:
                    raise self.SMSPeriodSendLimit("SMS period limit will be reached."
                                                  "  Your message will be split into "
                                                  "{} messages".format(int(number_messages)))
        else:
            self.log.info("{} was blocked from sending sms by "
                          "{}".format(sender, jid))
            raise self.SMSBlock("Permission denied.")

    @command(helphint="{user} {message}")
    def sms_send(self, msg, args):
        """
        Sends SMS from Endroid with given message body to specified user.
        """
        args_split = args.split(' ')

        try:
            to_user = args_split[0]
            to_send = ' '.join(args_split[1:])
        except IndexError:
            msg.reply('Call me like "sms send a@b.c Hello Patrick!"')
            return

        # error if we get an unexpected response from the server
        def errback(fail):
            if fail.check(smslib.SMSAuthError):
                msg.reply("There was a problem with authentication. Check config.")
            elif fail.check(smslib.SMSError):
                msg.reply(fail.getErrorMessage())
            else:
                msg.reply(str(fail))

        def callback(response):
            msg.reply('Message sent!')

        try:
            result_deferred = self.send_sms(msg.sender, to_user, to_send)
            result_deferred.addCallbacks(callback, errback)
        except self.UserNotFoundError:
            msg.reply(MESSAGES['user-not-found'])
        except self.GlobalSMSLimitError:
            msg.reply("Endroid has sent its limit of texts - please wait a bit.")
        except self.PersonalSMSLimitError:
            msg.reply("You have sent your limit of texts - please wait a bit.")
        except self.SMSPeriodSendLimit:
            msg.reply("You have used up your quota of texts for this period.")

