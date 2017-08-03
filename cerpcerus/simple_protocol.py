from struct import pack, unpack
#import logging

from twisted.internet.protocol import Protocol
from twisted.internet.protocol import Factory # convenience import for other modules

from utils import SimpleBuffer

from twisted.internet.interfaces import IHandshakeListener
from zope.interface import implementer

@implementer(IHandshakeListener) # otherwise handshakeCompleted is not called
class SimpleProtocol(Protocol):

	"""Twisted Protocol that assures that packets are not fragmented.
	That means for every send_data() there will be one recv_data() call.
	cf. twisted.protocols.basic.Int32StringReceiver
	"""

	def __init__(self):
		self._pos = 0
		self._int_len = 4
		self._buf_len = None
		self._length = self._int_len
		self._buffer = SimpleBuffer()

	# call

	def send_data(self, data):
		"""Send packet
		data: byte string (not unicode)"""
		buf_len = pack("!I", len(data))
		self.transport.write(buf_len + data)
		#self.transport.writeSequence((buf_len, data)) # is this better?

	def soft_disconnect(self):
		"""Disconnects and flushes write buffer first"""
		self.transport.loseConnection()

	def hard_disconnect(self):
		"""Disconnects and doesn't flush write buffer"""
		self.transport.abortConnection()

	def registerProducer(self, producer, streaming):
		self.transport.registerProducer(producer, streaming)

	def unregisterProducer(self):
		self.transport.unregisterProducer()

	# overwrite

	def connection_made(self):
		pass

	def connection_open(self):
		pass

	def connection_lost(self, reason):
		pass

	def recv_data(self, data):
		"""Receive packet"""
		raise NotImplementedError("recv_data(self, data)")

	# twisted protocol callbacks

	def connectionMade(self):
		self.connection_made()

	def handshakeCompleted(self): # needs twisted-16.4.0. called after the tls connection has been established
		self.connection_open()

	def connectionLost(self, reason):
		self.connection_lost(reason)

	def dataReceived(self, data):
		"""called from twisted"""
		self._pos = 0
		#logging.debug("len(data): {}, pos: {}, length {}".format(len(data), self._pos, self._length))
		while len(data) >= self._pos + self._length - len(self._buffer):
			if self._buf_len is None: #if not self._buf_len doesn't permit 0
				#logging.debug("int:buf_len: {}".format(self._buf_len))
				missing = self._int_len - len(self._buffer)
				#logging.debug("int:missing: {}".format(missing))
				assert missing >= 0, missing
				self._buffer.append(data[self._pos:self._pos+missing])
				assert len(self._buffer) == self._int_len
				self._length = self._buf_len = unpack("!I", self._buffer.get())[0]
				#logging.debug("int:length: {}".format(self._length))
				self._buffer.clear()
				self._pos += missing #self._int_len
				#logging.debug("int:pos: {}".format(self._pos))
			else:
				#logging.debug("buf:buf_len: {}".format(self._buf_len))
				missing = self._buf_len - len(self._buffer)
				#logging.debug("buf:missing: {}".format(missing))
				assert missing >= 0, missing
				self._buffer.append(data[self._pos:self._pos+missing])
				assert len(self._buffer) == self._buf_len
				self.recv_data(self._buffer.get())
				self._buffer.clear()
				self._pos += missing #self._buf_len
				#logging.debug("buf:pos: {}".format(self._pos))
				self._buf_len = None
				self._length = self._int_len
				#logging.debug("int:length: {}".format(self._length))
		assert self._pos <= len(data), (self._pos, len(data))
		if self._pos < len(data):
			self._buffer.append(data[self._pos:])
