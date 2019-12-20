from __future__ import absolute_import, division, print_function, unicode_literals

from builtins import str
from future.utils import iteritems

import logging, queue, itertools
from functools import partial

import msgpack
from OpenSSL import SSL, crypto, __version__ as pyopenssl_version
from twisted.internet import ssl, defer, error
from genutility.debug import args_str
from genutility.tls import get_pubkey_from_x509

from .utils import cert_info, Seq, IPAddr
from .rpc import RemoteObject, RemoteInstance, RemoteResult, RPCAttributeError, RPCInvalidArguments, RPCInvalidObject, NotAuthenticated, ObjectId
from .iter_deferred import MultiDeferredIterator

#pylint: disable=protected-access

logger = logging.getLogger(__name__)

"""
debug: errors which result from wrong usage on remote side (eg. calling non existing function)
info: errors which could result from above or below case (eg. accessing invalid object ids)
warning: errors which result from intentional wrong usage of protocol (eg. sending wrongly formatted data)
exception: unexpected exceptions which point to source code errors
error:
"""

L = ARROW_POINTING_DOWNWARDS_THEN_CURVING_RIGHTWARDS = "\u2937"

class RPCUserError(Exception):
	"""Can by raised by functions in RPC service to signal user defined error codes"""

class RPCError(Exception):
	"""Signals a general RPC error"""

class NetworkError(Exception):
	"""Signals a general RPC network error"""

class ConnectionLost(NetworkError):
	"""Raised when the RPC connection is lost or closed"""

class UnknownPeer(Exception):
	"""Raised by Friends if peer name is not known"""

class ResourceExhaustedError(Exception):
	"""Raised by producer when queue is full"""

class ConnectionClosedError(Exception):
	"""Raised by producer when trying to send data on a closed connection"""

class IFriends(object):

	"""Interface which defines all methods which friend classes must implement"""

	def identify(self, public_key): # was: key_to_name
		"""return name for key, raise on unknown key"""
		raise NotImplementedError()

	def establish_connection(self, name, conn): # was: update_connection_by_name
		"""called when connection is successful"""

	def reset_connection(self, name, conn):
		"""called on connection lost, should invalidate/delete connection object"""

	def start_connecting(self, name, deferred):
		"""called by client to set connection progress deferred"""
		logger.debug("to %s: %s", name, deferred)

	def reset_connecting(self, name, deferred):
		"""called by client, when connecting done or failed"""
		logger.debug("to %s: %s", name, deferred)

	def get_connection(self, name): # was: get_by_name
		"""used by client to see if connection was established from the other side"""
		raise NotImplementedError()

	def set_addr(self, name, addr): # was: update_addr_by_name
		raise NotImplementedError()

	def update_by_addr(self, addr, conn): #used?
		raise NotImplementedError()

class SameFriend(IFriends):

	"""Simple implementation of IFriends interface.
	Uses the same name for every connection.
	"""

	def __init__(self, name):
		self.name = name

	def identify(self, public_key):
		return self.name

	def get_connection(self, name):
		return

	def update_by_addr(self, addr, conn):
		pass

	def set_addr(self, name, addr):
		pass

class AllFriends(IFriends):

	"""Simple implementation of IFriends interface.
	Assigns a unique number as name for every key. Thus it accepts every key as friend.
	"""

	def __init__(self):
		self.friends = {}
		self.seq = Seq(0)

	def identify(self, public_key):
		try:
			return self.friends[public_key]
		except KeyError:
			self.friends[public_key] = next(self.seq)
			return self.friends[public_key]

	def get_connection(self, name):
		return

	def update_by_addr(self, addr, conn):
		pass

	def set_addr(self, name, addr):
		pass

from types import GeneratorType
try:
	from collections.abc import Generator
except ImportError: # python < 3.3
	class Generator: pass

class Streamable(Generator):

	def close(self):
		""" called when iteration is not finished, so resources can be cleaned up """
		pass

	def send(self, value):
		raise NotImplementedError()

	def throw(self, mytype, value=None, traceback=None):
		raise NotImplementedError()

	def __iter__(self):
		return self

	def __next__(self):
		""" returns a piece of data """
		raise NotImplementedError()

	def __repr__(self):
		return "'<Streamable>'"

	next = __next__ # py2

# unfinished, untested
class PushProducerRoundRobin(object):
	def __init__(self, consumer):
		self.consumer = consumer
		self.queue = queue.Queue()
		self.pushing = True

	def add(self, msg):
		self.queue.put_nowait(msg) #raises if queue is full, can dataReceived be slowed? (by pauseProducing?)
		if self.pushing:
			self.resumeProducing()

	def resumeProducing(self):
		self.pushing = True
		try:
			while self.pushing:
				msg = self.queue.get_nowait()
				if isinstance(msg, GeneratorType):
					self.consumer.write(next(msg))
					self.queue.put_nowait(msg)
				else:
					self.consumer.write(msg)

		except queue.Empty:
			pass

	def pauseProducing(self):
		self.pushing = False

	def stopProducing(self):
		#self.consumer.unregisterProducer()
		pass

from twisted.internet.threads import deferToThread
class file_sender(object):

	""" can be returned from service methods to asynchronously stream files """

	def __init__(self, path, buffer=1024*1024):
		self.fp = open(path, "rb")
		self.buffer = buffer
		self.finished = False

	def __iter__(self):
		return self

	def _read(self):
		data = self.fp.read(self, self.buffer)
		if not data:
			self.fp.close()
			raise StopIteration
		return data

	def __next__(self):
		return deferToThread(self._read)

	next = __next__ # py2

