from __future__ import absolute_import, division, print_function, unicode_literals

from builtins import str

import inspect
from itertools import islice
import unittest

from cerpcerus.utils import argspec_str, SimpleBuffer, Seq, IPAddr

class UtilsTestCase(unittest.TestCase):

	def test_argspec_str(self):
		def func(a, b, c=1, d="2"): pass

		result = argspec_str("func", inspect.getargspec(func)._asdict())
		truth = "func(a, b, c=1, d='2')"
		self.assertEqual(result, truth)

	def test_argspec_str_vars(self):
		def func(*args, **kwargs): pass

		result = argspec_str("func", inspect.getargspec(func)._asdict())
		truth = "func(*args, **kwargs)"
		self.assertEqual(result, truth)

	def test_argspec_str_mix(self):
		def func(a, b=1, *args, **kwargs): pass

		result = argspec_str("func", inspect.getargspec(func)._asdict())
		truth = "func(a, b=1, *args, **kwargs)"
		self.assertEqual(result, truth)

	def test_ipaddr_conv(self):
		self.assertEqual(str(IPAddr("addr", "port")), "addr:port")
		self.assertEqual(repr(IPAddr("addr", "port")), "IPAddr('addr', 'port')")

	def test_ipaddr_eq(self):
		self.assertEqual(IPAddr("addr", "port"), IPAddr("addr", "port"))
		self.assertNotEqual(IPAddr("addr", "port"), IPAddr("asd", "qwe"))

	def test_SimpleBuffer(self):
		b = SimpleBuffer()
		self.assertEqual(len(b), 0)
		self.assertEqual(b.get(), "")
		b.append("asd")
		self.assertEqual(len(b), 3)
		self.assertEqual(b.get(), "asd")
		b.append("fgh")
		self.assertEqual(len(b), 6)
		self.assertEqual(b.get(), "asdfgh")
		b.clear()
		self.assertEqual(len(b), 0)
		self.assertEqual(b.get(), "")

	def test_Seq(self):
		l = list(islice(Seq(0), 100))
		s = set(l)
		self.assertEqual(len(l), len(s), "Seq produced a nonunique value")
