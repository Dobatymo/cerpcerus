from __future__ import absolute_import, division, print_function, unicode_literals

import logging

from typing import TYPE_CHECKING

from autobahn.twisted.websocket import WebSocketClientProtocol, WebSocketServerProtocol
from autobahn.twisted.websocket import WebSocketClientFactory, WebSocketServerFactory # convenience import for other modules

from twisted.python.failure import Failure
from twisted.internet.protocol import connectionDone

if TYPE_CHECKING:
	from typing import Union

logger = logging.getLogger(__name__)

class WebSocketAdapterMixin(object):

	"""Mixin to connect WebSocketProtocols to RPC protocol"""

	# call

	def send_data(self, data):
		# type: (bytes, ) -> None

		"""Send packet with binary data"""
		#logger.debug("Sent {} {}".format(len(data), hash(data)))
		self.sendMessage(data, isBinary=True)

	def soft_disconnect(self):
		# type: () -> None

		"""Disconnects cleanly"""
		self.sendClose()
		#self.dropConnection(abort=False)

	def hard_disconnect(self):
		# type: () -> None

		"""Disconnects without WebSocket closing handshake"""
		self.dropConnection(abort=True)

	# overwrite

	def connection_made(self):
		pass

	def connection_open(self):
		pass

	def connection_lost(self, reason):
		pass

	def recv_data(self, data):
		# type: (bytes, ) -> None

		"""Receive packet with binary data"""
		raise NotImplementedError("recv_data(self, data)")

	# autobahn protocol callbacks

	def onOpen(self):
		# type: () -> None

		"""called after handshake is completed"""
		self.connection_open()
		self.debug = "onOpen"

	def onClose(self, wasClean, code, reason):
		"""called when the WebSocket connection is closed"""

		if not hasattr(self, "debug"):
			logger.error("Line closed without calling Connect or Open first. Happens when normal http request is sent on websocket.")

		if wasClean:
			reason = connectionDone
		else:
			reason = Failure(Exception(reason)) # chose twisted exception based on code
		self.connection_lost(reason)

	def onMessage(self, payload, isBinary):
		# type: (Union[bytes, str], bool) -> None

		"""delegate message to RPC protocol, drops connection if not binary"""
		#logger.debug("Received {} {}".format(len(payload), hash(payload)))
		if isBinary:
			self.recv_data(payload)
		else:
			self.dropConnection(abort=True)

class WebSocketClientAdapter(WebSocketAdapterMixin, WebSocketClientProtocol):

	"""WebSocket client protocol"""

	def __init__(self, *args, **kwargs):
		WebSocketClientProtocol.__init__(self, *args, **kwargs) #args needed?

	def onConnect(self, response):
		self.debug = "onConnect"
		#self.connection_made()

	def connectionMade(self):
		# type: () -> None

		self.connection_made()
		WebSocketClientProtocol.connectionMade(self)

class WebSocketServerAdapter(WebSocketAdapterMixin, WebSocketServerProtocol):

	"""WebSocket server protocol"""

	BINARY = "binary"

	def __init__(self, *args, **kwargs):
		WebSocketServerProtocol.__init__(self, *args, **kwargs) #args needed?

	def onConnect(self, request):
		self.debug = "onConnect"
		#self.connection_made()
		if self.BINARY in request.protocols:
			return self.BINARY
		else:
			return None

	def connectionMade(self):
		# type: () -> None

		self.connection_made()
		WebSocketServerProtocol.connectionMade(self)