class RPCPullProducer(object):

	"""
	it should be able to use this producer on both sides.
	for sending RPC requests and streams, and replying to RPC and stream requests.

	in the worst case, the producer is un/re-registered all the time. is this performance relevant?

	it should be possible to use Pull AND/OR Push producers,
	both work basically the same way. except one of them might be faster
	Pull basically tells the consumer to get more data. the loop is implicit in the consumer.
	Push directly gives the data to the consumer. the explicit loop blocks the program
	(similar to what the implicit does), but it will be paused and gives up execution that way.
	"""

	def __init__(self, consumer):
		assert hasattr(consumer, "registerProducer") and hasattr(consumer, "unregisterProducer")
		# change SimpleProtocol to real consumer (with IConsumer)? then this can be verified here. (must just write() instead of send_data()

		self.consumer = consumer
		self.registered = False
		self.closed = False

	### msgpack hooks

	RemoteInstanceID = 0x05
	StreamableID = 0x06

	def default(self, obj):
		""" converts `RemoteInstance` and `Streamable` to msgpack types """

		if isinstance(obj, RemoteInstance):
			return msgpack.ExtType(self.RemoteInstanceID, msgpack.dumps(obj.__getstate__(), use_bin_type=True))
		elif isinstance(obj, Streamable):
			return msgpack.ExtType(self.StreamableID, b"")
		return obj

	def add(self, senders, iterable):
		""" called from RPC """

		if self.closed:
			raise ConnectionClosedError("No new streams can be added")

		self._add(senders, iterable)
		if not self.registered: # registerProducer throws RuntimeError if registered again
			self.consumer.registerProducer(self, streaming=False) # calls resumeProducing
			self.registered = True

	def send_msgpack(self, msg):
		assert msg is not None
		assert self.closed is False
		self.consumer.send_data(msgpack.dumps(msg, use_bin_type=True, encoding="utf-8", default=self.default))

	# server sender (to client)

	def send_result(self, sequid, result):
		msg = (MessageTypes.STREAM_RESULT, sequid, result)
		self.send_msgpack(msg)

	def send_end(self, sequid):
		msg = (MessageTypes.STREAM_END, sequid)
		self.send_msgpack(msg)

	def send_error(self, sequid, errortype, errormsg=None):
		msg = (MessageTypes.STREAM_ERROR, sequid, errortype, errormsg)
		self.send_msgpack(msg)

	# client sender (to server)

	def send_argument(self, sequid, arg_pos, result):
		msg = (MessageTypes.STREAM_ARGUMENT, sequid, arg_pos, result)
		self.send_msgpack(msg)

	def send_argument_end(self, sequid, arg_pos):
		msg = (MessageTypes.ARGUMENT_END, sequid, arg_pos)
		self.send_msgpack(msg)

	def send_argument_error(self, sequid, arg_pos, code):
		msg = (MessageTypes.ARGUMENT_ERROR, sequid, arg_pos, code, None)
		self.send_msgpack(msg)

	# overwrite

	def _add(self, senders, iterable):
		"""should be overwritten. called from `add()` """

		raise NotImplementedError

	def resumeProducing(self):
		"""should be overwritten. called from consumer """

		raise NotImplementedError

	def stopProducing(self):
		# consumer has died
		self.closed = True
		#self.consumer.unregisterProducer()
		logger.debug("Consumer interrupted producer")

	def closeOff(self):
		self.closed = True

class PullProducerQueue(RPCPullProducer):

	"""
	implementation of a `RPCPullProducer`.
	accepts iterables which return blobs or deferreds.
	iterables are iterated and sent when requested
		blobs are written to consumer instantly.
		deferreds will have write callbacks added and execution is given up until result is ready.
	"""

	def __init__(self, consumer, maxsize=0):
		RPCPullProducer.__init__(self, consumer)
		self.queue = queue.Queue(maxsize) # use queue size to signal high resource usage
		self.current = None

	def _add(self, senders, iterable):
		assert isinstance(iterable, GeneratorType)
		try:
			self.queue.put_nowait((senders, iterable)) #raises if queue is full, can dataReceived be slowed? (by pauseProducing?), just send resource error
		except queue.Full:
			raise ResourceExhaustedError("Send queue is full")
		#should already call deferred here if buffer is empty (and add to buffer)

	def _write(self, send_result, send_error, result):
		if isinstance(result, defer.Deferred):
			result.addCallbacks(partial(self._write, send_result, send_error), partial(self._error, send_error)) # is the chain processing here correct?
		else:
			send_result(result)

	def _error(self, send_error, failure):
		send_error(RPCBase.ERRORS.Deferred)
		# stop on error?

	def cancel(self, sequid):

		""" cancel stream. interrupts active stream or removes inactive stream from queue """

		raise NotImplementedError("Cannot cancel streams in queue yet...")

		# first try to stop currently active iterable
		senders, sequid_, iterable = self.current
		if sequid == sequid_:
			self.current = None
			send_error(RPCBase.ERRORS.Cancelled)
			return

		# next, remove item from queue
		pass
		return

		# last
		# sequid not found, call probably already completed or sequid was invalid in the first place
		logger.debug("Tried to cancel invalid stream [%s]", sequid) # fixme: is .debug() here correct?

	def resumeProducing(self):

		""" handles currently active iterable (send data, error or finalize current stream)
			or retrieves a new iterable from queue.
			If the queue is empty, it unregisters from consumer.
		"""

		try:
			if not self.current:
				self.current = self.queue.get_nowait()

			(send_result, send_end, send_error), iterable = self.current
			try:
				""" if next() raises exception, than all following calls to next()
					will just raise StopIteration.
					this way streams cannot returns multiple errors,
					which means we can stop on error"""
				self._write(send_result, send_error, next(iterable))
			except StopIteration:
				send_end()
				self.current = None
			except RPCUserError as e:
				send_error(RPCBase.ERRORS.UserError, e.args)
				self.current = None
			except Exception:
				send_error(RPCBase.ERRORS.GeneralError)
				logger.exception("Calling iterator failed")
				self.current = None

		except queue.Empty:
			#logger.debug("Producer has run out of data, unregistering...")
			self.consumer.unregisterProducer()
			self.registered = False

class PullProducerRoundRobin(RPCPullProducer):
	pass

class RemoteResultDeferred(defer.Deferred, RemoteResult):

	def __init__(self, conn, sequid, classname):
		defer.Deferred.__init__(self)
		RemoteResult.__init__(self, conn, sequid, classname)

	def __getattr__(self, name):
		# This fix works and is needed, because Deferred uses `getattr` internally.
		# So calls are redirected back to the correct class.
		# External calls should work as intended.
		return getattr(defer.Deferred, name)

	def __repr__(self):
		return "'<RemoteResultDeferred object {} [{}] to {} at {}>'".format(self._classname, self._sequid, self._conn.name, self._conn.addr)

	def abort(self):
		# should this method be called `cancel`? Deferred.cancel already exists and is called by timeout for example.
		""" Cancels the remote call. Will only work if the server using a queuing system,
			threads or the like for deferreds and the abort call is processed
			before the call in the queue. """

		self._conn._cancel_call(self._sequid) # _conn from RemoteObjectGeneric

class RPCProtocolBase(object):

	def connection_made(self):
		"""Connection started (raw tcp)"""
		raise NotImplementedError("connection_made(self)")

	def connection_open(self):
		"""Connection established (full protocol)"""
		raise NotImplementedError("connection_open(self)")

	def connection_lost(self, reason):
		"""Connection lost"""
		raise NotImplementedError("connection_lost(self, reason)")

	def recv_data(self, data):
		"""Receive packet with binary data"""
		raise NotImplementedError("recv_data(self, data)")

