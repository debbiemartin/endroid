# -----------------------------------------
# Endroid - Webex Bot
# Copyright 2012, Ensoft Ltd.
# Created by Jonathan Millican
# -----------------------------------------

import functools
from collections import namedtuple
from endroid.pluginmanager import Plugin, PluginMeta

__all__ = (
    'CommandPlugin',
    'command',
    )

# A single registration
# - callback is the registered callback function
# - command is the original registered command (a str, or a tuple of strs)
# - helphint is any additional help hint provided at registration time
# - if hidden is True, then the command is not included in help output
# - plugin is the plugin that made the registration
Registration = namedtuple('Registration', ('callback', 'command', 'helphint',
                                           'hidden', 'plugin'))

# A set of handlers
# - handlers is a list of the Registration objects for this subcommand
# - subcommands is a dict of subcommand (simple str) to Handlers object
Handlers = namedtuple('Handlers', ('handlers', 'subcommands'))

def command(wrapped=None, synonyms=(), helphint="", hidden=False,
            chat_only=False, muc_only=False):
    """
    Decorator used to mark command functions in subclasses of CommandPlugin.

    In it's simplest form, can be used to mark a function as a command:

        >>> class Foo(CommandPlugin):
        ...     @command
        ...     def foo_bar(self, msg, args):
        ...         do_stuff_here()

    This will register the command string ("foo", "bar") with the Command plugin
    when the Foo plugin is initialised.

    The decorator also takes a series of optional keyword arguments to control
    the behaviour of the registration:

        synonyms: sequence of synonyms (either strings, or sequences of strings)
        helphint: a helpful hint to display in help for the command
        hidden: whether the command is hidden in the help
        chat_only: set to True if the command should only be registered in chat
        muc_only: set to True if the command should only be registered in muc

    """
    def decorator(fn):
        fn.is_command = True
        fn.synonyms = synonyms
        fn.helphint = helphint
        fn.hidden = hidden
        fn.chat_only = chat_only
        fn.muc_only = muc_only
        return fn
    if wrapped is None:
        return decorator
    else:
        return decorator(wrapped)


class _Topics(object):
    """
    Descriptor to handle auto-updating of the help_topics.

    This is required if a plugin doesn't just define its help_topics at the
    class level, and instead sets it during its initialisation. This descriptor
    will update the help_topics instead of replacing them when set.
    """
    def __get__(self, obj, type=None):
        """
        As well as fetching the help_topics (from the _help_topics field), this
        also injects the 'commands' entry into topics. It is done here, as this
        is the first point at which we have an instance of the plugin (needed
        to do the filtering later when displaying the help).

        Moral of the story: injecting methods is awkward.
        """
        def _commands_help(topic):
            com = obj.get('endroid.plugins.command')
            return com._help_main(topic, plugin=obj)
        if not 'commands' in obj._help_topics:
            # This will call the __set__, below
            setattr(obj, 'help_topics', {'commands': _commands_help})
        return obj._help_topics

    def __set__(self, obj, value):
        """
        Takes a copy of the existing topics, updates the dict with the given
        value, then sets it on the instance.

        Note that if someone attempts to set them on the class after class
        creation, this will raise an exception. Which seems the sanest thing to
        do, as updating the class topics after the fact is an odd thing to do.
        """
        # We need to take a copy in case these are the class topics
        topics = obj._help_topics.copy()
        topics.update(value)
        obj._help_topics = topics

# We only ever need one instance of this class
_Topics = _Topics()


class CommandPluginMeta(PluginMeta):
    """
    Metaclass to support simple command-driven plugins. This should not be used
    directly, but rather by subclassing from CommandPlugin rather than Plugin.
    """
    def __new__(meta, name, bases, dct):
        # We can also always add a default name here, so command can always
        # assume there is one.
        if 'name' not in dct:
            dct['name'] = name.lower()

        cmds = dict((c, f) for c, f in dct.items()
                    if c.startswith("cmd_") or getattr(f, "is_command", False))
        init = dct.get('endroid_init', lambda _: None)
        # Make sure the new init function looks like the old one
        @functools.wraps(init)
        def endroid_init(self):
            com = self.get('endroid.plugins.command')
            for cmd, fn in cmds.items():
                if getattr(fn, "chat_only", False):
                    reg_fn = com.register_chat
                elif getattr(fn, "muc_only", False):
                    reg_fn = com.register_muc
                else:
                    reg_fn = com.register_both
                words = cmd.split("_")
                # Handle a leading underscore (may be necessary in some cases)
                if not words[0]:
                    words = words[1:]
                if not getattr(fn, "is_command", False):
                    words = words[1:]
                reg_fn(getattr(self, cmd), words,
                       helphint=getattr(fn, "helphint", ""),
                       hidden=getattr(fn, "hidden", False),
                       synonyms=getattr(fn, "synonyms", ()),
                       plugin=self)
            init(self)
        dct['endroid_init'] = endroid_init

        # We replace any class topics with the Descriptor, and always set at
        # least an empty dict in the private _help_topics field
        topics = dct.get('help_topics', {})
        dct['_help_topics'] = topics
        dct['help_topics'] = _Topics

        dct['dependencies'] = (tuple(dct.get('dependencies', ())) +
                               ('endroid.plugins.command',))
        return super(CommandPluginMeta, meta).__new__(meta, name, bases, dct)

