from __future__ import absolute_import, division, print_function, unicode_literals

import os
from pathlib import Path
from io import open

import cerpcerus
from cerpcerus.rpcbase import RPCUserError

from utils import randblob

def scandir_rec(path):
	for direntry in os.scandir(path):
		if direntry.is_dir():
			yield from scandir_rec(direntry)
		elif direntry.is_file():
			yield direntry

randomdata = randblob(1024*1024) # 16MB

class TestService(cerpcerus.rpc.DebugService):
	def __init__(self, reactor, conn):
		cerpcerus.rpc.DebugService.__init__(self, True)
		self.shared = Path("D:/PUBLIC").resolve(strict=True) # needs to be absolute, existing path

	def list(self):
		return tuple((str(Path(direntry).relative_to(self.shared)), direntry.stat().st_size) for direntry in scandir_rec(self.shared))

	def file(self, relpath, seek=0):
		try:
			path = self.shared.joinpath(relpath).resolve(strict=True)
		except FileNotFoundError:
			raise RPCUserError("Invalid file")

		try:
			path.relative_to(self.shared) # is requested file really within shared directory?
		except ValueError:
			raise RPCUserError("Invalid file")

		try:
			with open(path, "rb") as fr:
				fr.seek(seek)
				while True:
					data = fr.read(1024*1024)
					if not data:
						break
					yield data
		except OSError:
			raise RPCUserError("Invalid file")

	def infinite(self):
		while True:
			yield randomdata

class MySSLContextFactory(cerpcerus.GenericRPCSSLContextFactory):

	def __init__(self):
		cerpcerus.GenericRPCSSLContextFactory.__init__(self, "server.pem.crt", "server.pem.key", verify_ca = True)

	def valid_ca_cert_files(self):
		return ("client.pem.crt",)

if __name__ == "__main__":
	import logging
	logging.basicConfig(level=logging.DEBUG, format="%(levelname)s\t%(name)s\t%(funcName)s\t%(message)s")

	from twisted.internet import reactor
	service = cerpcerus.SeparatedService(TestService, reactor)
	ssl = MySSLContextFactory()
	cerpcerus.Server(reactor, 1337, ssl, service, interface="127.0.0.1")
	reactor.run()
