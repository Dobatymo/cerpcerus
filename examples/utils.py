from __future__ import absolute_import, division, print_function, unicode_literals

import random, string

from builtins import range

def randstring(maxlen, minlen=0):
	return "".join(random.choice(string.letters) for _ in range(random.randint(minlen, maxlen)))

def randblob(length):
	return bytes(random.randint(0, 255) for _ in range(length))