# Decorator to avoid copy&paste
def ValidateConnection(func):
	# type: (Callable, ) -> Callable

	""" decorator which raises `NotAuthenticated` if the connection is not in a valid state """

	def check(self, *args, **kwargs):
		if self.authed:
			return func(self, *args, **kwargs)
		else:
			if self.closed:
				if self.name:
					raise NotAuthenticated("Connection to {} already closed".format(self.name))
				else:
					raise NotAuthenticated("Connection to {} already closed".format(self.addr))
			else:
				raise NotAuthenticated("Connection to {} not authenticated".format(self.addr))
	return check

class MessageTypes:
	# CLIENT TO SERVER
	NOTIFY = 1
	NOTIFYMETHOD = 2
	NOTIFYMETHOD_BY_RESULT = 3

	NOTIFY_WITH_STREAMS = 4
	NOTIFYMETHOD_WITH_STREAMS = 5
	NOTIFYMETHOD_BY_RESULT_WITH_STREAMS = 6

	CALL = 11
	CALLMETHOD = 12
	CALLMETHOD_BY_RESULT = 13

	CALL_WITH_STREAMS = 14
	CALLMETHOD_WITH_STREAMS = 15
	CALLMETHOD_BY_RESULT_WITH_STREAMS = 16

	DELINSTANCE = 21
	DELINSTANCE_BY_RESULT = 22
	CANCEL_CALL = 23
	CANCEL_STREAM = 24

	STREAM_ARGUMENT = 25
	ARGUMENT_END = 26
	ARGUMENT_ERROR = 27

	# SERVER TO CLIENT
	RESULT = 31
	OBJECT = 32
	ERROR = 33
	STREAM_RESULT = 34
	STREAM_ERROR = 35
	STREAM_END = 36

