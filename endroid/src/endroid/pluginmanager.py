# -----------------------------------------
# Endroid - XMPP Bot
# Copyright 2012, Ensoft Ltd.
# Created by Jonathan Millican
# -----------------------------------------

import sys
import logging
import functools

from endroid.cron import Cron
from endroid.database import Database

def deprecated(fn):
    return fn

msg_filter_doc = ("Register a {0} filter for {1} messages.\n"
    "Filter takes endroid.messagehandler.Message and returns bool. If its\n"
    "return value evaluates to False, the message is dropped.\n"
    "Priority specifies the order of calling - lower numbers = called earlier.\n")

msg_send_doc = ("Send a {0} message to {1}, with given text and priority.\n"
    "rjid is a string representing the JID of the room to send to.\n"
    "text is a string (or unicode) of the message contents.\n"
    "priority one of the PRIORITY_* constants from endroid.messagehandler.\n"
    "(Use with care, especially PRIORITY_URGENT, which will usually bypass any\n"
    "ratelimiting or other protections put in place.)")

msg_cb_doc = ("Register a callback for {0} messages.\n"
    "Callback takes endroid.messagehandler.Message and may alter it arbitrarily.\n"
    "Inc_self specifies whether to do the callback if EnDroid created the message.\n"
    "Priority specifies the order of calling - lower numbers = called earlier.\n")


class PluginMeta(type):
    """
    Metaclass for Plugins that automatically registers any Plugin subclasses
    against their module name. This allows the PluginManager to automatically
    find the right class (meaning plugins don't need to register themselves,
    nor provide some well-known function like 'get_plugin').

    The registration key being the module is consistent with the expectation
    that the plugin name in the config file is a python module.

    This metaclass also ensures the Plugin has certain fields, and converts
    them to properties if required.
    """
    registry = {}

    def __new__(meta, name, bases, dict):
        if 'name' not in dict:
            dict['name'] = name.lower()
        for prop in ('dependencies', 'preferences'):
            if callable(dict.get(prop, None)):
                dict[prop] = property(dict[prop])

        # For backwards compatibility
        if 'enInit' in dict:
            dict['endroid_init'] = dict['enInit']
            del dict['enInit']

        # Support for the Cron @task decorator
        crons = {name: fn for name, fn in dict.items()
                 if getattr(fn, "_cron_iscb", False)}
        init = dict.get('endroid_init', lambda _: None)
        # Make sure the new init function looks like the old one
        @functools.wraps(init)
        def endroid_init(self):
            for name, fn in crons.items():
                @functools.wraps(fn)
                def inner(*args, **kwargs):
                    # This function is here to ensure the right obj is passed
                    # as self to the method.
                    return fn(self, *args, **kwargs)
                task = self.cron.register(inner, fn._cron_name,
                                          persistent=fn._cron_persistent)
                setattr(self, name, task)
            init(self)
        dict['endroid_init'] = endroid_init

        return type.__new__(meta, name, bases, dict)

    def __init__(cls, name, bases, dict):
        type.__init__(cls, name, bases, dict)
        cls.modname = cls.__module__
        PluginMeta.registry[cls.__module__] = cls


