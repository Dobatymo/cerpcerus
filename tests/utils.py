import unittest

from cerpcerus.utils import args_str, SimpleBuffer

class TestSequenceFunctions(unittest.TestCase):

    def setUp(self):
        self.seq = range(10)

    def test_args_str(self):
        
        self.assertEqual(args_str((), {}), "")
        self.assertEqual(args_str(("asd", 1), {"a":"A"}), "'asd', 1, a='A'")
        self.assertEqual(args_str(("asd",), {}, max=2, app="!"), "'a!")

    def test_SimpleBuffer(self):
        b = SimpleBuffer()
        b.append("asd")
        self.assertEqual(len(b), 3)
        b.append("fgh")
        self.assertEqual(len(b), 6)
        self.assertEqual(b.get(), "asdfgh")
        b.clear()
        self.assertEqual(len(b), 0)
        self.assertEqual(b.get(), "")

if __name__ == '__main__':
    unittest.main()
