from __future__ import absolute_import, division, print_function, unicode_literals

import queue, logging

from twisted.internet import defer

from future.utils import PY2

if PY2:
	StopAsyncIteration = Exception

logger = logging.getLogger(__name__)

"""
call self.transport.pauseProducing() and self.transport.resumeProducing() if stream is sending too fast (queue gets too large
"""

class MultiDeferredIterator(object): # inherit from RemoteObjectGeneric?

	"""should this be made pause/resume-able?
	should be stoppable for sure
	maybe the stream should include information if it can be paused

	if this stops the producer/transport, it will be stopped for all streams.
	It would be better to have on collector with one queue for all streams, so it can be stopped with regard to all streams.
	if every single iterator can pause/resume, there will be interference among them
	"""

	def __init__(self, conn, sequid, classname):
		self._conn = conn
		self._sequid = sequid
		self._classname = classname

		self.queue = queue.Queue()
		self.deferred = None
		self.transport = None # interfaces.IPushProducer

	# called by client

	def abort(self): # this should be called from the generators .close() method as well to stop the server from sending
		self._conn._cancel_stream(self._sequid)

	def __iter__(self):
		return self

	def __next__(self): # this can hang if user is not careful
		#self.transport.resumeProducing() # if queue too empty
		try:
			deferred = self.queue.get_nowait()
			return deferred
		except queue.Empty:
			self.deferred = defer.Deferred()
			return self.deferred

	next = __next__

	def __aiter__(self):
		return self

	@defer.inlineCallbacks
	def __anext__(self):
		try:
			try:
				result = yield self.queue.get_nowait() # or yield from?
				defer.returnValue(result) # return result
			except queue.Empty:
				self.deferred = defer.Deferred()
				result = yield self.deferred # or yield from?
				defer.returnValue(result) # return result
		except StopIteration: # translate, as interface which is used by the user (iter/aiter) is unknown at time of raise
			raise StopAsyncIteration()

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

	def async_completed(self):
		return self.errback(StopAsyncIteration())

# tests

from twisted.internet import reactor, protocol

# python >= 3.5
""" syntax error for older python
async def async_recv_stream(async_iter):
	from twisted.internet import error

	print("start")
	try:
		async for result in async_iter:
			print(result)
			await sleep(1)
			print("slept for a second")

	except error.ConnectionDone:
		print("ConnectionDone")
	except error.ConnectionLost:
		print("ConnectionLost")
	print("end")
"""

# python <= 3.4
@defer.inlineCallbacks
def recv_stream(async_iter):
	print("start")
	for deferred in async_iter:
		try:
			result = yield deferred
			print(result)
		except StopIteration:
			print("end")
			break
		except GeneratorExit:
			logger.exception("GeneratorExit in recv")
			break
		except Exception:
			logger.exception("Exception in recv")
			break
		yield sleep(1)
		print("slept for a second")
	reactor.stop()

class Recv(protocol.Protocol):

	def __init__(self, mdit):
		self.mdit = mdit

	def dataReceived(self, data):
		if data == b"\x1b": # ESCAPE in TELNET
			#self.mdit.stop()
			self.mdit.completed()
		else:
			self.mdit.callback(data)

	def connectionLost(self, reason):
		self.mdit.errback(reason)

class RecvFactory(protocol.Factory):

	def __init__(self, mdit):
		self.mdit = mdit

	def buildProtocol(self, addr):
		return Recv(self.mdit)

def main1(): # connect with telnet
	mdit = MultiDeferredIterator()
	reactor.listenTCP(8000, RecvFactory(mdit))
	reactor.callWhenRunning(recv_stream, mdit)
	reactor.run()

def main2(): # connect with telnet
	from twisted.internet import task
	mdit = MultiDeferredIterator()
	reactor.listenTCP(8000, RecvFactory(mdit))
	task.react(lambda reactor: defer.ensureDeferred(async_recv_stream(mdit)))
	reactor.run()

if __name__ == "__main__":
	from utils import sleep
	main1()