class Plugin(object):
    """
    Parent class of all plugin objects within EnDroid. Plugins must subclass
    this type and it also represents the entry point for the plugin into the
    rest of EnDroid.

    """
    __metaclass__ = PluginMeta

    def _setup(self, pm, conf):
        self._pm = pm

        self.messagehandler = pm.messagehandler
        self.usermanagement = pm.usermanagement

        self.plugins = pm
        self.messages = pm.messagehandler.for_plugin(pm, self)
        self.rosters = pm.usermanagement.for_plugin(pm, self)

        self._database = None

        self.place = pm.place
        self.place_name = pm.name
        self.vars = conf

    @property
    def database(self):
        if self._database is None:
            self._database = Database(self.name) # Should use place too
        return self._database

    def _register(self, *args, **kwargs):
        return self.messagehandler._register_callback(self._pm.name, *args, **kwargs)

    # Message Registration methods
    @deprecated
    def register_muc_callback(self, callback, inc_self=False, priority=0):
        if self._pm.place != "room":
            return
        self._register("muc", "recv", callback, inc_self, priority)

    @deprecated
    def register_chat_callback(self, callback, inc_self=False, priority=0):
        if self._pm.place != "group":
            return
        self._register("chat", "recv", callback, inc_self, priority)

    @deprecated
    def register_unhandled_muc_callback(self, callback, inc_self=False, priority=0):
        if self._pm.place != "room":
            return
        self._register("muc", "unhandled", callback, inc_self, priority)

    @deprecated
    def register_unhandled_chat_callback(self, callback, inc_self=False, priority=0):
        if self._pm.place != "group":
            return
        self._register("chat", "unhandled", callback, inc_self, priority)

    register_muc_callback.__doc__ = msg_cb_doc.format("muc")
    register_chat_callback.__doc__ = msg_cb_doc.format("chat")
    register_unhandled_muc_callback.__doc__ = msg_cb_doc.format("unhandled muc")
    register_unhandled_chat_callback.__doc__ = msg_cb_doc.format("unhandled chat")

    @deprecated
    def register_muc_filter(self, callback, inc_self=False, priority=0):
        if self._pm.place != "room":
            return
        self._register("muc", "recv_filter", callback, inc_self, priority)

    @deprecated
    def register_chat_filter(self, callback, inc_self=False, priority=0):
        if self._pm.place != "group":
            return
        self._register("chat", "recv_filter", callback, inc_self, priority)

    @deprecated
    def register_muc_send_filter(self, callback, inc_self=False, priority=0):
        if self._pm.place != "room":
            return
        self._register("muc", "send_filter", callback, inc_self, priority)

    @deprecated
    def register_chat_send_filter(self, callback, inc_self=False, priority=0):
        if self._pm.place != "group":
            return
        self._register("chat", "send_filter", callback, inc_self, priority)

    register_muc_filter.__doc__ = msg_filter_doc.format("receive", "muc")
    register_chat_filter.__doc__ = msg_filter_doc.format("receive", "chat")
    register_muc_send_filter.__doc__ = msg_filter_doc.format("send", "muc")
    register_chat_send_filter.__doc__ = msg_filter_doc.format("send", "chat")

    # Plugin access methods
    @deprecated
    def get(self, plugin_name):
        """Return a plugin-like object from the plugin module plugin_name."""
        return self.plugins.get(plugin_name)

    def get_dependencies(self):
        """
        Return an iterable of plugins this plugin depends on.

        This includes indirect dependencies i.e. the dependencies of plugins this
        plugin depends on and so on.

        """
        return (self.get(dependency) for dependency in self.dependencies)

    def get_preferences(self):
        """
        Return an iterable of plugins this plugin prefers.

        This includes indirect preferences i.e. the preferences of plugins this
        plugin prefers and so on.

        """
        return (self.get(preference) for preference in self.preferences)

    @deprecated
    def list_plugins(self):
        """Return a list of all plugins loaded in the plugin's environment."""
        return self.plugins.all()

    @deprecated
    def pluginLoaded(self, modname):
        """Check if modname is loaded in the plugin's environment (bool)."""
        return self.plugins.loaded(modname)

    @deprecated
    def pluginCall(self, modname, func, *args, **kwargs):
        """Directly call a method on plugin modname."""
        return getattr(self.get(modname), func)(*args, **kwargs)

    # Overridable values/properties
    def endroid_init(self):
        pass

    @property
    def cron(self):
        return Cron().get()
    
    dependencies = ()
    preferences = ()


class GlobalPlugin(Plugin):
    def _setup(self, pm, conf):
        super(GlobalPlugin, self)._setup(pm, conf)
        self.messages = pm.messagehandler
        self.rosters = pm.usermanagement


class PluginProxy(object):
    def __init__(self, modname):
        self.name = modname

    def __getattr__(self, key):
        return self.__dict__.get(key, self)

    def __getitem__(self, idx):
        return self

    def __call__(self, *args, **kwargs):
        return self

    def __nonzero__(self):
        return False


class ModuleNotLoadedError(Exception):
    def __init__(self, value):
        super(ModuleNotLoadedError, self).__init__(value)
        self.value = value

    def __str__(self):
        return repr(self.value)


class PluginInitError(Exception):
    pass


