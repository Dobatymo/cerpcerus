import inspect, itertools
import unittest

from cerpcerus.utils import args_str, argspec_str, SimpleBuffer, Seq

class UtilsTestCase(unittest.TestCase):
    def test_args_str(self):
        str = args_str((), {})
        res = ""
        self.assertEqual(str, res)
        
        str = args_str(("asd", 1), {"a":("qwe", 2)}, max=20, app="...")
        res = "'asd', 1, a=('qwe', 2)"
        self.assertEqual(str, res)
        
    def test_args_str_with_app(self):
        str = args_str(("a",), {}, max=2, app=".")
        res = "'a'"
        self.assertEqual(str, res)

        str = args_str(("as",), {}, max=2, app=".")
        res = "'a."
        self.assertEqual(str, res)

        str = args_str(("012345678",), {}, max=10, app="...")
        res = "'012345678'"
        self.assertEqual(str, res)
        
        str = args_str(("0123456789",), {}, max=10, app="...")
        res = "'0123456789'"
        self.assertEqual(str, res)
        
        str = args_str(("01234567890",), {}, max=10, app="...")
        res = "'01234567890'"
        self.assertEqual(str, res)
        
        str = args_str(("012345678901",), {}, max=10, app="...")
        res = "'012345678..."
        self.assertEqual(str, res)

    def test_args_str_without_app(self):
        str = args_str(("01234567",), {}, max=10, app="")
        res = "'01234567'"
        self.assertEqual(str, res)

        str = args_str(("012345678",), {}, max=10, app="")
        res = "'012345678"
        self.assertEqual(str, res)

    def test_argspec_str(self):
        def func(a, b, c=1, d="2"): pass

        str = argspec_str("func", inspect.getargspec(func)._asdict())
        res = "func(a, b, c=1, d='2')"
        self.assertEqual(str, res)

    def test_argspec_str_vars(self):
        def func(*args, **kwargs): pass

        str = argspec_str("func", inspect.getargspec(func)._asdict())
        res = "func(*args, **kwargs)"
        self.assertEqual(str, res)

    def test_argspec_str_mix(self):
        def func(a, b=1, *args, **kwargs): pass

        str = argspec_str("func", inspect.getargspec(func)._asdict())
        res = "func(a, b=1, *args, **kwargs)"
        self.assertEqual(str, res)

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