class CommandPlugin(Plugin):
    """
    Parent class for simple command-driven plugins. Such plugins don't need to
    explicitly register their commands. Instead, they can just define methods
    prefixed with "cmd_" or decorated with the 'command' decorator, and they
    will automatically be registered. Any additional underscores in the method
    name will be converted to spaces in the registration (so cmd_foo_bar is
    registered as ('foo', 'bar')).

    In addition, certain options can be passed by adding fields to the methods,
    or as keyword arguments to the decorator:

    - hidden: don't show the command in help if set to True.
    - synonyms: an iterable of alternative keyword sequences to register the
        method against. All synonyms are hidden.
    - helphint: a hint to print after the keywords in help output.
    - muc_only or chat_only: register for only chat or muc messages (default is
        both).
    """
    __metaclass__ = CommandPluginMeta

class Command(Plugin):
    """
    Helper plugin to handle command registrations by other plugins. This is
    the main avenue by which plugins are expected to handle incoming messages
    and it is expected most plugins will depend on this.
    """
    name = "commands"
    hidden = True # This plugin is built in to the help module

    def endroid_init(self):
        self._muc_handlers = Handlers([], {})
        self._chat_handlers = Handlers([], {})
        self.messages.register(self._command_muc, muc_only=True)
        self.messages.register(self._command_chat, chat_only=True)

        self.help_topics = {
            '': self._help_main,
            'chat': self._help_chat,
            'muc': self._help_muc,
            }

    # -------------------------------------------------------------------------
    # Help methods

    def _help_add_regs(self, output, handlers, plugin=None):
        """
        Add lines of help strings to the output list for each handler in the
        given Handlers object. Then recurses down all subcommands to get their
        help strings too.
        """
        for reg in handlers.handlers:
            if not reg.hidden and (plugin is None or plugin is reg.plugin):
                output.append("  %s %s" % (reg.command, reg.helphint))
        for _, hdlrs in sorted(handlers.subcommands.items()):
            self._help_add_regs(output, hdlrs, plugin)

    def _help_main(self, topic, plugin=None):
        assert not topic
        out = ["Commands known to {}:"
               .format("me" if plugin is None else plugin.name)]
        chat = self._help_chat(topic, plugin=plugin)
        if chat:
            out.extend(["", chat])
        muc = self._help_muc(topic, plugin=plugin)
        if muc:
            out.extend(["", muc])
        return "\n".join(out)

    def _help_chat(self, topic, plugin=None):
        parts = []
        self._help_add_regs(parts, self._chat_handlers, plugin=plugin)
        if parts:
            return "\n".join(["Commands in Chat:"] + parts)
        else:
            return "No command registered in chat."

    def _help_muc(self, topic, plugin=None):
        parts = []
        self._help_add_regs(parts, self._muc_handlers, plugin=plugin)
        if parts:
            return "\n".join(["Commands in MUC:"] + parts)
        else:
            return "No commands registed in MUC."

    # -------------------------------------------------------------------------
    # Command handling methods

    def _command(self, handlers, args, msg):
        """
        Handle an incoming message using the given handlers; args is the
        current remaining message string; msg is the full Message object.

        All handlers for the current command are called after first recursing
        down to any subcommands that match.
        """
        com, arg = self._command_split(args)
        if com in handlers.subcommands:
            msg.inc_handlers()
            self._command(handlers.subcommands[com], arg, msg)
        for handler in handlers.handlers:
            msg.inc_handlers()
            handler.callback(msg, args)
        msg.dec_handlers()
    
    def _command_muc(self, msg):
        # Some clients seem to send an empty message when joining a chat room
        # - Ignore it
        if msg.body is not None:
            self._command(self._muc_handlers, msg.body, msg)

    def _command_chat(self, msg):
        self._command(self._chat_handlers, msg.body, msg)
    
    def _command_split(self, text):
        num = text.count(' ')
        if num == 0:
            return (text.lower(), '')
        else:
            com, arg = text.split(' ', 1)
            return (com.lower(), arg)

    # -------------------------------------------------------------------------
    # Registration methods

    def _register_handler(self, callback, cmd, helphint, hidden, handlers,
                          synonyms=(), plugin=None):
        """
        Register a new handler.

        callback is the callback handle to call.
        command is either a single keyword, or a sequence of keywords to match.
        helphint and hidden are arguments to the Registration object.
        handlers are the top-level handlers to add the registration to.
        plugin is the plugin that made the registration, used to provide
        automatic 'commands' help for the plugin.
        """
        # Register any synonyms (done before we frig with the handlers)
        for entry in synonyms:
            self._register_handler(callback, entry, helphint, True, handlers,
                                   plugin=plugin)

        # Allow simple commands to be passed as strings
        cmd = cmd.split() if isinstance(cmd, (str, unicode)) else cmd

        for part in cmd:
            handlers = handlers.subcommands.setdefault(part, Handlers([], {}))
        handlers.handlers.append(Registration(callback, " ".join(cmd),
                                              helphint, hidden, plugin))

    def register_muc(self, callback, command, helphint="", hidden=False,
                     synonyms=(), plugin=None):
        """Register a new handler for MUC messages."""
        self._register_handler(callback, command, helphint, hidden,
                               self._muc_handlers, synonyms, plugin)
    
    def register_chat(self, callback, command, helphint="", hidden=False,
                      synonyms=(), plugin=None):
        """Register a new handler for chat messages."""
        self._register_handler(callback, command, helphint, hidden,
                               self._chat_handlers, synonyms, plugin)

    def register_both(self, callback, command, helphint="", hidden=False,
                      synonyms=(), plugin=None):
        """Register a handler for both MUC and chat messages."""
        self.register_muc(callback, command, helphint, hidden, synonyms,
                          plugin)
        self.register_chat(callback, command, helphint, hidden, synonyms,
                           plugin)
