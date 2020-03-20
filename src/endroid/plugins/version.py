# -----------------------------------------
# Endroid - Provide access to EnDroid's version info
# Copyright 2014, Ensoft Ltd.
# Created by Chris Davidson
# -----------------------------------------

import endroid

from endroid.plugins.command import CommandPlugin, command


class Version(CommandPlugin):

    def endroid_init(self):
        self.version_info = None
        try:
            import endroid.version_info
            self.version_info = endroid.version_info.version_info
        except ImportError:
            # No version info
            pass

    def help(self):
        return "Display details of EnDroid's version."

    @command()
    def version(self, msg, args):
        reply = "I'm running Endroid verson {}.".format(endroid.__version__)
        if self.version_info is not None:
            reply += (" More specifically revno {revno} commited on "
                      "{date} and built on {build_date} (rev "
                      "{revision_id})".format(**self.version_info))
        msg.reply(reply)
