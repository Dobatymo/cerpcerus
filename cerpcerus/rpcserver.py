from __future__ import unicode_literals

import logging

from twisted.internet.protocol import ServerFactory

from rpc import RemoteObject, VoidServiceFactory
from rpcbase import RPCBase, IPAddr, AllFriends
from utils import IProtocolConnector

from simple_protocol import Factory, SimpleProtocol
from websocket_protocol import WebSocketServerFactory, WebSocketServerAdapter

logger = logging.getLogger(__name__)

class RPCServer(RPCBase):
	"""Server specialisation of RPCBase"""

	def authenticated(self, key):
		self.friends.set_addr(self.name, self.addr) #bad: sets outgoing instead of incoming  port / overwrites existings addr of possibly currently established connection
		self.friends.establish_connection(self.name, RemoteObject(self)) # overwrites existings connection

class RPCServerFactory(ServerFactory):
	"""Factory needed for Twisted. Uses a service factory to present a service to peers"""
	def __init__(self, friends, service_factory, transport_protocol_factory):
		self.friends = friends
		self.service_factory = service_factory
		self.transport_protocol_factory = transport_protocol_factory

	def buildProtocol(self, addr):
		transport_protocol = self.transport_protocol_factory.buildProtocol(addr)
		conn = RPCServer(self.friends, transport_protocol)
		IProtocolConnector(transport_protocol, conn)
		remote = RemoteObject(conn)
		service = self.service_factory.build(remote)
		conn.service = service
		#self.friends.update_by_addr(IPAddr(addr.host, addr.port), conn = remote) #overwrites existings connection
		return transport_protocol

def Server(reactor, port, ssl_context_factory, service=None, friends=None, transport_protocol_factory=None, interface="", backlog=None):
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
	if not transport_protocol_factory:
		transport_protocol_factory = Factory()
		transport_protocol_factory.protocol = SimpleProtocol

		# WebSocketAdapterProtocol does not support unregisterProducer()
		#transport_protocol_factory = WebSocketServerFactory(u"wss://{}:{}".format(interface, port), protocols=["binary"])
		#transport_protocol_factory.protocol = WebSocketServerAdapter

	if backlog:
		return reactor.listenSSL(port, RPCServerFactory(friends, service, transport_protocol_factory), ssl_context_factory, backlog, interface)
	else:
		return reactor.listenSSL(port, RPCServerFactory(friends, service, transport_protocol_factory), ssl_context_factory, interface=interface)
