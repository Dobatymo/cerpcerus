from __future__ import unicode_literals

import logging

from twisted.internet.protocol import ServerFactory

from rpc import RemoteObject, VoidServiceFactory
from rpcbase import RPCBase, IPAddr, AllFriends

logger = logging.getLogger(__name__)

class RPCServer(RPCBase):
    """Server specialisation of RPCBase"""
    pass

class RPCServerFactory(ServerFactory):
    """Factory needed for Twisted. Uses a service factory to present a service to peers"""
    def __init__(self, friends, service_factory):
        self.friends = friends
        self.service_factory = service_factory

    def buildProtocol(self, addr):
        conn = RPCServer(self.friends)
        remote = RemoteObject(conn)
        service = self.service_factory.build(remote)
        conn.service = service
        #self.friends.update_by_addr(IPAddr(addr.host, addr.port), conn = remote) #overwrites existings connection
        return conn

def Server(reactor, port, ssl_context_factory, service=None, friends=None, interface="", backlog=None):
    """Starts rpc server on 'port' on 'interface'.
    reactor: Twisted reactor object
    ssl_context_factory: Twisted ssl.ContextFactory object
    service: Service offered to the other side of the connection (default: VoidServiceFactory())
    friends: can be used to manage or keep track of the rpc connections (default: AllFriends())
    interface: "" means all ipv4, "::1" means all ipv6
    backlog: low level parameter which limits the number of half open tcp connections (default: twisted default)
    Returns Twisted ssl.Port object. Port.stopListening() can be used to close server.
    """
    if not service:
        service = VoidServiceFactory()
    if not friends:
        friends = AllFriends()
    if backlog:
        return reactor.listenSSL(port, RPCServerFactory(friends, service), ssl_context_factory, backlog, interface)
    else:
        return reactor.listenSSL(port, RPCServerFactory(friends, service), ssl_context_factory, interface=interface)