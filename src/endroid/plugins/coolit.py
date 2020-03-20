# -----------------------------------------------------------------------------
# EnDroid - Cool it Plugin
# Copyright 2012, Ensoft Ltd
# -----------------------------------------------------------------------------

from endroid.plugins.command import CommandPlugin, command

class CoolIt(CommandPlugin):
    help = "I'm a robot. I'm not a refrigerator."
    hidden = True
    
    @command(synonyms=('cool it', 'freeze'), hidden=True)
    def coolit(self, msg, args):
        msg.reply(self.help)
