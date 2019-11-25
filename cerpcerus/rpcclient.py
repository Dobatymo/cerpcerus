from __future__ import absolute_import, division, print_function, unicode_literals

import logging
from typing import TYPE_CHECKING

from twisted.internet.protocol import ClientFactory
from twisted.internet import defer, error

from .rpc import RemoteObject, VoidServiceFactory
from .rpcbase import RPCBase, NetworkError, AllFriends, UnknownPeer
from .utils import IProtocolConnector, IPAddr

from .simple_protocol import Factory, SimpleProtocol
from .websocket_protocol import WebSocketClientFactory, WebSocketClientAdapter

if TYPE_CHECKING:
	from typing import Any, Optional
	from twisted.internet import ssl
	from twisted.internet.defer import Deferred
	from .rpc import ServiceFactory, Service
	from .rpcbase import IFriends

logger = logging.getLogger(__name__)

class RPCClient(RPCBase):
	"""Client specialisation of RPCBase"""

	def __init__(self, friends, transport_protocol, deferred=None):
		# type: (IFriends, Any, Optional[Deferred]) -> None

		RPCBase.__init__(self, friends, transport_protocol)
		self.deferred = deferred

	def authenticated(self, pubkey):
		# type: (bytes, ) -> None

		self.friends.establish_connection(self.name, RemoteObject(self)) # overwrites existing connection
		self.friends.reset_connecting(self.name, self.deferred)
		if self.deferred:
			self.deferred.callback(RemoteObject(self))

class RPCClientFactory(ClientFactory):
	"""Factory needed for Twisted. Uses a service factory to present a service to peers"""
	def __init__(self, friends, service_factory, transport_protocol_factory, name):
		# type: (IFriends, ServiceFactory, Factory, str) -> None

		self.friends = friends
		self.service_factory = service_factory
		self.transport_protocol_factory = transport_protocol_factory
		self.auth_d = defer.Deferred()
		self.name = name

	@property
	def deferred(self):
		# type: () -> Deferred

		"""Get the authentication deferred."""
		return self.auth_d

	def clientConnectionFailed(self, connector, reason):
		self.friends.reset_connecting(self.name, self.auth_d)
		try:
			conn = self.friends.get_connection(self.name)
		except UnknownPeer:
			conn = None
		if conn:
			logger.info("Connection to %s at %s failed, but was established from the other side in the meantime",
				self.name, connector.getDestination())
			# might not be from the other side, but a previously opened connection
			# this is not very general and might not be what the user wants
			self.auth_d.callback(conn)
		else:
			logger.warning("Connection to %s at %s failed: %s", self.name, connector.getDestination(), reason.getErrorMessage())
			self.auth_d.errback(NetworkError(reason.getErrorMessage()))

	def clientConnectionLost(self, connector, reason):
		self.friends.reset_connecting(self.name, self.auth_d) # only needed if connection is lost before authentication
		if reason.check(error.ConnectionDone):
			logger.debug("Connection to %s closed", connector.getDestination()) #logs needed? bc duplicate
		else:
			logger.info("Connection to %s lost: %s", connector.getDestination(), reason.getErrorMessage())

	def startedConnecting(self, connector):
		self.friends.start_connecting(self.name, self.auth_d)
		logger.debug("Started connecting to %s", connector.getDestination())

	def buildProtocol(self, addr):
		transport_protocol = self.transport_protocol_factory.buildProtocol(addr)
		conn = RPCClient(self.friends, transport_protocol, self.auth_d)
		IProtocolConnector(transport_protocol, conn)
		remote = RemoteObject(conn)
		service = self.service_factory.build(remote) #do not use RemoteObject here, instead use OnConnect(remote)
		conn.service = service
		#self.friends.update_by_addr(IPAddr(addr.host, addr.port), conn = remote)
		return transport_protocol

def Client(reactor, host, port, name, ssl_context, service=None, friends=None, transport_protocol_factory=None):
	# type: (Any, str, int, str, ssl.ContextFactory, Optional[Service], Optional[IFriends], Optional[Factory]) -> Deferred

	"""Connects to `host`:`port`, and uses `name` as identifier for this connection.
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
	if not transport_protocol_factory:
		transport_protocol_factory = Factory()
		transport_protocol_factory.protocol = SimpleProtocol

		# WebSocketAdapterProtocol does not support unregisterProducer() # should be fixed
		#transport_protocol_factory = WebSocketClientFactory("wss://{}:{}".format(host, port), protocols=["binary"])
		#transport_protocol_factory.protocol = WebSocketClientAdapter

	factory = RPCClientFactory(friends, service, transport_protocol_factory, name)
	reactor.connectSSL(host, port, factory, ssl_context)
	return factory.deferred