class RPCBase(RPCProtocolBase):

	class ERRORS: #todo: named tuple?
		GeneralError = 0
		NoSuchFunction = 1 # called function or method does not exist
		WrongArguments = 2 # function or method called with wrong arguments
		UserError = 3 # function or method returned user defined error code
		NoService = 4 # tried to call function or method on endpoint which does not provide a service
		Deferred = 5 # error occurred while waiting on deferred
		InvalidObject = 6 # invalid object was referenced
		ResourceExhausted = 7 # some resource was exhausted...

	connids = Seq(0)

	def __init__(self, friends, transport_protocol):
		# type: (IFriends, ) -> None

		self.connid = next(self.connids)
		self._sequid = Seq(0) #was static/class var before
		self.friends = friends
		self.tp = transport_protocol
		self.name = None
		self.addr = None
		self.service = None
		self._deferreds = {} # deferreds saved on client side to process normal calls
		self._multideferreds = {} # deferreds saved on client side to process streaming calls
		self._calldeferreds = {} # deferreds saved on server side to process incoming streaming calls
		self.waitingcalls = {} # deferreds saved on server side which are not completed yet
		self.results = {} # map sequids to objectids
		self.authed = False
		self.closed = None

		self.sender = PullProducerQueue(self.tp) # tp is consumer

	### Call on protocol

	def authenticate(self, name, pubkey):
		"""Authenticates a user with pubkey.
		Should only be called from outside if you know what you are doing!"""

		self.authed = True
		self.name = name
		self.authenticated(pubkey)
		logger.debug("Connection accepted: %s is now %s", self.addr, self.name)
		self.service._OnAuthenticated() #use RemoteObject(self) as argument?

	### overwrite

	def authenticated(self, key):
		""" Called wth `key` if connection is authenticated. To be overwritten. """
		pass

	### msgpack hooks

	RemoteInstanceID = 0x05
	StreamableID = 0x06

	def ext_hook(self, n, obj):
		if n == self.RemoteInstanceID:
			objectid, classname = msgpack.loads(obj, use_list=False, raw=False)
			return RemoteInstance(self, objectid, classname)
		elif n == self.StreamableID:
			return Streamable()
		return obj

	# argument conversion for streams

	def filter_args(self, args, sequid):
		for arg_pos, arg in enumerate(args): # only handle positional args for now
			if isinstance(arg, GeneratorType):
				self.stream_msgpack_call(sequid, arg_pos, arg)
				yield Streamable() # (sequid, arg_pos)
			else:
				yield arg

	def defilter_args(self, sequid, name, args):
		""" this could be put in msgpack custom unpacking also.
			but this would require sending the sequid and argument position.
			does not handles keyword arguments right now.
		"""

		for arg_pos, arg in enumerate(args):
			if isinstance(arg, Streamable):
				deferred = MultiDeferredIterator()
				# fixme: what are the correct arguments here?
				# should it be possible to cancel specific arg_pos streams, or just all of them?
				#deferred = MultiDeferredIterator(self, sequid, name)
				self._calldeferreds[(sequid, arg_pos)] = (deferred, name)
				#self._calldeferreds[sequid][arg_pos] = (deferred, name)
				yield deferred
			else:
				yield arg

	### converting messages <-> calls

	def _success(self, sequid, result): # check for GeneratorType also
		del self.waitingcalls[sequid]
		if isinstance(result, ObjectId):
			self.send_msgpack((MessageTypes.OBJECT, sequid, int(result))) # there is no automatic conversion for ObjectId so far
		else:
			self.send_msgpack((MessageTypes.RESULT, sequid, result))

	def _failure(self, sequid, failure):
		del self.waitingcalls[sequid]

		if isinstance(failure, defer.CancelledError):
			# because Deferred()s are not created by library code, we cannot pass a canceller
			# parameter to initializer and thus have to translate cancelled errors here.
			# the canceller set by user code will be called so the operation can be canceled.
			msg = (MessageTypes.ERROR, sequid, self.ERRORS.Cancelled, None)
		else:
			msg = (MessageTypes.ERROR, sequid, self.ERRORS.Deferred, None)
			logger.exception(failure.getErrorMessage())
		self.send_msgpack(msg)

	def proc_notifymethod(self, objectid, name, args, kwargs):
		assert isinstance(name, str)
		assert self.service

		try:
			self.service._callmethod(self.connid, objectid, name, *args, **kwargs)
		except RPCUserError:
			logger.info("%sUser Error", L)
		except RPCInvalidObject:
			logger.info("%sInvalid Object %s", L, objectid)
		except RPCAttributeError:
			logger.debug("%sNo Such Method %s", L, name)
		except RPCInvalidArguments:
			logger.debug("%sWrong Arguments", L)
		except Exception:
			logger.exception("%sRPC %s(%s) failed", L, name, args_str(args, kwargs))

	def proc_call(self, sequid, name, args, kwargs):
		assert isinstance(name, str)
		assert self.service

		try:
			#if name.startswith("_") check not needed. Service does that and raises RPCAttributeError

			result = self.service._call(self.connid, name, *args, **kwargs)
			print("local yielded result of type:", type(result))
			if isinstance(result, defer.Deferred):
				self.waitingcalls[sequid] = result
				result.addCallbacks(partial(self._success, sequid), partial(self._failure, sequid))
				return
			elif isinstance(result, ObjectId):
				self.results[sequid] = result
				msg = (MessageTypes.OBJECT, sequid, int(result)) # there is no automatic conversion for ObjectId so far
			elif isinstance(result, GeneratorType):
				try:
					self.stream_msgpack(sequid, result)
					return
				except ResourceExhaustedError:
					msg = (MessageTypes.ERROR, sequid, self.ERRORS.ResourceExhausted, None)
				except ConnectionClosedError:
					logger.warning("Tried to stream result on closed connection")
			else:
				msg = (MessageTypes.RESULT, sequid, result)

		except RPCUserError as e:
			msg = (MessageTypes.ERROR, sequid, self.ERRORS.UserError, e.args)
			logger.info("%sUser Error", L)
		except RPCAttributeError as e:
			msg = (MessageTypes.ERROR, sequid, self.ERRORS.NoSuchFunction, None)
			logger.debug("%sNo Such Function %s [%s]", L, name, sequid)
		except RPCInvalidArguments as e:
			msg = (MessageTypes.ERROR, sequid, self.ERRORS.WrongArguments, None)
			logger.debug("%sWrong Arguments [%s]", L, sequid)
		except Exception as e:
			msg = (MessageTypes.ERROR, sequid, self.ERRORS.GeneralError, None)
			logger.exception("%sRPC %s(%s) [%s] failed", L, name, args_str(args, kwargs), sequid)

		return msg

	def proc_callmethod(self, sequid, objectid, name, args, kwargs):
		assert isinstance(name, str)
		assert self.service

		try:
			result = self.service._callmethod(self.connid, objectid, name, *args, **kwargs)
			print("local yielded result of type:", type(result))
			if isinstance(result, defer.Deferred):
				self.waitingcalls[sequid] = result
				result.addCallbacks(partial(self._success, sequid), partial(self._failure, sequid))
				return
			elif isinstance(result, ObjectId):
				self.results[sequid] = result
				msg = (MessageTypes.OBJECT, sequid, int(result))
			elif isinstance(result, GeneratorType):
				try:
					self.stream_msgpack(sequid, result)
					return
				except ResourceExhaustedError:
					msg = (MessageTypes.ERROR, sequid, self.ERRORS.ResourceExhausted, None)
				except ConnectionClosedError:
					logger.warning("Tried to stream result on closed connection")
			else:
				msg = (MessageTypes.RESULT, sequid, result)

		except RPCUserError as e:
			msg = (MessageTypes.ERROR, sequid, self.ERRORS.UserError, e.args)
			logger.info("%sUser Error", L)
		except RPCInvalidObject as e:
			msg = (MessageTypes.ERROR, sequid, self.ERRORS.InvalidObject, None)
			logger.info("%sInvalid Object %s", L, objectid)
		except RPCAttributeError as e:
			msg = (MessageTypes.ERROR, sequid, self.ERRORS.NoSuchFunction, None)
			logger.debug("%sNo Such Method %s [%s]", L, name, sequid)
		except RPCInvalidArguments as e:
			msg = (MessageTypes.ERROR, sequid, self.ERRORS.WrongArguments, None)
			logger.debug("%sWrong Arguments [%s]", L, sequid)
		except Exception as e:
			msg = (MessageTypes.ERROR, sequid, self.ERRORS.GeneralError, None)
			logger.exception("%sRPC %s(%s) [%s] failed", L, name, args_str(args, kwargs), sequid)

		return msg

	def proc_delinstance(self, objectid):
		try:
			self.service._delete(self.connid, objectid)
		except RPCInvalidObject:
			logger.info("Tried to delete invalid Object %s", objectid)
		except Exception:
			logger.exception("RPC delete object %s failed", objectid)

	def recv_msgpack(self, msg):
		try:
			type = msg[0]
		except (IndexError, TypeError):
			logger.warning("Received invalid formatted RPC message")
			return
		except: # replace with Exception for py3
			# import exceptions #msgpack 0.4.8 throws TypeError from this module...
			logger.exception("Received invalid formatted RPC message")
			return

		"""
		problems:
		it would be nice to only save object results in notify calls, because they don't return anything normally so it would make sense to keep
		track of the objects. but notify calls don't have sequids, so they cannot be associated (only real calls have sequids).
		also no error messages can be send in case something goes wrong with notifies
		=> so i guess normal calls are the only solution
		"""

		try:
			if type == MessageTypes.NOTIFY:
				name, args, kwargs = msg[1:]

				logger.debug("notifying local %s(%s)", name, args_str(args, kwargs))
				if self.service:
					try:
						self.service._call(self.connid, name, *args, **kwargs)
					except RPCUserError:
						logger.info("%sUser Error", L)
					except RPCAttributeError:
						logger.debug("%sNo Such Function %s", L, name)
					except RPCInvalidArguments:
						logger.debug("%sWrong Arguments", L)
					except Exception:
						logger.exception("%sRPC %s(%s) failed", L, name, args_str(args, kwargs))
				else:
					logger.debug("No Service")

			elif type == MessageTypes.NOTIFYMETHOD:
				objectid, name, args, kwargs = msg[1:]

				logger.debug("notifying local method [%s].%s(%s)", objectid, name, args_str(args, kwargs))
				if self.service:
					self.proc_notifymethod(objectid, name, args, kwargs)
				else:
					logger.debug("No Service")

			elif type == MessageTypes.NOTIFYMETHOD_BY_RESULT:
				previous_sequid, name, args, kwargs = msg[1:]

				logger.debug("notifying local method on result [%s].%s(%s)", previous_sequid, name, args_str(args, kwargs))
				if self.service:
					try:
						objectid = self.results[previous_sequid]
						self.proc_notifymethod(objectid, name, args, kwargs)
					except KeyError:
						logger.info("Invalid Object %s", previous_sequid)
				else:
					logger.debug("No Service")

			# *_WITH_STREAMS

			elif type == MessageTypes.CALL:
				sequid, name, args, kwargs = msg[1:]

				logger.debug("calling local %s(%s) [%s]", name, args_str(args, kwargs), sequid)
				if self.service:
					msg = self.proc_call(sequid, name, args, kwargs)
					if msg is None:
						return
				else:
					msg = (MessageTypes.ERROR, sequid, self.ERRORS.NoService, None)
					logger.debug("No Service [%s]", sequid)

				self.send_msgpack(msg)

			elif type == MessageTypes.CALL_WITH_STREAMS:
				sequid, name, args, kwargs = msg[1:]

				logger.debug("calling local with stream %s(%s) [%s]", name, args_str(args, kwargs), sequid)
				if self.service:
					args = self.defilter_args(sequid, name, args) # only handle positional args for now
					msg = self.proc_call(sequid, name, args, kwargs)
					if msg is None:
						return
				else:
					msg = (MessageTypes.ERROR, sequid, self.ERRORS.NoService, None)
					logger.debug("No Service [%s]", sequid)

				self.send_msgpack(msg)

			elif type == MessageTypes.CALLMETHOD:
				sequid, objectid, name, args, kwargs = msg[1:]

				logger.debug("calling local method [%s].%s(%s) [%s]", objectid, name, args_str(args, kwargs), sequid)
				if self.service:
					msg = self.proc_callmethod(sequid, objectid, name, args, kwargs)
					if msg is None:
						return
				else:
					msg = (MessageTypes.ERROR, sequid, self.ERRORS.NoService, None)
					logger.debug("No Service [%s]", sequid)

				self.send_msgpack(msg)

			elif type == MessageTypes.CALLMETHOD_WITH_STREAMS:
				sequid, objectid, name, args, kwargs = msg[1:]

				logger.debug("calling local method with stream [%s].%s(%s) [%s]", objectid, name, args_str(args, kwargs), sequid)
				if self.service:
					args = self.defilter_args(sequid, name, args) # only handle positional args for now
					msg = self.proc_callmethod(sequid, objectid, name, args, kwargs)
					if msg is None:
						return
				else:
					msg = (MessageTypes.ERROR, sequid, self.ERRORS.NoService, None)
					logger.debug("No Service [%s]", sequid)

				self.send_msgpack(msg)

			elif type == MessageTypes.CALLMETHOD_BY_RESULT:
				sequid, previous_sequid, name, args, kwargs = msg[1:]

				logger.debug("calling local method on result [%s].%s(%s) [%s]", previous_sequid, name, args_str(args, kwargs), sequid)
				if self.service:
					try:
						objectid = self.results[previous_sequid]
						msg = self.proc_callmethod(sequid, objectid, name, args, kwargs)
						if msg is None:
							return
					except KeyError: # sequid does not reference a object
						msg = (MessageTypes.ERROR, sequid, self.ERRORS.InvalidObject, None)
						logger.info("Invalid Object [%s]", previous_sequid)
				else:
					msg = (MessageTypes.ERROR, sequid, self.ERRORS.NoService, None)
					logger.debug("No Service [%s]", sequid)

				self.send_msgpack(msg)

			elif type == MessageTypes.CALLMETHOD_BY_RESULT_WITH_STREAMS:
				sequid, previous_sequid, name, args, kwargs = msg[1:]

				logger.debug("calling local method on result [%s].%s(%s) [%s]", previous_sequid, name, args_str(args, kwargs), sequid)
				if self.service:
					try:
						objectid = self.results[previous_sequid]
						args = self.defilter_args(sequid, name, args) # only handle positional args for now
						msg = self.proc_callmethod(sequid, objectid, name, args, kwargs)
						if msg is None:
							return
					except KeyError: # sequid does not reference a object
						msg = (MessageTypes.ERROR, sequid, self.ERRORS.InvalidObject, None)
						logger.info("Invalid Object [%s]", previous_sequid)
				else:
					msg = (MessageTypes.ERROR, sequid, self.ERRORS.NoService, None)
					logger.debug("No Service [%s]", sequid)

				self.send_msgpack(msg)

			elif type == MessageTypes.DELINSTANCE:
				objectid, = msg[1:]

				logger.debug("deleting local instance [%s]", objectid)
				if self.service:
					self.proc_delinstance(objectid)
				else:
					logger.debug("No Service")

			elif type == MessageTypes.DELINSTANCE_BY_RESULT:
				previous_sequid, = msg[1:]

				logger.debug("deleting local instance on result [%s]", previous_sequid)
				if self.service:
					try:
						objectid = self.results[previous_sequid]
					except KeyError:
						logger.info("Invalid Object %s", previous_sequid)
						return

					self.proc_delinstance(objectid)
				else:
					logger.debug("No Service")

			elif type == MessageTypes.CANCEL_CALL: # should this return a msg or not? without, canceling cannot be awaited directly
				sequid, = msg[1:]

				logger.debug("canceling call [%s]", previous_sequid)
				if self.service:
					try:
						self.waitingcalls[sequid].cancel()
					except KeyError:
						logger.debug("Tried to cancel invalid call [%s]", sequid)
				else:
					logger.debug("No Service")

			elif type == MessageTypes.CANCEL_STREAM: # should this return a msg or not? without, canceling cannot be awaited directly
				sequid, = msg[1:]

				logger.debug("canceling stream [%s]", sequid)
				if self.service:
					self.sender.cancel(sequid)
				else:
					logger.debug("No Service")

			elif type == MessageTypes.STREAM_ARGUMENT:

				sequid, arg_pos, result = msg[1:]

				try:
					deferred, name = self._calldeferreds[(sequid, arg_pos)]
					#deferred = self._calldeferreds[sequid][arg_pos]
					logger.debug("Received arg stream %s([%s]) [%s], calling iterator", name, arg_pos, sequid)
					deferred.callback(result)
				except KeyError:
					logger.info("Received arg stream with unknown SeqID [%s] or argument number (%s)", sequid, arg_pos)

			elif type == MessageTypes.ARGUMENT_ERROR:
				sequid, arg_pos, errortype, errormsg = msg[1:]

				try:
					deferred, name = self._calldeferreds.pop((sequid, arg_pos))
					logger.debug("Received arg stream error %s for %s([%s]) [%s], deleting iterator", errortype, name, arg_pos, sequid)
					# what errors can happen?
					if errortype == self.ERRORS.UserError:
						deferred.errback(RPCUserError(*errormsg))
					elif errortype == self.ERRORS.GeneralError:
						deferred.errback(Exception("{}() failed in an unexpected way".format(name)))
					else:
						deferred.errback(RPCError("Received unknown error"))
				except KeyError:
					logger.info("Received arg stream error with unknown SeqID [%s] or argument number (%s)", sequid, arg_pos)

			elif type == MessageTypes.ARGUMENT_END:
				sequid, arg_pos = msg[1:]

				try:
					deferred, name = self._calldeferreds.pop((sequid, arg_pos))
					logger.debug("Received end of arg stream %s([%s]) [%s], deleting iterator", name, arg_pos, sequid)
					deferred.completed()
				except KeyError:
					logger.info("Received end of arg stream with unknown SeqID [%s] or argument number (%s)", sequid, arg_pos)

			elif type == MessageTypes.RESULT:
				sequid, result = msg[1:]

				try:
					deferred, name = self._deferreds.pop(sequid)
					logger.debug("Received result %s() [%s], calling callback", name, sequid)
					deferred.callback(result)
				except KeyError:
					logger.info("Received result with unknown SeqID [%s]", sequid)

			elif type == MessageTypes.OBJECT:
				sequid, objectid = msg[1:]

				try:
					deferred, classname = self._deferreds.pop(sequid)
					logger.debug("Received object [%s]=%s [%s], calling callback", objectid, classname, sequid)
					deferred.callback(RemoteInstance(self, objectid, classname))
				except KeyError:
					logger.info("Received object [%s] with unknown SeqID [%s]", objectid, sequid)

			elif type == MessageTypes.ERROR:
				sequid, errortype, errormsg = msg[1:]

				try:
					deferred, name = self._deferreds.pop(sequid) #removes deferred (cannot receive errors with same sequid, change?)
					logger.debug("Received error %s [%s], calling errback", errortype, sequid)
					if errortype == self.ERRORS.UserError:
						deferred.errback(RPCUserError(*errormsg))
					elif errortype == self.ERRORS.ResourceExhausted:
						deferred.errback(ResourceExhaustedError("Not enough free resources on endpoint"))
					elif errortype == self.ERRORS.NoSuchFunction:
						deferred.errback(AttributeError("Invalid attribute {} on service".format(name)))
					elif errortype == self.ERRORS.WrongArguments:
						deferred.errback(TypeError("{}() was called with invalid arguments".format(name)))
					elif errortype == self.ERRORS.InvalidObject:
						deferred.errback(RPCInvalidObject("{}() was called on an invalid object".format(name)))
					elif errortype == self.ERRORS.GeneralError:
						deferred.errback(Exception("{}() failed in an unexpected way".format(name)))
					else:
						deferred.errback(RPCError("Received unknown error"))
				except KeyError:
					logger.info("Received error with unknown SeqID [%s]", sequid)

			elif type == MessageTypes.STREAM_RESULT:
				sequid, result = msg[1:]

				try:
					deferred, name = self._multideferreds[sequid]
					logger.debug("Received stream %s() [%s], calling iterator", name, sequid)
					deferred.callback(result)
				except KeyError:
					logger.info("Received stream with unknown SeqID [%s]", sequid)

			elif type == MessageTypes.STREAM_ERROR:
				sequid, errortype, errormsg = msg[1:]

				"""
				stream cannot have ResourceExhausted
				fixme: stream calls which fail before the RPC can decide it's a stream, will return a ERROR, not STREAM_ERROR (NoSuchFunction, WrongArguments, InvalidObject)

				could there be errors which are not caused by exceptions in the iterator
				and thus don't stop the iterator and thus continue sending?
				Maybe some informational messages for the client? then deferreds cannot be pop()'ed
				"""

				try:
					deferred, name = self._multideferreds.pop(sequid)
					logger.debug("Received stream error %s for %s() [%s], deleting iterator", errortype, name, sequid)
					if errortype == self.ERRORS.UserError:
						deferred.errback(RPCUserError(*errormsg))
					elif errortype == self.ERRORS.GeneralError:
						deferred.errback(Exception("{}() failed in an unexpected way".format(name)))
					else:
						deferred.errback(RPCError("Received unknown error"))
				except KeyError:
					logger.info("Received stream error with unknown SeqID [%s]", sequid)

			elif type == MessageTypes.STREAM_END:
				sequid, = msg[1:]

				try:
					deferred, name = self._multideferreds.pop(sequid)
					logger.debug("Received end of stream %s() [%s], deleting iterator", name, sequid)
					deferred.completed()
				except KeyError:
					logger.info("Received end of stream with unknown SeqID [%s]", sequid)

			else:
				logger.warning("Unknown message type received: %s", type)
		except ValueError:
			logger.warning("Received invalid formatted RPC message")

	def send_msgpack(self, msg):
		self.sender.send_msgpack(msg)

	def stream_msgpack(self, sequid, iterable): # flow controlled
		assert isinstance(iterable, GeneratorType)
		result = partial(self.sender.send_result, sequid)
		end = partial(self.sender.send_end, sequid)
		error = partial(self.sender.send_error, sequid)
		self.sender.add((result, end, error), iterable)

	def stream_msgpack_call(self, sequid, arg_pos, iterable): # flow controlled
		assert isinstance(iterable, GeneratorType)
		result = partial(self.sender.send_argument, sequid, arg_pos)
		end = partial(self.sender.send_argument_end, sequid, arg_pos)
		error = partial(self.sender.send_argument_error, sequid, arg_pos)
		self.sender.add((result, end, error), iterable)

	### RPC calls

	@ValidateConnection
	def _notify(self, _name, *args, **kwargs):
		assert isinstance(_name, str)

		logger.debug("notifying remote %s(%s)", _name, args_str(args, kwargs))
		msg = (MessageTypes.NOTIFY, _name, args, kwargs)
		self.send_msgpack(msg)

	@ValidateConnection
	def _notifymethod(self, _objectid, _name, *args, **kwargs):
		assert isinstance(_name, str)

		logger.debug("notifying remote method [%s].%s(%s)", _objectid, _name, args_str(args, kwargs))
		msg = (MessageTypes.NOTIFYMETHOD, _objectid, _name, args, kwargs)
		self.send_msgpack(msg)

	@ValidateConnection
	def _notifymethod_by_result(self, prev_sequid, _name, *args, **kwargs):
		assert isinstance(_name, str)

		logger.debug("notifying remote method on result [%s].%s(%s)", prev_sequid, _name, args_str(args, kwargs))
		msg = (MessageTypes.NOTIFYMETHOD_BY_RESULT, prev_sequid, _name, args, kwargs)
		self.send_msgpack(msg)

	# _notify_with_streams
	# _notifymethod_with_streams
	# _notifymethod_by_result_with_streams

	# helper for all kind of calls which return non-streaming results
	def process_call_and_prepare_deferred(self, sequid, _name, msg):
		assert sequid not in self._deferreds, "Must not reuse sequence id"
		deferred = RemoteResultDeferred(self, sequid, _name)
		self._deferreds[sequid] = (deferred, _name)
		self.send_msgpack(msg)
		return deferred

	@ValidateConnection
	def _call(self, _name, *args, **kwargs):
		assert isinstance(_name, str)

		sequid = next(self._sequid)
		logger.debug("calling remote %s(%s) [%s]", _name, args_str(args, kwargs), sequid)
		msg = (MessageTypes.CALL, sequid, _name, args, kwargs)

		return self.process_call_and_prepare_deferred(sequid, _name, msg)

	@ValidateConnection
	def _call_with_streams(self, _name, *args, **kwargs): # same for _stream_with_streams, copy
		assert isinstance(_name, str)

		sequid = next(self._sequid)
		args = tuple(self.filter_args(args, sequid))
		logger.debug("calling remote with stream %s(%s) [%s]", _name, args_str(args, kwargs), sequid)
		msg = (MessageTypes.CALL_WITH_STREAMS, sequid, _name, args, kwargs)

		return self.process_call_and_prepare_deferred(sequid, _name, msg)

	@ValidateConnection
	def _callmethod(self, _objectid, _name, *args, **kwargs):
		assert isinstance(_name, str)

		sequid = next(self._sequid)
		logger.debug("calling remote method [%s].%s(%s) [%s]", _objectid, _name, args_str(args, kwargs), sequid)
		msg = (MessageTypes.CALLMETHOD, sequid, _objectid, _name, args, kwargs)

		return self.process_call_and_prepare_deferred(sequid, _name, msg)

	@ValidateConnection
	def _callmethod_with_streams(self, _objectid, _name, *args, **kwargs):
		assert isinstance(_name, str)

		sequid = next(self._sequid)
		args = tuple(self.filter_args(args, sequid))
		logger.debug("calling remote method with stream [%s].%s(%s) [%s]", _objectid, _name, args_str(args, kwargs), sequid)
		msg = (MessageTypes.CALLMETHOD_WITH_STREAMS, sequid, _objectid, _name, args, kwargs)

		return self.process_call_and_prepare_deferred(sequid, _name, msg)

	@ValidateConnection
	def _callmethod_by_result(self, prev_sequid, _name, *args, **kwargs):
		assert isinstance(_name, str)

		sequid = next(self._sequid)
		logger.debug("calling remote method on result [%s].%s(%s) [%s]", prev_sequid, _name, args_str(args, kwargs), sequid)
		msg = (MessageTypes.CALLMETHOD_BY_RESULT, sequid, prev_sequid, _name, args, kwargs)

		return self.process_call_and_prepare_deferred(sequid, _name, msg)

	@ValidateConnection
	def _callmethod_by_result_with_streams(self, prev_sequid, _name, *args, **kwargs):
		assert isinstance(_name, str)

		sequid = next(self._sequid)
		args = tuple(self.filter_args(args, sequid))
		logger.debug("calling remote method on result with stream [%s].%s(%s) [%s]", prev_sequid, _name, args_str(args, kwargs), sequid)
		msg = (MessageTypes.CALLMETHOD_BY_RESULT_WITH_STREAMS, sequid, prev_sequid, _name, args, kwargs)

		return self.process_call_and_prepare_deferred(sequid, _name, msg)

	# helper for all kind of calls which return non-streaming results
	def process_stream_and_prepare_deferred(self, sequid, _name, msg):
		assert sequid not in self._multideferreds, "Must not reuse sequence id"
		deferred = MultiDeferredIterator(self, sequid, _name)
		self._multideferreds[sequid] = (deferred, _name)
		self.send_msgpack(msg)
		return deferred

	@ValidateConnection
	def _stream(self, _name, *args, **kwargs):
		assert isinstance(_name, str)

		sequid = next(self._sequid)
		logger.debug("requesting stream from remote %s(%s) [%s]", _name, args_str(args, kwargs), sequid)
		msg = (MessageTypes.CALL, sequid, _name, args, kwargs)

		return self.process_stream_and_prepare_deferred(sequid, _name, msg)

	@ValidateConnection
	def _streammethod(self, _objectid, _name, *args, **kwargs):
		assert isinstance(_name, str)

		sequid = next(self._sequid)
		logger.debug("requesting stream from remote method [%s].%s(%s) [%s]", _objectid, _name, args_str(args, kwargs), sequid)
		msg = (MessageTypes.CALLMETHOD, sequid, _objectid, _name, args, kwargs)

		return self.process_stream_and_prepare_deferred(sequid, _name, msg)

	@ValidateConnection
	def _streammethod_by_result(self, prev_sequid, _name, *args, **kwargs):
		assert isinstance(_name, str)

		sequid = next(self._sequid)
		logger.debug("requesting stream from remote method on result [%s].%s(%s) [%s]", prev_sequid, _name, args_str(args, kwargs), sequid)
		msg = (MessageTypes.CALLMETHOD_BY_RESULT, sequid, prev_sequid, _name, args, kwargs)

		return self.process_stream_and_prepare_deferred(sequid, _name, msg)

	# _stream_with_streams
	# _streammethod_with_streams
	# _streammethod_by_result_with_streams

	@ValidateConnection
	def _delinstance(self, objectid):
		logger.debug("deleting remote instance [%s]", objectid)
		msg = (MessageTypes.DELINSTANCE, objectid)
		self.send_msgpack(msg)

	@ValidateConnection
	def _delinstance_by_result(self, sequid):
		logger.debug("deleting remote result [%s]", sequid)
		msg = (MessageTypes.DELINSTANCE_BY_RESULT, sequid)
		self.send_msgpack(msg)

	@ValidateConnection
	def _cancel_call(self, sequid):
		logger.debug("canceling call [%s]", sequid)
		msg = (MessageTypes.CANCEL_CALL, sequid)
		self.send_msgpack(msg)

	@ValidateConnection
	def _cancel_stream(self, sequid):
		logger.debug("canceling stream [%s]", sequid)
		msg = (MessageTypes.CANCEL_STREAM, sequid)
		self.send_msgpack(msg)

	def _soft_disconnect(self):
		self.tp.soft_disconnect()

	def _hard_disconnect(self):
		self.tp.hard_disconnect()

	### convenience

	def check_certificate(self):

		""" verify identify of peer certificate
		todo: maybe do hard disconnect instead of soft? could help with DoS
		"""

		peer_x509 = self.tp.transport.getPeerCertificate()
		if not peer_x509:
			logger.warning("Peer did not send a certificate")
			self._soft_disconnect()
			return

		peer_pubkey = get_pubkey_from_x509(peer_x509)

		try:
			name = self.friends.identify(peer_pubkey)
		except UnknownPeer:
			logger.warning("Connection denied (not in friends list)")
			logger.info(cert_info(peer_x509))
			self._soft_disconnect()
			return
		self.authenticate(name, peer_pubkey)

		""" modify like this?
		try:
			name, peer_pubkey = verify_certificate():
			self.authenticate(name, peer_pubkey)
		except BadPeer:
			self._soft_disconnect()
		"""

	# unused so far, could be used for unencrypted connections
	def check_token(self, token):
		try:
			name = self.friends.identify(token)
		except UnknownPeer:
			logger.warning("Connection denied (not in friends list)")
			logger.info("Unknown token: %s", token)
			self._soft_disconnect()
			return
		self.authenticate(name, token)

	### Callbacks

	def connection_made(self): # todo: use host and port as args?
		self.addr = IPAddr(self.tp.transport.getPeer().host, self.tp.transport.getPeer().port)
		logger.debug("Connection to %s started [TCP_NODELAY=%s, SO_KEEPALIVE=%s]",
			self.addr, self.tp.transport.getTcpNoDelay(), self.tp.transport.getTcpKeepAlive())

	def connection_open(self): # might be called multiple time
		#self.check_certificate()
		self.service._OnConnect() # use RemoteObject(self) as argument?
		logger.debug("Connection to %s established", self.addr)
		self.tp.send_data(b"") # Because there is no SSLconnectionMade function. Well there is now!
		#send token here if the connection is not encrypted

	def connection_lost(self, reason):
		self.service._OnDisconnect() # use RemoteObject(self) as argument?

		if self.authed:
			if reason.check(error.ConnectionDone):
				logger.debug("Connection to %s closed", self.name)
			else:
				logger.info("Connection to %s lost: %s", self.name, reason.getErrorMessage())

			self.authed = False
			self.friends.reset_connection(self.name, RemoteObject(self))

			self.service._delete_all_objects(self.connid) # makes use by other peers impossible

			logger.debug("%s outstanding requests, %s streams", len(self._deferreds), len(self._multideferreds))

			if reason.check(error.ConnectionDone):
				for sequid, (deferred, __) in itertools.chain(iteritems(self._deferreds), iteritems(self._multideferreds)):
					deferred.errback(ConnectionLost("Connection to {} closed".format(self.name)))
			else:
				for sequid, (deferred, __) in itertools.chain(iteritems(self._deferreds), iteritems(self._multideferreds)):
					deferred.errback(ConnectionLost("Connection to {} lost: {}".format(self.name, reason.getErrorMessage())))

		else:
			if reason.check(error.ConnectionDone):
				logger.debug("Connection to %s closed", self.addr)
			else:
				logger.info("Connection to %s lost: %s", self.addr, reason.getErrorMessage())
			assert not self._deferreds and not self._multideferreds

		self.closed = True

	def recv_data(self, data):
		if self.name and data:
			try:
				msg = msgpack.loads(data, use_list=False, raw=False, ext_hook=self.ext_hook)
				self.recv_msgpack(msg)
			except msgpack.exceptions.UnpackException: # Deprecated. Use Exception instead.
				logger.exception("msgpack loading error") # should be logger.warning
		elif self.name is None and data == b"": # because there is no SSLconnectionMade function. well in twisted 16.4.0+ there is: handshakeCompleted
			self.check_certificate()
		else:
			if not data:
				logger.warning("Received zero length message")
			if not self.name:
				logger.warning("Received unauthenticated message")

