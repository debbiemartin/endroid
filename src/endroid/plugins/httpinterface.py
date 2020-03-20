# -----------------------------------------------------------------------------
# EnDroid - HTTP Interface
# Copyright 2012, Ensoft Ltd
# -----------------------------------------------------------------------------

import collections
import re
import logging
import jinja2
import time

from endroid.pluginmanager import Plugin
from twisted.internet import reactor
from twisted.web.resource import Resource, IResource
from twisted.web.server import Site
from twisted.web.static import File
from twisted.web.guard import HTTPAuthSessionWrapper, BasicCredentialFactory
from twisted.cred.portal import IRealm, Portal
from twisted.cred.checkers import InMemoryUsernamePasswordDatabaseDontUse


DEFAULT_HTTP_PORT = 8880
DEFAULT_HTTP_INTERFACE = '127.0.0.1'
DEFAULT_MEDIA_DIR = "/usr/share/endroid/media/"
DEFAULT_TEMPL_DIR = "/usr/share/endroid/templates/"

class HandlerNotFoundError(Exception):
    pass

class EnDroidRealm(object):
    """
    Twisted Realm for authenticated resources. Quite simply, it's a wrapper
    around a single resource (all users get the same resource).
    """
    def __init__(self, resource):
        self._resource = resource

    def requestAvatar(self, avatarId, mind, *interfaces):
        if IResource in interfaces:
            return (IResource, self._resource, lambda: None)
        raise NotImplementedError()


class IndexPage(Resource):
    """
    This is the root page resource.

    All other resources hang off this one. There is one Resource for each
    plugin that has at least one registration. Either that will be a custom
    Resource (defined in the plugin itself), or an instance of RegexResource,
    defined below.

    This Resource just shows a list of known plugins for now.
    """
    
    def __init__(self, interface):
        Resource.__init__(self)
        self.interface = interface
        self.putChild('', self)

    def _render(self, request):
        return self.interface.jinja.get_template(
                                         "httpinterface/index.html").render({
            "plugins": sorted(self.interface._plugins),
        }).encode("utf-8")

    render_GET = _render
    render_POST = _render


class RegexResource(Resource):
    """
    Plugins that take advantage of the regex registrations get one of these.

    Contains a list of regexs -> callback mappings, in order of registrations
    (hence stored in a list of tuples, and not a dict). Flat registrations
    (i.e. not regexs) are converted into regexs before being added to the
    list.
    """

    isLeaf = True
    def __init__(self, singleton):
        Resource.__init__(self)
        self._singleton = singleton
        self.registrations = []

    def lookup_handler(self, sub_path):
        for regex, cb in self.registrations:
            if regex.match(sub_path):
                callback = cb
                break
        else:
            raise HandlerNotFoundError("Plugin {} is not registered on {}"
                                       .format(plugin_name, sub_path))

        return callback

    def _render(self, request):
        try:
            callback = self.lookup_handler(request.path)
        except HandlerNotFoundError as e:
            page = self._singleton.jinja.get_template(
                                    "httpinterface/notfound.html").render({
                "message": str(e),
            }).encode('utf-8')
        else:
            page = callback(request)
            
        return page

    render_GET = _render
    render_POST = _render


class AuthedRegexResource(HTTPAuthSessionWrapper):
    """
    Wrapper Resource for a RegexResource.

    One of these is used whenever a plugin using the simplified register_*path
    APIs requests authentication support.
    """
    def __init__(self, resource, creds):
        self._resource = resource
        HTTPAuthSessionWrapper.__init__(self,
                                        Portal(EnDroidRealm(self._resource),
                                               creds),
                                        [BasicCredentialFactory("EnDroid")])
        self.registrations = self._resource.registrations


