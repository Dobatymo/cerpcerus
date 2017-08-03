from __future__ import print_function, absolute_import

import sys, logging
from twisted.internet import reactor, defer

import cerpcerus
from cerpcerus.utils import pprint_introspect, sleep

logging.basicConfig(level=logging.DEBUG, format="%(levelname)s\t%(name)s\t%(funcName)s\t%(message)s")

ssl = cerpcerus.GenericRPCSSLContextFactory("client.pem.crt", "client.pem.key", False)

@defer.inlineCallbacks
def Task():
	try:
		conn = yield cerpcerus.Client(reactor, "127.0.0.1", 1337, "Server", ssl)
	except cerpcerus.rpcbase.NetworkError:
		print("Could not connect to server")
		reactor.callLater(0, Stop)
		return
	intro = yield conn.introspect()
	pprint_introspect(intro)

	try:
		yield conn.reactor()
	except cerpcerus.RPCInvalidArguments:
		logging.info("reactor() failed as expected")
	
	try:
		no_obj = conn.echo("asd")
		yield no_obj.asd()
	except cerpcerus.RPCInvalidObject:
		logging.info("no_obj.asd() failed as expected")
	
	calc1 = yield conn.Calc(1)
	calc2 = yield conn.Calc(2)
	intro = yield calc1.introspect()
	pprint_introspect(intro)
	calc1.add(10)
	calc2.add(10)
	res1 = yield calc1.get()
	res2 = yield calc2.get()
	print(res1, res2)

	yield conn.remote(calc1)

	d = yield dir(calc1)
	print(d)
	
	for result in conn._stream("random", 10, 10):
		try:
			res = yield result
			print("Stream", res)
			yield sleep(0.1)
		except StopIteration:
			break
		except Exception as e:
			print("something went wrong: {}".format(e))

	def range(x):
		yield from range(x)

	res = yield conn._call_with_streams("print_stream", range(3))
	print(res)

	#while False:
	#	result = yield conn.echo("0123456789"*100000)
	#	#print(result)
	yield sleep(5)
	yield conn._lose()
	reactor.callLater(0, Stop)

def Stop(*args):
	reactor.stop()

import txaio
txaio.start_logging(level="debug")

reactor.callWhenRunning(Task)
reactor.run()
