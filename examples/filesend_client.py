from __future__ import print_function, absolute_import

import os.path, logging
from twisted.internet import reactor, defer

import cerpcerus

@defer.inlineCallbacks
def Task(path, files):
	try:
		ssl = cerpcerus.GenericRPCSSLContextFactory("client.pem.crt", "client.pem.key", False)
		conn = yield cerpcerus.Client(reactor, "127.0.0.1", 1337, "Server", ssl)
		print("Connected to server")
	except cerpcerus.rpcbase.NetworkError:
		print("Could not connect to server")
		reactor.callLater(0, reactor.stop)
		return

	for f in files:
		print("Downloading {}".format(f))
		name = os.path.basename(f)

		fullpath = os.path.join(path, name)
		try:
			with open(fullpath, "ab") as fa:
				size = fa.tell() # opened for append, so already at the end
				for result in conn._stream("file", f, size):
					try:
						res = yield result
						fa.write(res)
					except StopIteration:
						print("Finished downloading {} to {}".format(name, fullpath))
						break
					except Exception as e:
						print("Downloading {} failed: {}".format(name, e))
						break
		except IOError:
			logging.exception("Could not open file")
		except Exception:
			logging.exception("Downloading failed")

	yield conn._lose()
	reactor.callLater(0, reactor.stop)

if __name__ == "__main__":

	logging.basicConfig(level=logging.DEBUG, format="%(levelname)s\t%(name)s\t%(funcName)s\t%(message)s")

	import argparse

	parser = argparse.ArgumentParser(description="Download files")
	parser.add_argument("path")
	parser.add_argument("files", nargs="+")
	args = parser.parse_args()

	reactor.callWhenRunning(Task, args.path, args.files)
	reactor.run()
