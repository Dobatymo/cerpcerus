from __future__ import unicode_literals

import logging

from twisted.internet.protocol import ClientFactory
from twisted.internet import defer, error

from rpc import RemoteObject, VoidServiceFactory
from rpcbase import RPCBase, IPAddr, NetworkError, AllFriends, UnknownPeer

logger = logging.getLogger(__name__)

class RPCClient(RPCBase):
    """Client specialisation of RPCBase"""
    def __init__(self, friends, deferred=None):
        RPCBase.__init__(self, friends)
        self.deferred = deferred

    def authenticated(self, pubkey):
        self.friends.establish_connection(self.name, RemoteObject(self)) # overwrites existings connection
        self.friends.reset_connecting(self.name, self.deferred)
        if self.deferred:
            self.deferred.callback(RemoteObject(self))

class RPCClientFactory(ClientFactory):
    """Factory needed for Twisted. Uses a service factory to present a service to peers"""
    def __init__(self, friends, service_factory, name):
        self.friends = friends
        self.service_factory = service_factory
        self.auth_d = defer.Deferred()
        self.name = name

    @property
    def deferred(self):
        """Get the authentication deferred."""
        return self.auth_d

    def clientConnectionFailed(self, connector, reason):
        self.friends.reset_connecting(self.name, self.auth_d)
        try:
            conn = self.friends.get_connection(self.name)
        except UnknownPeer:
            conn = None
        if conn:
            logger.info("Connection to {} at {} failed, but was established from the other side in the meantime".format(self.name, connector.getDestination()))
            # might not be from the other side, but a previously opened connection
            # this is not very general and might not be what the user wants
            self.auth_d.callback(conn)
        else:
            logger.warning("Connection to {} at {} failed: {}".format(self.name, connector.getDestination(), reason.getErrorMessage()))
            self.auth_d.errback(NetworkError(reason.getErrorMessage()))

    def clientConnectionLost(self, connector, reason):
        self.friends.reset_connecting(self.name, self.auth_d) # only needed if connection is lost before authentication
        if reason.check(error.ConnectionDone):
            logger.debug("Connection to {} closed".format(connector.getDestination())) #logs needed? bc duplicate
        else:
            logger.info("Connection to {} lost: {}".format(connector.getDestination(), reason.getErrorMessage()))

    def startedConnecting(self, connector):
        self.friends.start_connecting(self.name, self.auth_d)
        logger.debug("Started connecting to {}".format(connector.getDestination()))

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
    factory = RPCClientFactory(friends, service, name)
    reactor.connectSSL(host, port, factory, ssl_context)
    return factory.deferred
