from __future__ import absolute_import, division, print_function, unicode_literals

import os.path, logging
from io import open
from twisted.internet import defer

import cerpcerus

@defer.inlineCallbacks
def Download(reactor, path, files):
	ssl = cerpcerus.GenericRPCSSLContextFactory("client.pem.crt", "client.pem.key", False)
	try:
		conn = yield cerpcerus.Client(reactor, "127.0.0.1", 1337, "Server", ssl)
		print("Connected to server")
	except cerpcerus.rpcbase.NetworkError:
		print("Could not connect to server")
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

@defer.inlineCallbacks
def List(reactor):
	try:
		ssl = cerpcerus.GenericRPCSSLContextFactory("client.pem.crt", "client.pem.key", False)
		conn = yield cerpcerus.Client(reactor, "127.0.0.1", 1337, "Server", ssl).addTimeout(10, reactor)
		print("Connected to server")
	except cerpcerus.rpcbase.NetworkError:
		print("Could not connect to server")
		return
	except defer.TimeoutError:
		print("Error: Timed out after 10 seconds")

	files = yield conn.list()
	for path, size in files:
		print(size, path)

	yield conn._lose()

if __name__ == "__main__":

	from twisted.internet import task

	logging.basicConfig(level=logging.DEBUG, format="%(levelname)s\t%(name)s\t%(funcName)s\t%(message)s")

	import argparse

	parser = argparse.ArgumentParser(description="Download files")
	parser.add_argument("action", choices=["list", "download"])
	parser.add_argument("path", nargs="?")
	parser.add_argument("files", nargs="*")
	args = parser.parse_args()

	if args.action == "list":
		task.react(List)
	elif args.action == "download":
		task.react(Download, (args.path, args.files))
