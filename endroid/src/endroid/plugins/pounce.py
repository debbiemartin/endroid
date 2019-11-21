# -----------------------------------------------------------------------------
# Endroid - XMPP Bot - Pounce user presence plugin
# Copyright 2014, Ensoft Ltd.
# Created by Patrick Stevens
# -----------------------------------------------------------------------------

"""Sample plugin to demonstrate use of UserManagement.register_presence_callback"""

from endroid.plugins.command import CommandPlugin, command

class Pounce(CommandPlugin):
    name = "pounce"
    help = ("Pounces on a user by sending them a message immediately when they"
            " come online. \n"
            "Use 'pounce <user> [<message>]' to be told when user comes online "
            "and optionally send them message when they do, \n"
            "or 'stalk <user>' to be notified when a user goes offline.")

    
    @command(helphint='{user} [{message}]')
    def pounce(self, msg, args):
        reply = None
        args = args.strip()
        if args:
            arg_tokens = args.split(' ') 
            target = arg_tokens.pop(0)
            message = " ".join(arg_tokens)
            if message:
                message = "{} says: {}".format(msg.sender, message)
        else:
            reply = "Doesn't look like you've told me who to pounce"

        if not reply and target not in self.rosters.users:
            reply = "I don't know the user {}.".format(target)

        if not reply and self.rosters.is_online(target):
            if message:
                # Send them the message now
                self.messages.send_chat(target, message, msg.sender)
                reply = target + " was already online, so I just told them direct."
            else:
                reply = target + " is already online."

        if not reply:
            if message:
                # When the target comes online send them message and the
                # requestor the pounce_message
                pounce_message = target + ' came online - message sent'
                reply = ("I'll let you know when {} comes online and send "
                         "them the message.".format(target))
            else:
                pounce_message = target + ' came online.'
                reply = "I'll let you know when {} comes online.".format(target)

            def cb():
                self.messages.send_chat(msg.sender, pounce_message)
                if message:
                    self.messages.send_chat(target, message)

            self.rosters.register_presence_callback(user=target, callback=cb,
                                                    available=True)

        msg.reply(reply)

    @command(helphint="{user}")
    def stalk(self, msg, args):
        cb = lambda: self.messages.send_chat(msg.sender,
                                             'User {} is offline'.format(args))
        self.rosters.register_presence_callback(user=args, callback=cb,
                                                unavailable=True)

        msg.reply("You will be notified when user {} goes offline.".format(args))
