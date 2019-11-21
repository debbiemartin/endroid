# -----------------------------------------------------------------------------
# EnDroid - Compute Plugin
# Copyright 2012, Ben Eills
# -----------------------------------------------------------------------------

"""
Plugin to fetch query results from WA, using their API.
"""

import endroid.messagehandler as messagehandler
from endroid.pluginmanager import Plugin
from endroid.pluginmanager import PluginInitError
from endroid.database import Database
from twisted.web.client import getPage
import logging
import wap
import urllib

# Constants for the DB values we use
WOLFRAM_API_SERVER_DEFAULT = "http://api.wolframalpha.com/v2/query"

MESSAGES = {
'help' : """
Compute is a plugin that interfaces with the WolframAlpha search engine.
Try 'compute Height of Eiffel Tower' to see it in action.""",

'default-error' : u"An error was encountered in computation.  Aborting.",
'no-result-error' : "No result was found for the query.",
'download-error' : "An error occurred while downloading the results: {0}"}

class Compute(Plugin):
    name = "compute"
    
    def dependencies(self):
        return ['endroid.plugins.command']
    
    def enInit(self):
        com = self.get('endroid.plugins.command')
        
        try:
            self.api_key = self.vars['api_key']
            self.server = self.vars.get('server', WOLFRAM_API_SERVER_DEFAULT)
            com.register_muc(lambda msg, arg: self.handle_command(msg, arg, True), 'compute')
            com.register_chat(self.handle_command, 'compute')
            self.waeo = wap.WolframAlphaEngine(self.api_key, self.server)
        except KeyError:
            logging.error("ERROR: Compute: There is no API key set in config!  Set 'api_key' variable"
                  " in section '[Plugin:endroid.plugins.compute]'.  Aborting plugin load.")
            raise PluginInitError("Aborted plugin initialization")

    def help(self):
        return MESSAGES['help']

    def handle_error(self, msg, error_message=None):
        reply = MESSAGES['default-error']
        if error_message:
            reply += u"\nDetails: " + error_message
        msg.reply(reply)

    def _result_callback(self, msg, result, fail_silent):
        """
        Deferred callback to handle result data.
        Called when page has sucessfully been downloaded.
        Negotiate (necessarily) nasty query result data and
        reply with nice string.
        """
        try:
            if result[:7] == u"<error>":
                self.handle_error(msg, "Error in PerformQuery()")
                return
            waeqr = wap.WolframAlphaQueryResult(result)
            pods = [wap.Pod(p) for p in waeqr.Pods()]
            if len(pods) < 2:
                if not fail_silent:
                    msg.reply(MESSAGES['no-result-error'])
                return
            pod = pods[1]  # Usually the second pod has useful stuff in it.
            title = pod.Title()[0]
            results = []  # Probably only one, but may be more
            for subpod in [wap.Subpod(s) for s in pod.Subpods()]:
                results.append(subpod.Plaintext()[0])  # Unicode
                resultstring = u'\n'.join(results)
            # Pretty print, omitting "Result" if possible
            if title == u'Result':
                msg.reply(u"{0}".format(resultstring))
            else:
                msg.reply(u"{0}: {1}".format(title, resultstring))
        except Exception as e:
            self.handle_error(msg, "Exception occurred: " + str(e))    

    def handle_command(self, msg, arg, fail_silent=False):
        """
        Upon user sending 'compute' command, tell Twisted to POST to query URL
          at some point in future and tell it what to do when successful.
        """
        args = arg.split()
        if not args:
            msg.reply(MESSAGES['help'])
            return
        query = self.waeo.CreateQuery(urllib.quote_plus(' '.join(args)))
        
        # Set up Twisted to asyncronously download page
        d = getPage(self.waeo.server,method='POST',postdata=str(query),
                    headers={'Content-Type':'application/x-www-form-urlencoded'})
        d.addCallbacks(callback=lambda data: self._result_callback(msg, data, fail_silent),
                       errback=lambda error: msg.reply(MESSAGES['download-error'].format(error)))
        

        

        
def get_plugin():
    return Compute()