class PluginManager(object):
    def __init__(self, messagehandler, usermanagement, place, name, config):
        self.messagehandler = messagehandler
        self.usermanagement = usermanagement

        self.place = place # For global, needs to be made to work with config
        self.name = name or "*"

        # this is a dictionary of plugin module names to plugin objects
        self._loaded = {}
        # a dict of modnames : plugin configs (unused?)
        self._plugin_cfg = {}
        # module name to bool dictionary (use set instead?)
        self._initialised = set()

        self._read_config(config)
        self._load_plugins()
        self._init_plugins()

    def _read_config(self, conf):
        def get_data(modname):
            # return a tuple of (modname, modname's config)
            return modname, conf.get(self.place, self.name, "plugin", modname, default={})

        plugins = conf.get(self.place, self.name, "plugins")
        logging.debug("Found the following plugins in {}/{}: {}".format(
                      self.place, self.name, ", ".join(plugins)))
        self._plugin_cfg = dict(map(get_data, plugins))

    def _load(self, modname):
        # loads the plugin module and adds a key to self._loaded
        logging.debug("\tLoading Plugin: " + modname)
        try:
            __import__(modname)
        except ImportError as i:
            logging.error(i)
            logging.error("**Could not import plugin \"" + modname
                          + "\". Check that it exists in your PYTHONPATH.")
            return
        except Exception as e:
            logging.exception(e)
            logging.error("**Failed to import plugin {}".format(modname))
            return
        else:
            # dictionary mapping module names to module objects
            m = sys.modules[modname]

        try:
            # In loading a plugin, we first look for a get_plugin() function,
            # then check the automatic Plugin registry for a Plugin defined in
            # that module.
            if hasattr(m, 'get_plugin'):
                plugin = getattr(m, 'get_plugin')()
            else:
                plugin = PluginMeta.registry[modname]()
        except Exception as k:
            logging.exception(k)
            logging.error("**Could not import plugin {}. Module doesn't seem to"
                          "define a Plugin".format(modname))
            return
        else:
            plugin._setup(self, self._plugin_cfg[modname])
            self._loaded[modname] = plugin

    def _load_plugins(self):
        logging.info("Loading Plugins for {0}".format(self.name))
        for p in self._plugin_cfg:
            self._load(p)

    def _init_one(self, modname):
        if modname in self._initialised:
            logging.debug("\t{0} Already Initialised".format(modname))
            return True
        if not self.loaded(modname):
            logging.error("\t**Cannot Initialise Plugin \"" + modname + "\", "
                          "It Has Not Been Imported")
            return False
        if modname in self._initialising:
            logging.error("\t**Circular dependency detected. Initialising: {}"
                          .format(", ".join(sorted(self._initialising))))
            return False
        logging.debug("\tInitialising Plugin: " + modname)

        # deal with dependencies and preferences
        # Dependencies are mandatory, so they must be loaded;
        # Preferences are optional, so are replaced with a PluginProxy if not
        # loaded. In both cases, all mentioned plugins are initialised to
        # make sure they are ready before this plugin starts to load them.
        
        # Circular dependencies cause failures, while circular preferences are
        # temporarily replaced with a Proxy to break the cycle, then replaced
        # later (which means that during the init phase, they will not have
        # been available so might not be correctly used).
        self._initialising.add(modname)

        try:
            plugin = self.get(modname)
            for mod_dep_name in plugin.dependencies:
                logging.debug("\t{} depends on {}".format(modname,
                                                          mod_dep_name))
                if not self._init_one(mod_dep_name):
                    # can't possibly initialise us so remove us from self._loaded
                    logging.error('\t**No "{}". Unloading {}.'
                                  .format(mod_dep_name, modname))
                    self._loaded.pop(modname)
                    return False

            for mod_pref_name in plugin.preferences:
                logging.debug("\t{} Prefers {}".format(modname, mod_pref_name))
                if mod_pref_name in self._initialising:
                    logging.warning("\tDetected circular preference for {}. "
                                    "Continuing with proxy object in place"
                                    .format(mod_pref_name))
                    self._loaded[mod_pref_name] = PluginProxy(mod_pref_name)

                elif not self._init_one(mod_pref_name):
                    logging.error("\t**Could Not Load {} required by {}".format(
                                  mod_pref_name, modname))
                    # Create a proxy object instead
                    self._loaded[mod_pref_name] = PluginProxy(mod_pref_name)

            # attempt to initialise the plugin
            try:
                plugin.endroid_init()
                self._initialised.add(modname)
                logging.info("\tInitialised Plugin: " + modname)
                # Re-add this plugin to _loaded, in case it was temporarily
                # replaced by a proxy
                self._loaded[modname] = plugin
            except Exception as e:
                logging.exception(e)
                logging.error('\t**Error initializing "{}".  See log for '
                              'details.'.format(modname))
                return False
            return True
        finally:
            self._initialising.discard(modname)

    def _init_plugins(self):
        logging.info("Initialising Plugins for {0}".format(self.name))
        # Track what we're doing to detect circular dependencies
        self._initialising = set()
        for p in self.all():
            self._init_one(p)
        del self._initialising

        logging.info("Plugins initialised.")

    # =========================================================================
    # Public API for plugins
    #

    def all(self):
        """
        Return an Iterator of the names of all plugins loaded in this place.

        Note that this does not include PluginProxy objects.
        """
        return [k for k, obj in self._loaded.items() if not isinstance(obj, PluginProxy)]

    get_plugins = all

    def loaded(self, name):
        """Returns True if the named plugin is loaded in this place."""
        return name in self._loaded
    hasLoaded = loaded

    def get(self, name):
        """
        Gets the instance of the named plugin within this place.

        Raises a ModuleNotLoadedError if the plugin is not loaded.
        """
        if not name in self._loaded:
            raise ModuleNotLoadedError(name)
        return self._loaded[name]
