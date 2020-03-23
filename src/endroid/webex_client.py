#
# Webex Teams websocket client
#
import logging
import sys
import json
import requests
import uuid
import functools
import webexteamssdk
import pprint

from twisted.internet import reactor
from twisted.internet.protocol import ReconnectingClientFactory
from webexteamssdk import WebexTeamsAPI
from autobahn.twisted.websocket import WebSocketClientProtocol, \
    WebSocketClientFactory, connectWS
from twisted.internet import reactor

# Sports modules that are used by this module. Used when reloading plugin.
USED_MODULES = []

# Taken from https://github.com/cgascoig/ciscospark-websocket
DEVICES_URL = "https://wdm-a.wbx2.com/wdm/api/v1/devices"
DEVICE_DATA = {
    "deviceName":"pywebsocket-client",
    "deviceType":"DESKTOP",
    "localizedModel":"python",
    "model":"python",
    "name":"python-spark-client",
    "systemName":"python-spark-client",
    "systemVersion":"0.1"
}

# Time in seconds to wait after an event notification before attempting to get
# the event from webexteamssdk
EVENT_WAIT = 1

logger = logging.getLogger("webex-client")

def catch_api_errors(func):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except webexteamssdk.exceptions.ApiError as e:
            logger.exception(e)
    return wrapper

class WebexProto(WebSocketClientProtocol):
    """
    Webex web socket protocol. 

    Attributes (all added by this class):
        access_token - The authorization key for the Webex server. 
        on_message   - Callback to be called on receipt of message.

    Methods (all inherited from twisted websocket):
        onConnect    - Log the event.
        onConnecting - Log the event. 
        onOpen       - Send the access token to the server. 
        onMessage    - Call the specified on_message callback.
        onClose      - Log the event.
        
    """
    def __init__(self, access_token, connected, on_message):
        self.access_token = access_token
        self.on_connected = connected
        self.on_message = on_message
        super(WebexProto, self).__init__()

    #
    # Protocol handlers
    #
    def onConnect(self, response):
        """
        Called on the initiation of the websocket opening handshake by the 
        client. 
        """
        logger.info("Server connected: %s", response.peer)

    def onConnecting(self, transport_details):
        """
        Called immediately before the websocket opening handshake to the 
        server. 
        """
        logger.info("Connecting; transport details: %s", transport_details)
        return None  # ask for defaults

    def onOpen(self):
        """
        Called when the websocket opening handshake has been successfully 
        completed. Sends a message to the server containing the authorization
        key.
        """
        logger.info("WebSocket connection open.")

        msg = {
            'id': str(uuid.uuid4()),
            'type': 'authorization',
            'data': { 'token': 'Bearer ' + self.access_token }
        }
        self.sendMessage(json.dumps(msg).encode('utf8'))
        self.on_connected()

    def onMessage(self, payload, isBinary):
        """
        Called on receipt of a message from the server. Calls the specified 
        callback.
        """
        if isBinary:
            logger.debug("Binary message received: %u bytes",
                         len(payload))
        else:
            logger.debug("Text message received: %s",
                         payload.decode('utf8'))
        self.on_message(json.loads(payload))

    def onClose(self, wasClean, code, reason):
        """
        Called on the websocket closing handshake. 
        """
        logger.info("WebSocket connection closed: %s", reason)


class WebexProtoFactory(WebSocketClientFactory, ReconnectingClientFactory):
    """
    Webex web socket protocol factory.

    Methods:
        Inherited from websocket factory:
          buildProtocol - Produce an instance of the webex client protocol.
        Inherited from reconnecting factory:
          clientConnectionFailed - Log and retry the connection.
          clientConnectionLost   - Log and retry the connection.
    """
    maxDelay = 10

    def buildProtocol(self, addr):
        """
        Produce an instance of the webex client protocol.
        """
        proto = WebexProto(self.access_token, self.connected_handler, 
                           self.message_handler)
        proto.factory = self
        self.resetDelay()
        return proto

    def clientConnectionFailed(self, connector, reason):
        """
        Called when a connection has failed to connect. Retries the connection.
        """
        logger.info("Client connection failed (%s), retrying...", reason)
        self.retry(connector)

    def clientConnectionLost(self, connector, reason):
        """
        Called when an established connection is lost. Retries the connection.
        """
        logger.info("Client connection lost (%s), retrying...", reason)
        self.retry(connector)


class WebexClient(object):
    """
    The webex client instance. 

    Attributes:
        access_token  - The client's webex authorization key.
        on_message    - The callback to call on receipt of a message. 
        on_membership - The callback to call on notification of a membership 
                        creation.
        webex_api     - The instance of the webexteamssdk API.
        device_info   - Webex device information.
        my_emails     - Set of the client's registered webex emails.   
        my_person_id  - The client's webex person ID.      
    """
    def __init__(self, access_token, on_message=None, on_membership=None,
                 ping_interval=10, ping_timeout=20):
        self.access_token = access_token
        self.connected = None
        self.on_message = None
        self.on_membership = None
        self.webex_api = WebexTeamsAPI(access_token=access_token)
        self.device_info = None
        self._get_device_info()
        self.my_emails = self.webex_api.people.me().emails
        self.my_person_id = self.webex_api.people.me().id

        if self.device_info is not None:
            factory = WebexProtoFactory(self.device_info['webSocketUrl'])
            factory.access_token = access_token
            factory.message_handler = self._process_message
            factory.connected_handler = self._process_connected
            factory.setProtocolOptions(autoPingInterval=ping_interval,
                                       autoPingTimeout=ping_timeout)
            connectWS(factory)
            
    def _get_device_info(self):
        # Always create a new device 
        logging.info('Creating new device info')
        session = self.webex_api._session.post(DEVICES_URL, 
                                               json=DEVICE_DATA)
        if session is None:
            logger.error('Could not create device with webex')
        else:
            logger.info('Successfully registered new device with webex')
            self.device_info = session

    def set_callbacks(self, connected, on_message, on_membership):
        self.connected = connected
        self.on_message = on_message
        self.on_membership = on_membership
        
    @catch_api_errors
    def _process_message(self, data):
        if data['data']['eventType'] == 'conversation.activity':
            logger.debug('Event Type is conversation.activity') 
            activity = data['data']['activity']

            if activity['verb'] == 'post': 
                # Handle a message
                logger.debug('activity verb is post, message id is %s',
                              activity['id'])
                try:
                    message = self.webex_api.messages.get(activity['id'])

                    logger.info('Message from %s: %s',
                                message.personEmail, message.text)
                    self.on_message(message)
                except Exception as e:
                    # Just log the message, don't retry - failure to get a
                    # message is normally due to no longer being in a room 
                    # rather than timing.
                    logger.exception(e)

            elif activity['verb'] == 'add':
                # Handle a membership - defer getting the event for a second as
                # it may not be immediately findable
                logger.debug('activity verb is add, event id is %s',
                              activity['id'])
                def _process_membership(eventId):
                    try:
                        event = self.webex_api.events.get(eventId=eventId)
                        logger.info('Membership created for %s into %s room',
                                    event.data.personEmail, event.data.roomId)
                        self.on_membership(event.data)
                    except Exception as e:
                        logger.exception
                        # If the event is still not findable, defer again.
                        later = reactor.callLater(EVENT_WAIT,
                                                  _process_membership, eventId)

                # Defer the membership get since events are not immediately
                # findable.
                later = reactor.callLater(EVENT_WAIT, _process_membership,
                                          activity['id'])

    @catch_api_errors
    def _process_connected(self):
        logging.info("In _process_connected")
        self.connected()
