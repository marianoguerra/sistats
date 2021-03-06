'''REST transport for stats'''
import time
import json
import Queue
import pprint
import requests
import threading

import transport

from optparse import OptionParser

class ThreadDoer(threading.Thread):
    QUIT_MSG = object()

    def __init__(self):
        threading.Thread.__init__(self)
        self._in = Queue.Queue()

    def call(self, fun, *args, **kwargs):
        self._in.put((fun, args, kwargs))

    def quit(self):
        self._in.put(ThreadDoer.QUIT_MSG)

    def run(self):
        while True:
            msg = self._in.get()

            if msg is ThreadDoer.QUIT_MSG:
                break

            fun, args, kwargs = msg

            try:
                fun(*args, **kwargs)
            except Exception as error:
                print "error calling", fun, args, kwargs, error

        print "exiting doer"

class Event(object):
    '''a class that holds message metadata and payload'''

    def __init__(self, value, channel):

        self.value = value
        self.channel = channel

    def to_json(self):
        '''return a dict representation'''
        dct = vars(self).copy()
        return dct

    def __str__(self):
        '''return a string representation'''
        return pprint.pformat(self.to_json())

class Checker(transport.Checker):
    '''checker class that sends the stats to a mqtt broker'''

    def __init__(self, client_id, username, password, login_ep, data_ep,
            topic_template="sistats.%s.%s", verbose=False, blacklist=None):
        transport.Checker.__init__(self, blacklist)

        self.data_ep = data_ep
        self.login_ep = login_ep

        self.session_key = None

        self.username = username
        self.password = password

        self.topic_template = topic_template
        self.client_id = client_id

        self.verbose = verbose

        self.doer = ThreadDoer()
        self.doer.start()
        self.login()

    def log(self, *args):
        '''log if verbose flag is True'''
        if self.verbose:
            print " ".join([str(arg) for arg in args])

    def login(self):
        '''login to the service and get the session key'''
        self.log("logging in to", str(self.login_ep), "with", self.username)
        self.cookies = login(self.login_ep, self.username, self.password)
        self.log("logged in with", self.session_key)

    def send_stats(self, name, data):
        '''send stats somewhere'''
        topic = self.topic_template % (self.client_id, name)
        self.send(topic, data)

    def send_delta_stats(self, name, data):
        '''send delta stats somewhere'''
        topic = self.topic_template % (self.client_id, name) + ".diff"
        self.send(topic, data)

    def _send(self, topic, data):
        event = Event(data, topic)
        self.log("send to", str(self.data_ep))
        self.log(event)
        json_data = json.dumps(event.to_json())

        headers = {
            'content-type': 'application/json'
        }

        response = requests.post(str(self.data_ep), json_data, headers=headers,
                cookies=self.cookies)

        self.log("response", response.status_code)
        if response.status_code in (401, 403):
            self.login()

    def send(self, topic, data):
        '''send event to the data endpoint'''
        self.doer.call(self._send, topic, data)

    def on_exit(self):
        self.doer.quit()

def login(endpoint, username, password):
    '''do a login to endpoint'''
    session = dict(username=username, password=password)
    data = json.dumps(session)
    headers = {'content-type': 'application/json'}

    response = requests.post(str(endpoint), data, headers=headers)

    return response.cookies

def base_option_parser():
    '''create a parser for the basic options and return it, used to extend
    the command line parsing with custom options for other agents
    '''
    parser = OptionParser()

    parser.add_option("-v", action="store_true", dest="verbose", default=False,
        help="be verbose")
    parser.add_option("-c", "--clientid", dest="clientid", default=None,
        help="generate event for clientid", metavar="ID")
    parser.add_option("-e", "--endpoint", dest="endpoint",
            default="/api/event", help="send event to ENDPOINT",
            metavar="ENDPOINT")
    parser.add_option("-l", "--loginendpoint", dest="loginendpoint",
            default="/api/session", help="login to ENDPOINT",
            metavar="ENDPOINT")

    parser.add_option("-H", "--host", dest="host", default="localhost",
        help="send events to HOST", metavar="HOST")
    parser.add_option("-P", "--port", dest="port", default=8080,
        type="int", help="send events to PORT", metavar="PORT")

    parser.add_option("-r", "--retries", dest="max_retries", default=3,
        type="int", help="max retries to send event", metavar="RETRIES")

    parser.add_option("-u", "--username", dest="username", default=None,
        help="authenticate using USERNAME", metavar="USERNAME")
    parser.add_option("-p", "--password", dest="password", default=None,
        help="authenticate using PASSWORD, if not provided ask for it",
        metavar="PASSWORD")

    parser.add_option("-C", "--checkinterval", dest="checkinterval",
            default=10, type="int",
            help="check for new values every SEC seconds", metavar="SEC")

    parser.add_option("-b", "--blacklist", dest="blacklist", default="",
        help="don't generates events for the given types", metavar="TYPES")

    return parser

class EndPoint(object):
    '''describes an API endpoint'''

    def __init__(self, host, port, path, protocol="http"):
        self.host = host
        self.port = port
        self.path = path
        self.protocol = protocol

    def __str__(self):
        return "%s://%s:%s%s" % (self.protocol, self.host, str(self.port),
                self.path)

def main():
    '''main function if this module is called, starts a mqtt listener'''
    parser = base_option_parser()
    opts, _args = parser.parse_args()

    login_ep = EndPoint(opts.host, opts.port, opts.loginendpoint)
    data_ep = EndPoint(opts.host, opts.port, opts.endpoint)

    checker = Checker(opts.clientid, opts.username, opts.password, login_ep,
            data_ep, verbose=opts.verbose, blacklist=opts.blacklist.split(","))

    transport.main_loop(checker, opts.checkinterval)

if __name__ == "__main__":
    main()

