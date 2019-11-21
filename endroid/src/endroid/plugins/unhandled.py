# -----------------------------------------------------------------------------
# EnDroid - Plugin to respond to unhandled messages
# Copyright 2012, Ensoft Ltd
# -----------------------------------------------------------------------------

from datetime import date
import random
from endroid.pluginmanager import Plugin

class UnHandled(Plugin):
    name = "unhandled"
    help = "I'm a personality prototype. You can tell, can't you...?"
    hidden = True

    _messages = [
        "404 Error: message not found",
        "Command not found, perhaps it can be found in the bottom of a locked "
        "filing cabinet stuck in a disused lavatory with a sign on the door "
        "saying Beware of the Leopard?",
        "Command not found. Don't Panic!",
        "I'm afraid I lost my Babel fish, please translate command into "
        "EnDroid.",
        "As you will no doubt be aware, the plans for development of the "
        "outlying regions of the Galaxy require the building of a "
        "hyperspatial express route through my code for that command.",
        "I seem to be having this tremendous difficulty with my lifestyle. As "
        "soon as I reach some kind of definite policy about what is my kind "
        "of music and my kind of restaurant and my kind of overdraft, people "
        "start blowing up my kind of planet, throwing me out of their kind of "
        "spaceships, and entering unrecognized commands!",
        "I'm afraid I won't execute that command without an order, signed in "
        "triplicate, sent in, sent back, queried, lost, found, subjected to "
        "public enquiry, lost again, and finally buried in soft peat for "
        "three months and recycled as firelighters.",
        ]

    def endroid_init(self):
        self.register_unhandled_chat_callback(self.unhandled)
        self.register_unhandled_muc_callback(self.unhandled)

    def unhandled(self, msg):
        messages = self._messages
        if date.weekday(date.today()) == 3:
            messages = messages[:] + ["This must be a Thursday, I could never "
                                      "get the hang of Thursdays"]
        msg.reply(random.choice(messages))
