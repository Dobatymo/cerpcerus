import random, string

def randstring(length):
    return "".join(random.choice(string.letters) for i in xrange(random.randint(0, length)))

def randblob(length):
    return "".join(chr(random.randint(0,255)) for _ in xrange(length))
