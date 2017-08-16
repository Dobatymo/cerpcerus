from __future__ import absolute_import, division, print_function, unicode_literals

from twisted.trial import unittest
from twisted.internet import defer

from cerpcerus.convert_deferreds import bind_deferreds

class DeferredsTestCase(unittest.TestCase):
	def _test_void(self):
		pass

	def _test_1(self, a):
		return a

	def _test_2(self, a, b):
		return (a, b)

	def _test_3(self, a, b, c):
		return (a, b, c)

	def test_0v0d(self):
		bind_deferreds(self._test_void).addCallback(self.assertEqual, None)

	def test_1v0d(self):
		bind_deferreds(self._test_1, 1).addCallback(self.assertEqual, 1)

	def test_1v0d_fail(self):
		ret = bind_deferreds(self._test_void, 1)
		self.assertFailure(ret, TypeError)

	def test_0v1d(self):
		d = defer.Deferred()
		bind_deferreds(self._test_1, d).addCallback(self.assertEqual, 1)
		d.callback(1)

	def test_0v1d_fail(self):
		d = defer.Deferred()
		ret = bind_deferreds(self._test_void, d)
		d.callback(1)
		self.assertFailure(ret, TypeError)

	def test_1v1d(self):
		d = defer.Deferred()
		bind_deferreds(self._test_2, 1, d).addCallback(self.assertEqual, (1, 2))
		d.callback(2)

	def test_1v2d(self):
		d1 = defer.Deferred()
		d2 = defer.Deferred()
		bind_deferreds(self._test_3, 1, d1, d2).addCallback(self.assertEqual, (1, 2, 3))
		d1.callback(2)
		d2.callback(3)

	def test_0v2d_nonunique(self):
		d = defer.Deferred()
		bind_deferreds(self._test_2, d, d).addCallback(self.assertEqual, (1, 1))
		d.callback(1)
