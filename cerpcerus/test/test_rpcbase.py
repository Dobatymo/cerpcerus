from twisted.trial import unittest

from cerpcerus.rpcbase import IPAddr

class RPCBaseTestCase(unittest.TestCase):
    def test_ipaddr_conv(self):
        self.assertEqual(str(IPAddr("addr", "port")), "addr:port")
        self.assertEqual(repr(IPAddr("addr", "port")), "IPAddr('addr', 'port')")

    def test_ipaddr_eq(self):
        self.assertEqual(IPAddr("addr", "port"), IPAddr("addr", "port"))
        self.assertNotEqual(IPAddr("addr", "port"), IPAddr("asd", "qwe"))
