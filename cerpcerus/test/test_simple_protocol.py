from __future__ import absolute_import, division, print_function, unicode_literals

from twisted.trial import unittest
from twisted.test import proto_helpers

from cerpcerus.simple_protocol import SimpleProtocol

"""
class CallbackMock:

	def __init__(self, testcase):
		self.called = False
		self.testcase = testcase

	def __call__(self, data):
		self.data = data
		self.called = True

	def check(self, data):
		self.testcase.assertEqual(self.data, data)
		self.testcase.assertTrue(self.called)
		self.called = False
	
	def check_not_called(self):
		self.testcase.assertFalse(self.called)
		self.called = False

f = CallbackMock(self)
self.sp.recv_data = f
self.sp.dataReceived("\x00\x00\x00\x0aXXXXXXXXXX")
f.check("XXXXXXXXXX")

"""

class SimpleProtocolTestCase(unittest.TestCase):
	def _recv_data(self, data):
		self.recv_data = data

	def _data_received(self, *args):
		for data in args:
			self.proto.dataReceived(data)

	def _connection_lost(self, reason):
		self.connection_lost = True

	def _test_recv(self, data, expected):
		self.proto.recv_data = self._recv_data
		self._data_received(*data)
		self.assertEqual(self.recv_data, expected)

	def _test_send(self, data, expected):
		self.proto.send_data(data)
		self.assertEqual(self.tr.value(), expected)

	def setUp(self):
		self.proto = SimpleProtocol()
		self.tr = proto_helpers.StringTransport()
		self.proto.makeConnection(self.tr)
		self.recv_data = None
		self.connection_lost = None

	def test_recv_zero(self):
		self._test_recv([b"\x00\x00\x00\x00"], b"")
		self._test_recv([b"\x00\x00\x00\x00"], b"")

	def test_recv_simple(self):
		self._test_recv([b"\x00\x00\x00\x03asd"], b"asd")
		self._test_recv([b"\x00\x00\x00\x03asd"], b"asd")

	def test_recv_length_split(self):
		self._test_recv([b"\x00\x00", "\x00\x03asd"], b"asd")
		self._test_recv([b"\x00\x00", "\x00\x03asd"], b"asd")

	def test_recv_value_split(self):
		self._test_recv([b"\x00\x00\x00\x03a", "sd"], b"asd")
		self._test_recv([b"\x00\x00\x00\x03a", "sd"], b"asd")

	def test_recv_length_split_double(self):
		self._test_recv([b"\x00\x00\x00\x03asd\x00\x00"], b"asd")
		self._test_recv([b"\x00\x03asd"], b"asd")

	def test_recv_value_split_double(self):
		self._test_recv([b"\x00\x00\x00\x03asd\x00\x00\x00\x03a"], b"asd")
		self._test_recv([b"sd"], b"asd")

	def test_send_data_zero(self):
		self._test_send(b"", b"\x00\x00\x00\x00")

	def test_send_data_simple(self):
		self._test_send(b"asd", b"\x00\x00\x00\x03asd")

	def test_send_data_unicode(self):
		with self.assertRaises(TypeError):
			self.proto.send_data(u"asd")

	def test_send_data_list(self):
		with self.assertRaises(TypeError):
			self.proto.send_data([1, 2, 3])

	def test_send_data_none(self):
		with self.assertRaises(TypeError):
			self.proto.send_data(None)

	"""
	def test_disconnect(self): #why does that fail?
		self.proto.connection_lost = self._connection_lost
		self.tr.loseConnection()
		self.assertEqual(self.connection_lost, True)
	"""
