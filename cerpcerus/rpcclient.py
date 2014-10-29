from __future__ import unicode_literals

import logging

from twisted.internet.protocol import ClientFactory
from twisted.internet import defer, error

from rpc import RemoteObject, VoidServiceFactory
from rpcbase import RPCBase, IPAddr, NetworkError, AllFriends

logger = logging.getLogger(__name__)

class RPCClient(RPCBase):
    """Client specialisation of RPCBase"""
    def __init__(self, friends, deferred=None):
        RPCBase.__init__(self, friends)
        self.deferred = deferred

    def authenticated(self, name, key):
        RPCBase.authenticatedFromClient(self, name, key)
        if self.deferred:
            self.deferred.callback(RemoteObject(self))

class RPCClientFactory(ClientFactory):
    """Factory needed for Twisted. Uses a service factory to present a service to peers"""
    def __init__(self, friends, service_factory, auth_d, name):
        self.friends = friends
        self.service_factory = service_factory
        self.auth_d = auth_d
        self.name = name

    def clientConnectionFailed(self, connector, reason):
        try:
            __, conn, __ = self.friends.get_by_name(self.name)
        except KeyError as e:
            conn = None
        if conn:
            logger.info("Connection to {} at {} failed, but was established from the other side in the meantime".format(self.name, connector.getDestination()))
            if self.auth_d:
                self.auth_d.callback(conn)
        else:
            logger.warning("Connection to {} at {} failed: {}".format(self.name, connector.getDestination(), reason.getErrorMessage()))
            if self.auth_d:
                self.auth_d.errback(NetworkError(reason.getErrorMessage()))

    def clientConnectionLost(self, connector, reason):
        self.friends.reset_connecting(self.name)
        if reason.check(error.ConnectionDone):
            logger.debug("Connection to {} closed".format(connector.getDestination()))
        else:
            logger.info("Connection to {} lost: {}".format(connector.getDestination(), reason.getErrorMessage()))

    def setClientInfo(self, deferred, name): #dont use, delete later
        self.auth_d = deferred
        self.name = name

    def buildProtocol(self, addr):
        conn = RPCClient(self.friends, self.auth_d)
        remote = RemoteObject(conn)
        service = self.service_factory.build(remote) #do not use RemoteObject here, instead use OnConnect(remote)
        conn.service = service
        #self.friends.update_by_addr(IPAddr(addr.host, addr.port), conn = remote)
        return conn

def Client(reactor, host, port, name, ssl_context, service=None, friends=None):
    """Connects to host:port, and uses 'name' as identifier for this connection.
    reactor: twisted reactor object
    ssl_context: Twisted ssl.ContextFactory object
    service: Service which the client provides (can be used from other side)
    friends: IFriends object which can be used to manage and keep track of the rpc connections
    Returns a deferred which fires when the connection is completely established (connected and authenticated)
    """
    if not service:
        service = VoidServiceFactory()
    if not friends:
        friends = AllFriends()
    deferred = defer.Deferred()
    friends.set_connecting(name, deferred)
    factory = RPCClientFactory(friends, service, deferred, name)
    reactor.connectSSL(host, port, factory, ssl_context)
    return deferred
