from __future__ import absolute_import, division, print_function, unicode_literals

import queue, logging

from twisted.internet import defer, reactor, protocol

logger = logging.getLogger(__name__)

"""
call self.transport.pauseProducing() and self.transport.resumeProducing() if stream is sending too fast (queue gets too large
"""

class MultiDeferredIterator(object):

	"""should this be made pause/resume-able?
	should be stoppable for sure
	maybe the stream should include information if it can be paused

	if this stops the producer/transport, it will be stopped for all streams.
	It would be better to have on collector with one queue for all streams, so it can be stopped with regard to all streams.
	if every single iterator can pause/resume, there will be nterference among them
	"""

	def __init__(self):
		self.queue = queue.Queue()
		self.deferred = None
		self.transport = None # interfaces.IPushProducer

	# called by client

	def __iter__(self):
		return self

	def next(self): # __next__ python3, this can hang if user is not careful
		#self.transport.resumeProducing() # if queue too empty
		try:
			deferred = self.queue.get_nowait()
			return deferred
		except queue.Empty:
			self.deferred = defer.Deferred()
			return self.deferred

	def stop(self):
		pass

	def pause(self):
		pass

	def resume(self):
		pass

	# called from rpc

	def callback(self, val): # called multiple times
		#self.transport.pauseProducing() # if queue too full
		if self.deferred and not self.deferred.called:
			#logger.debug("call directly")
			self.deferred.callback(val)
		else:
			#logger.debug("add to queue")
			self.queue.put_nowait(defer.succeed(val))

	def errback(self, val):
		if self.deferred and not self.deferred.called:
			#logger.debug("call error directly")
			self.deferred.errback(val)
		else:
			#logger.debug("add error to queue")
			self.queue.put_nowait(defer.fail(val))

	def completed(self):
		return self.errback(StopIteration())

""" py 3 only
class AsyncMultiDeferredIterator:

	def __init__(self):
		self.queue = queue.Queue()
		self.deferred = None

	def __aiter__(self):
		return self

	async def __anext__(self):
		try:
			result = await self.queue.get_nowait()
			if result == "stop":
				raise StopAsyncIteration
			return result
		except queue.Empty:
			self.deferred = defer.Deferred()
			result = await self.deferred
			if result == "stop":
				raise StopAsyncIteration
			return result

	def callback(self, val): # called multiple times
		if self.deferred and not self.deferred.called:
			print("call directly")
			self.deferred.callback(val)
		else:
			print("add to queue")
			self.queue.put_nowait(defer.succeed(val))

	def errback(self, val):
		if self.deferred and not self.deferred.called:
			print("call directly")
			self.deferred.errback(val)
		else:
			print("add to queue")
			self.queue.put_nowait(defer.fail(val))

async def async_recv_stream(async_iter):
	print("start")
	async for deferred in async_iter:
		print(deferred)
	print("end")
	return True
"""

from .utils import sleep

@defer.inlineCallbacks
def recv_stream(async_iter):
	for deferred in async_iter:
		try:
			result = yield deferred
			print(result)
		except StopIteration:
			print("stop")
			break
		except GeneratorExit:
			logger.exception("GeneratorExit in recv")
		except Exception:
			logger.exception("Exception in recv")
		yield sleep(1)
		print("slept for a second")
	reactor.stop()

class Recv(protocol.Protocol):

	def __init__(self, mdit):
		self.mdit = mdit

	def dataReceived(self, data):
		if data == b"\x1b": # ESCAPE in TELNET
			self.mdit.stop()
		else:
			self.mdit.callback(data)

class RecvFactory(protocol.Factory):

	def __init__(self, mdit):
		self.mdit = mdit

	def buildProtocol(self, addr):
		return Recv(self.mdit)

def main1():
	mdit = MultiDeferredIterator()
	reactor.listenTCP(8000, RecvFactory(mdit))
	reactor.callWhenRunning(recv_stream, mdit)
	reactor.run()

def main2():
	import asyncio
	mdit = AsyncMultiDeferredIterator()
	reactor.listenTCP(8000, RecvFactory(mdit))
	reactor.callWhenRunning(defer.Deferred.fromFuture(asyncio.ensure_future(async_recv_stream)), mdit)
	reactor.run()

if __name__ == "__main__":
	main1()