class HTTPInterfaceSingleton(object):
    """
    Start a webserver, allow callback registrations on URL paths, and route
    requests to callbacks.
    """

    def __init__(self):
        self._plugins = collections.defaultdict(lambda: RegexResource(self))
        self._root = None

    def register_regex_path(self, plugin, callback, path_regex,
                            require_auth=False):
        """
        See HTTPInterface.register_regex_path()
        """
        if isinstance(path_regex, str):
            path_regex = re.compile(path_regex)

        if require_auth and plugin.name not in self._plugins:
            self._plugins[plugin.name] = AuthedRegexResource(
                                                 self._plugins[plugin.name],
                                                 self._creds)

        self._plugins[plugin.name].registrations.append((path_regex, callback))
        self._root.putChild(plugin.name, self._plugins[plugin.name])

    def register_path(self, plugin, callback, path_prefix='',
                      require_auth=False):
        """
        See HTTPInterface.register_path()
        """
        if not path_prefix:
            re_src = r".*"
        else:
            if path_prefix[0] == '/':
                raise ValueError("Prefix %s begins with a slash" % path_prefix)
            if path_prefix[-1] == '/':
                raise ValueError("Prefix %s ends with a slash" % path_prefix)
            re_src = re.escape(path_prefix) + r"(/.*)?"
        self.register_regex_path(plugin, callback, re_src,
                                 require_auth=require_auth)

    def register_resource(self, plugin, resource, require_auth=False):
        """
        See HTTPInterface.register_resource()
        """
        if require_auth:
            self._plugins[plugin.name] = self.authed_resource(resource)
        else:
            self._plugins[plugin.name] = resource
        self._root.putChild(plugin.name, self._plugins[plugin.name])

    def authed_resource(self, resource):
        """
        See HTTPInterface.register_resource()
        """
        return HTTPAuthSessionWrapper(Portal(EnDroidRealm(resource),
                                             self._creds),
                                      [BasicCredentialFactory("EnDroid")])

    def endroid_init(self, pluginmanager, port, interface, media_dir,
                     template_dir, credplugins):
        """
        credplugins is a list of strings or objects
        """
        def _get_cred(plugin):
            """
            Get a credential checker for one entry in the credplugins list.

            'plugin' might be an object or a string representing the name of
            a plugin.

            """

            logging.info("Getting credentials from plugin {}".format(plugin))
            try:
                cred = plugin.http_cred_checker()
            except Exception as e:
                # Plugin was probably a string, try finding a plugin of that 
                # name
                try:
                    cred = pluginmanager.get(plugin).http_cred_checker()
                except Exception as e:
                    logging.exception(e)
                    cred = None
            return cred
        self._creds = [_get_cred(p) for p in credplugins]
        self._root = IndexPage(self)
        self._media = File(media_dir)
        self._root.putChild("_media", self._media)

        template_loader = jinja2.FileSystemLoader(template_dir)
        self.jinja = jinja2.Environment(loader=template_loader)
        def datetime_filter(val, fmt="%H:%M:%S"):
            return time.strftime(fmt, time.localtime(val))
        self.jinja.filters['datetime'] = datetime_filter

        factory = Site(self._root)
        logging.info("Starting web server on {}:{}; static files in {}"
                     .format(interface, port, media_dir))
        reactor.listenTCP(port, factory, interface=interface)


class HTTPInterface(Plugin):
    """
    The actual plugin class. This may be instantiated multiple times, but is
    just a wrapper around a HTTPInterfaceSingleton object.
    """

    _singleton = None
    enInited = False
    name = "httpinterface"
    hidden = True

    def __init__(self):
        if HTTPInterface._singleton == None:
            HTTPInterface._singleton = HTTPInterfaceSingleton()

    def get_template(self, name):
        """
        Get a Jinja template by name.
        """
        return self._singleton.jinja.get_template(name)

    @classmethod
    def authed_resource(cls, resource):
        """
        Class method provided to plugins to wrap a resource to require auth.

        The authentication itself is handled by httpinterface's configuration
        (i.e. defers to authenticator plugins defined in configuration).
        """
        return cls._singleton.authed_resource(resource)
    
    def register_regex_path(self, plugin, callback, path_regex,
                            require_auth=False):
        """
        Register a callback to be called for requests whose URI matches:
           http://<server>/<plugin name>/<regex>[?<args>]

        Callback arguments:
            request: A twisted.web.http.Request object.
        """

        HTTPInterface._singleton.register_regex_path(plugin, callback,
                                                     path_regex,
                                                     require_auth=require_auth)

    def register_path(self, plugin, callback, path_prefix, require_auth=False):
        """
        Register a callback to be called for requests whose URI matches:
            http://<server>/<plugin name>/<prefix>[?<args>]

        Or:
            http://<server>/<plugin name>/<prefix>/<more path>[?<args>]

        Or if the prefix is the empty string:
            http://<server>/<plugin name>/<more path>[?<args>]
        """

        HTTPInterface._singleton.register_path(plugin, callback, path_prefix,
                                               require_auth=require_auth)

    def register_resource(self, plugin, resource, require_auth=False):
        """
        Register a resource for the given plugin.

        This should be used instead of the register_*path functions if the
        plugin has more complex routing requirements and wants to use the
        twisted web APIs directly.

        Each plugin must only call this API once. Subsequent calls will
        replace the resource registered on any previous call.
        """
        HTTPInterface._singleton.register_resource(plugin, resource,
                                                   require_auth=require_auth)

    def http_cred_checker(self):
        """
        Default credential checker that simply accepts user "endroid" and
        password "password". Shouldn't really be used!
        """
        return InMemoryUsernamePasswordDatabaseDontUse(endroid='password')

    def endroid_init(self):
        """
        Initialises the singleton object on first call only.

        Simply extracts the configuration, and passes it through.
        """
        if not HTTPInterface.enInited:
            port = self.vars.get("port", DEFAULT_HTTP_PORT)
            interface = self.vars.get("interface", DEFAULT_HTTP_INTERFACE)
            media_dir = self.vars.get("media_dir", DEFAULT_MEDIA_DIR)
            templ_dir = self.vars.get("template_dir", DEFAULT_TEMPL_DIR)
            credplugins = self.vars.get("credential_plugins", [self])
            HTTPInterface._singleton.endroid_init(self.plugins, port,
                                                  interface, media_dir,
                                                  templ_dir, credplugins)
            HTTPInterface.enInited = True
