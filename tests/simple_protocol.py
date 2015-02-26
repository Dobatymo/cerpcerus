import unittest
from twisted.test import proto_helpers

from cerpcerus.simple_protocol import SimpleProtocol

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

class TestSequenceFunctions(unittest.TestCase):

    message1 = "XXXXXXXXXX"
    packet1 = "\x00\x00\x00\x0aXXXXXXXXXX"
    message2 = "XXXXXXXXXX"
    packet2 = "\x00\x00\x00\x0aXXXXX"

    def setUp(self):
        self.sp = SimpleProtocol()
        self.tr = proto_helpers.StringTransport()
        self.sp.makeConnection(self.tr)

    def test_send(self):
        self.sp.send_data(self.message1)
        self.assertEqual(self.tr.value(), self.packet1)

    def test_trivialpacket(self):
        f = CallbackMock(self)
        self.sp.recv_data = f
        self.sp.dataReceived(self.packet1)
        f.check(self.message1)

    def test_incompletepacket(self):
        f = CallbackMock(self)
        self.sp.recv_data = f
        self.sp.dataReceived(self.packet2)
        f.check_not_called()

if __name__ == "__main__":
    unittest.main()
