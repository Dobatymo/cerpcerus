import sys, logging
from twisted.internet import reactor, defer

import cerpcerus
from cerpcerus.utils import sleep

class TestService(cerpcerus.DebugService):
	def __init__(self, reactor, conn):
		cerpcerus.Service.__init__(self, True)
		self.reactor = reactor #reactor and conn: security problem?
		self.conn = conn #use _OnConnect for conn

	def remote(self, remoteinstance):
		print(remoteinstance)

	#def _OnDisconnect(self):
	#	self.reactor.stop()

	def stream(self, echo): # make defer.inlineCallbacks? must be supported by pullproducer
		for i in range(10):
			yield echo

	@defer.inlineCallbacks
	def print_stream(self, stream):
		for result in stream:
			try:
				res = yield result
				print("Stream", res)
			except StopIteration:
				break
			except Exception as e:
				print("something went wrong: {}".format(e))

		return True

	class Calc(cerpcerus.Service):
		def __init__(self, num):
			cerpcerus.Service.__init__(self, True)
			self.num = num
		
		def add(self, num):
			self.num += num
		
		def sub(self, num):
			self.num -= num
		
		def get(self):
			return self.num

class MySSLContextFactory(cerpcerus.GenericRPCSSLContextFactory):

	def __init__(self):
		cerpcerus.GenericRPCSSLContextFactory.__init__(self, "server.pem.crt", "server.pem.key", verify_ca = True)

	def valid_ca_cert_files(self):
		return ("client.pem.crt",)

logging.basicConfig(level=logging.DEBUG, format="%(levelname)s\t%(name)s\t%(funcName)s\t%(message)s")
import txaio
txaio.start_logging(level="debug")
service = cerpcerus.SeparatedService(TestService, reactor)
ssl = MySSLContextFactory()

cerpcerus.Server(reactor, 1337, ssl, service, interface = "127.0.0.1")
reactor.run()
