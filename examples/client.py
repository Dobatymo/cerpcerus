#from __future__ import print_function

import sys, logging
from twisted.internet import reactor, defer

import cerpcerus

logging.basicConfig(level=logging.DEBUG, format="%(levelname)s\t%(name)s\t%(funcName)s\t%(message)s")

ssl = cerpcerus.GenericRPCSSLContextFactory("client-pub.pem", "client-priv.pem", False)

@defer.inlineCallbacks
def Task():
    conn = yield cerpcerus.Client(reactor, "127.0.0.1", 1337, "Server", ssl)
    print(yield conn.introspect())
    
    try:
        yield conn.reactor()
    except cerpcerus.RPCInvalidArguments:
        logging.info("reactor() failed as expected")
    
    calc1 = yield conn.Calc(1)
    calc2 = yield conn.Calc(2)
    print(yield calc1.introspect())
    calc1.add(10)
    calc2.add(10)
    res1 = yield calc1.get()
    res2 = yield calc2.get()
    print(res1, res2)

    yield conn.remote(calc1)

    print(yield dir(calc1))
    
    while True:
        result = yield conn.Echo("0123456789"*100000)
        #print(result)
    yield conn._loose()
    reactor.callLater(1, Stop)

def Stop(*args):
    reactor.stop()

reactor.callWhenRunning(Task)
reactor.run()
