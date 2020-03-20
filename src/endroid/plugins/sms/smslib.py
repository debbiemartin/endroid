# (c) Ensoft Ltd, 2014
__author__ = 'jamesh'
__all__ = ("send", "SMSError", "SMSAuthError", "SMSInvalidNumberError")
"""Module to send an sms message"""

import treq

import argparse
import logging


class SMSError(Exception):
    """Base class for exceptions raised by this module."""


class SMSInvalidNumberError(SMSError):
    """Exception raised if the calling number or the called number are invalid.
    Invalidity is determined by the SMS remote service."""


class SMSAuthError(SMSError):
    """Exception raised if the supplied SID or auth token are invalid.
    That is, they do not match, or they are of the wrong format."""


def _parse_response_code(r):
    """
    Determines whether the SMS was sent correctly, by examining the Twilio server's response.
    This is a convenience function, which automatically raises an appropriate
    error if the request failed or was malformed. It returns a Deferred which
    can be used to access the body of the request, in the event of success.
    :param r: server response string, as a Deferred which presents the response as string.
    """
    status_code = r.code

    if status_code == 201:
        logging.info("SMS sent successfully")
    elif status_code == 400:
        #incorrect calling number or invalid number being called
        raise SMSInvalidNumberError(r.text())
    elif status_code == 401:
        #incorrect auth (length or code) or incorrect sid code
        raise SMSAuthError(r.text())
    elif status_code == 404:
        #incorrect sid length
        raise SMSAuthError(r.text())
    else:
        not_recognised = "SMS error: status code " + str(status_code) + " not recognised"
        logging.warning(not_recognised)
        raise SMSError(not_recognised)

    return r.content()


def _http_failed(failure):
    """
    Errback to log an SMS error warning to the logs.
    :param failure: the Deferred failure object the callback will receive
    :return: the input failure object
    """
    logging.warning('SMS error: could not connect to the server.')
    logging.warning(str(failure))

    return failure


def send(from_, to, msg, sid, auth):
    """
    Sends an SMS using Twilio.
    :param from_: the phone number (must be registered with Twilio already)
    :param to: the recipient number
    :param msg: body of the SMS
    :param sid: 16 hex digits representing your username with Twilio
    :param auth: 16 hex digits, your authentication key with Twilio
    :return: a Deferred object which presents the server response body (string).
    """

    if not all([from_, to, msg, sid, auth]):
        raise SMSError("You must supply a calling twilio number along with its "
                       "authentication code and sign-in id, "
                       "as well as a message body and the number being called.")

    url = 'https://api.twilio.com/2010-04-01/Accounts/' + sid + '/Messages'
    params = {"From": from_, "To": to, "Body": msg}
    # make the request
    request_deferred = treq.post(url, params, auth=(sid, auth))
    request_deferred.addCallbacks(_parse_response_code, _http_failed)
    return request_deferred


def main():
    #  SID should be sixteen hex digits, as should auth.

    parser = argparse.ArgumentParser(description="Send an sms message")
    parser.add_argument('--from_', required=False, metavar="PHONE_NUMBER",
                        help="Phone number doing the send, format +447771010101",
                        default='+009876543210')
    parser.add_argument('--to', required=False, metavar="PHONE_NUMBER",
                        help="Phone number being called, format +447771010101",
                        default='+991234567890')
    parser.add_argument('--sid', required=False, metavar="ID",
                        help="sign-in Id of calling twilio number",
                        default='0000000000000000')
    parser.add_argument('--auth', required=False, metavar="AUTH_TOKEN",
                        help="Authentication token of calling twilio number",
                        default="0000000000000000")
    parser.add_argument('--message', required=False, metavar="MESSAGE",
                        help="Message to be sent", default="Hello!")
    parsed = parser.parse_args()

    sid = parsed.sid[0]
    from_ = parsed.from_[0]
    to = parsed.to[0]
    auth = parsed.auth[0]
    message = parsed.message[0]
    sid = parsed.sid[0]

    deferred = send(from_, to, message, sid, auth)
    deferred.addCallback(_parse_response_code)
    deferred.addErrback(_http_failed)
    deferred.addCallback(lambda r: logging.info(r.text))

if __name__ == '__main__':
    main()
