from __future__ import absolute_import, division, print_function, unicode_literals

import inspect, itertools
import unittest

from cerpcerus.utils import args_str, argspec_str, SimpleBuffer, Seq, IPAddr

class UtilsTestCase(unittest.TestCase):
	def test_args_str(self):
		result = args_str((), {})
		truth = ""
		self.assertEqual(result, truth)

		result = args_str(("asd", 1), {"a":("qwe", 2)}, maxlen=20, app="...")
		truth = "'asd', 1, a=('qwe', 2)"
		self.assertEqual(result, truth)

	def test_args_str_with_app(self):
		result = args_str(("a",), {}, maxlen=2, app=".")
		truth = "'a'"
		self.assertEqual(result, truth)

		result = args_str(("as",), {}, maxlen=2, app=".")
		truth = "'a."
		self.assertEqual(result, truth)

		result = args_str(("012345678",), {}, maxlen=10, app="...")
		truth = "'012345678'"
		self.assertEqual(result, truth)

		result = args_str(("0123456789",), {}, maxlen=10, app="...")
		truth = "'0123456789'"
		self.assertEqual(result, truth)

		result = args_str(("01234567890",), {}, maxlen=10, app="...")
		truth = "'01234567890'"
		self.assertEqual(result, truth)

		result = args_str(("012345678901",), {}, maxlen=10, app="...")
		truth = "'012345678..."
		self.assertEqual(result, truth)

	def test_args_str_without_app(self):
		result = args_str(("01234567",), {}, maxlen=10, app="")
		truth = "'01234567'"
		self.assertEqual(result, truth)

		result = args_str(("012345678",), {}, maxlen=10, app="")
		truth = "'012345678"
		self.assertEqual(result, truth)

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
		l = list(itertools.islice(Seq(0), 100))
		s = set(l)
		self.assertEqual(len(l), len(s), "Seq produced a nonunique value")
