# -----------------------------------------------------------------------------
# EnDroid - Help Plugin
# Copyright 2012, Ensoft Ltd
# -----------------------------------------------------------------------------

import functools
from endroid.plugins.command import CommandPlugin, command

class Help(CommandPlugin):
    name = "help"

    def endroid_init(self):
        self.help_topics = {
            '': self.show_help_main,
            'plugins': self.show_help_plugins,
            'commands': self.show_help_commands,
            'help': lambda _: "DON'T PANIC!",
            '*': lambda t: self.show_help_plugin(*t.strip().split(' ', 1)),
            }

        self.load_plugin_list()

    def load_plugin_list(self):
        """
        Loads all plugins and stores a short name to plugin mapping. It also
        updates the plugins to simplify later calls to get the help.

        Currently this means handling a help method or string, and updating
        (or creating, as necessary) the help_topics with a '*' entry. This
        means it's possible to just handle help_topics later when help is
        requested.
        """

        def help_helper(self, name, topic):
            out = []
            try:
                out.append(self.help(topic))
            except TypeError:
                if topic:
                    out.append("(Plugin {} doesn't support topic-based help)"
                               .format(name))
                if callable(self.help):
                    out.append(self.help())
                else:
                    out.append(str(self.help))
            return "\n".join(out)

        self._plugins = {}
        for fullname in self.plugins.all():
            plugin = self.plugins.get(fullname)
            name = getattr(plugin, "name", fullname)
            self._plugins[name] = (fullname, plugin)

            # Do a little jiggery pokery to simplify any requests for help
            # Put a "help" method or string in as a '*' topic handler (unless)
            # there is already a '*' handler). If there's neither a help method
            # nor help_topics dictionary, then it is just left alone.
            topics = getattr(plugin, "help_topics", {})

            if not '*' in topics and hasattr(plugin, "help"):
                topics['*'] = functools.partial(help_helper, plugin, name)

            if topics:
                plugin.help_topics = topics

    @command
    def _help(self, msg, args):
        msg.reply_to_sender(self.show_help_plugin("help", args))

    def show_help_main(self, topic):
        assert not topic
        out = []
        out.append("EnDroid at your service! Help topics:")
        out.append("  plugins - list loaded plugins")
        out.append("  commands - list supported commands")
        out.append("  <pluginname> - help provided by the given plugin")
        return "\n".join(out)

    def show_help_plugins(self, topic):
        if topic.strip():
            # specific plugin?
            return self.help_topics['*'](topic)
        else:
            out = []
            out.append("Currently loaded plugins:")
            for name, (_, plug) in sorted(self._plugins.items()):
                if not getattr(plug, "hidden", False):
                    out.append("  {0}".format(name))
            return "\n".join(out)

    def show_help_commands(self, topic):
        return self.show_help_plugin("commands", topic)

    def show_help_plugin(self, name, topic=''):
        out = []
        fullname, plugin = self._plugins.get(name, (name, None))
        if self.plugins.loaded(fullname):
            # First check for help_topics
            if hasattr(plugin, "help_topics"):
                # Check if it is a "help_topics" dictionary, mapping topic
                # (first keyword) to handler function
                keywords = topic.strip().split(' ', 1)
                topic, extra = keywords[0], ''.join(keywords[1:])

                if topic in plugin.help_topics:
                    out.append(plugin.help_topics[topic](extra))
                elif '*' in plugin.help_topics:
                    out.append(plugin.help_topics['*'](' '.join(keywords)))
                else:
                    out.append("Unknown topic '{}' for plugin {}".format(topic,
                                                                         name))

            else:
                out.append("Plugin '{}' provides no help".format(name))
        else:
            out.append("Plugin '{}' is not loaded".format(name))

        return '\n'.join(out)