class GenericRPCSSLContextFactory(ssl.ContextFactory):

	def __init__(self, public_key, private_key, verify_ca=True, tls_version=SSL.TLSv1_2_METHOD, cipher_string="HIGH"):
		"""public_key and private_key are paths to certificate files
		if verify_ca is true:
			self signed certs are not allowed. A list of valid CA files can be given with 'valid_ca_cert_files'.
			this list can contain the certificates itself for selfsigned certificates
		else:
			self signed certs are allowed.
		tls_version: can be SSL.SSLv2_METHOD, SSL.SSLv3_METHOD, SSL.SSLv23_METHOD, SSL.TLSv1_METHOD, SSL.TLSv1_1_METHOD, SSL.TLSv1_2_METHOD (depending on pyOpenSSL version)
		cipher_string: see https://www.openssl.org/docs/apps/ciphers.html
		"""
		self.public_key = public_key
		self.private_key = private_key
		self.tls_version = tls_version
		self.verify_ca = verify_ca

		self.ctx = SSL.Context(self.tls_version)
		self.ctx.use_certificate_file(self.public_key)
		self.ctx.use_privatekey_file(self.private_key)

		self.ctx.set_cipher_list(cipher_string)
		self.ctx.set_verify(SSL.VERIFY_PEER | SSL.VERIFY_FAIL_IF_NO_PEER_CERT, self.verify_callback) #must be called or client does not send certificate at all

		if self.verify_ca:
			for pubkeyfile in self.valid_ca_cert_files():
				try:
					#authenticate client public key
					if pyopenssl_version == "0.14":
						self.ctx.load_verify_locations(pubkeyfile.encode("utf-8")) #encode("utf-8") fixes pyopenssl-0.14
					else:
						self.ctx.load_verify_locations(pubkeyfile)
					logger.debug("Authorised '%s'", pubkeyfile)
				except SSL.Error as e:
					logger.info("Authorising '%s' failed", pubkeyfile)

	def getContext(self):
		"""Returns the SSL Context object."""
		return self.ctx

	def valid_ca_cert_files(self):
		"""Should return a list of files (paths) with valid CA certificates"""
		raise NotImplementedError()

	def verify_callback(self, connection, x509, errnum, errdepth, ok):
		"""Is called to verify a certificate. (is called for every error and certificate in chain)
		return True to indicate a valid
		return False to indicate an invalid certificate.
		"""
		#see https://www.openssl.org/docs/apps/verify.html#DIAGNOSTICS for error codes
		if not ok:
			if not self.verify_ca and errnum == 18: #X509_V_ERR_DEPTH_ZERO_SELF_SIGNED_CERT, X509_V_ERR_SELF_SIGNED_CERT_IN_CHAIN??
				logger.info("Allowing self signed certificate from peer: %s", x509.get_subject())
				return True
			else:
				logger.warning("Invalid certificate from peer: %s [%s,%s]: %s",
					x509.get_subject(), errnum, errdepth, crypto.X509_verify_cert_error_string(errnum))
				return False
		else:
			logger.info("Certificates are valid: %s", x509.get_subject())
			return True
