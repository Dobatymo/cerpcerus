import unittest

from cerpcerus.rpc import CallAnyPublic, RPCAttributeError

class RPCTestCase(unittest.TestCase):

    class TestObject(CallAnyPublic):

        attr = True
        _attr = True

        def _callpublic(self, name):
            return lambda: True

        def _callprivate(self, name):
            raise RPCAttributeError("{} instance has no attribute '{}'".format(type(self).__name__, name))

        def method(self):
            return True

        def _method(self):
            return True

    def test_CallAnyPublic(self):

        t = self.TestObject()
        self.assertEqual(t.attr, True)
        self.assertEqual(t._attr, True)
        self.assertEqual(t.method(), True)
        self.assertEqual(t._method(), True)
        self.assertEqual(t.public(), True)
        with self.assertRaises(RPCAttributeError):
            t._private()
