import sys, logging
from twisted.internet import reactor

import cerpcerus

class TestService(cerpcerus.Service):
    def __init__(self, reactor, conn):
        cerpcerus.Service.__init__(self, True)
        self.reactor = reactor
        self.conn = conn #use _OnConnect for conn

    def Echo(self, str):
        return str

    def remote(self, remoteinstance):
        print(remoteinstance)

    #def _OnDisconnect(self):
    #    self.reactor.stop()

    class Calc(cerpcerus.Service):
        def __init__(self, num):
            cerpcerus.Service.__init__(self, True)
            self.num = num
        
        def add(self, num):
            self.num += num
        
        def sub(self, num):
            self.num -= num
        
        def get(self):
            return self.num

class MySSLContextFactory(cerpcerus.GenericRPCSSLContextFactory):

    def __init__(self):
        cerpcerus.GenericRPCSSLContextFactory.__init__(self, "server-pub.pem", "server-priv.pem", verify_ca = True)

    def valid_ca_cert_files(self):
        return ("client-pub.pem",)

logging.basicConfig(level=logging.DEBUG, format="%(levelname)s\t%(name)s\t%(funcName)s\t%(message)s")

service = cerpcerus.SeparatedService(TestService, reactor)
ssl = MySSLContextFactory()

cerpcerus.Server(reactor, 1337, ssl, service, interface = "127.0.0.1")
reactor.run()
