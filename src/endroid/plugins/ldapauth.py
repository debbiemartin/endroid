#
# EnDroid - LDAP-based authenticator
#

from ldaptor import checkers, config

from endroid.pluginmanager import Plugin

class LDAPAuth(Plugin):
    hidden = True
    name = "ldapauth"
    def http_cred_checker(self):
        # Check whether we've been configured with the attribute forming the
        # relative DN for identity entries within the directory and use the
        # appropriate LDAP credential checker object.
        rdn = self.vars.get("identityrdn")
        if rdn:
            return LDAPAuthedBindingChecker(
                LDAPAuthedConfig(','.join(self.vars.get("basedn")),
                                 {','.join(self.vars.get("basedn")):
                                      (self.vars.get("ldaphost"),
                                       int(self.vars.get("ldapport", 389)))},
                                 identityRelativeDN=rdn))
        else:
            return checkers.LDAPBindingChecker(
                config.LDAPConfig(','.join(self.vars.get("basedn")),
                                  {','.join(self.vars.get("basedn")):
                                       (self.vars.get("ldaphost"),
                                        int(self.vars.get("ldapport", 389)))}))

# Subclass the ldaptor package's LDAPBindingChecker with a variant that
# supplies the user's credentials to the bind call; do this by overriding the
# _connected callback method.
#
# On the assumption that this will be used when anonymous access to the LDAP
# server is not allowed, the user's entry is not looked up before binding.
# Instead the full distinguished name of the user is constructed from this
# plugin's config.
#
# Also subclass LDAPConfig, so that we can attach an extra bit of config to
# it.
class LDAPAuthedBindingChecker(checkers.LDAPBindingChecker):
    def _connected(self, client, filt, credentials):
        d = client.bind(self.config.getIdentityDN(credentials.username),
                        credentials.password)
        d.addCallback(self._bound)
        return d

    def _bound(self, bindresult):
        # Doesn't matter what we return here: it's never used.
        return bindresult

class LDAPAuthedConfig(config.LDAPConfig):
    def __init__(self,
                 baseDN=None,
                 serviceLocationOverrides=None,
                 identityBaseDN=None,
                 identitySearch=None,
                 identityRelativeDN="cn"):
        super(LDAPAuthedConfig, self).__init__(baseDN,
                                               serviceLocationOverrides,
                                               identityBaseDN,
                                               identitySearch)
        self.identityRelativeDN = identityRelativeDN

    def getIdentityDN(self, name):
        return "{}={},{}".format(self.identityRelativeDN,
                                 name,
                                 str(self.getIdentityBaseDN()))

