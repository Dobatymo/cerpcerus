from __future__ import print_function, absolute_import

import logging
from twisted.internet import reactor

import cerpcerus

class TestService(cerpcerus.rpc.DebugService):
	def __init__(self, reactor, conn):
		cerpcerus.rpc.DebugService.__init__(self, True)

	def file(self, path, seek=0):
		with open(path, "rb") as fr:
			fr.seek(seek)
			while True:
				data = fr.read(1024*1024)
				if not data:
					break
				yield data

class MySSLContextFactory(cerpcerus.GenericRPCSSLContextFactory):

	def __init__(self):
		cerpcerus.GenericRPCSSLContextFactory.__init__(self, "server.pem.crt", "server.pem.key", verify_ca = True)

	def valid_ca_cert_files(self):
		return ("client.pem.crt",)

if __name__ == "__main__":
	logging.basicConfig(level=logging.DEBUG, format="%(levelname)s\t%(name)s\t%(funcName)s\t%(message)s")

	service = cerpcerus.SeparatedService(TestService, reactor)
	ssl = MySSLContextFactory()
	cerpcerus.Server(reactor, 1337, ssl, service, interface="127.0.0.1")
	reactor.run()
