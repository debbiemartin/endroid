# -----------------------------------------------------------------------------
# EnDroid - Timer plugin
# Copyright 2014, Patrick Stevens
# -----------------------------------------------------------------------------

"""
Plugin to let the user initiate a time-alert from Endroid.

A bit contrived; intended mainly as a demo of context-awareness in plugins.
"""

from endroid.plugins.command import CommandPlugin, command


class Timer(CommandPlugin):
    """Plugin to send messages to a user, storing them if they are offline."""

    name = "timer"

    help = ("Start a timer. \n "
            "Commands: timer, which is its own help.")

    def _timer_elapsed(self, sender):
        self.messagehandler.send_chat(sender, 'Ding!')

    def _timer_cancelled(self, msg):
        if msg.body == 'cancel':
            msg.reply('You cancelled the timer.')
        else:
            msg.reply('You have higher priorities, I see. Forgetting the timer.')
            msg.unhandled()

    def _handle_first(self, msg):
        """ Callback to handle the initial input of times"""
        if msg.body == 'cancel':
            msg.reply('Aborting timer.')
        else:
            try:
                timeout = int(msg.body)
            except ValueError:
                msg.unhandled()
                msg.reply("That's not a time!")
                return

            # we'd like to use msg.reply here, but it doesn't have the
            # context callback methods.
            self.messagehandler.send_chat(msg.sender,
                                          'Type "cancel" to abort the timer.',
                                          response_cb=self._timer_cancelled,
                                          no_response_cb=self._timer_elapsed,
                                          timeout=timeout)

    def _forget_timer(self, sender):
        self.messagehandler.send_chat(sender, "You don't want a timer.")

    @command()
    def timer(self, msg, args):
        text = 'Please enter a time in seconds, or "cancel" to abort:'
        self.messagehandler.send_chat(msg.sender, text,
                                      response_cb=self._handle_first,
                                      no_response_cb=self._forget_timer,
                                      timeout=10)
