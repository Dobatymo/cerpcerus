from __future__ import absolute_import, unicode_literals

import logging, Queue, itertools
from functools import partial

import msgpack
from OpenSSL import SSL, crypto, __version__ as pyopenssl_version
from twisted.internet import ssl, defer, error

from .utils import cert_info, args_str, Seq
from .rpc import RemoteObject, RemoteInstance, RemoteResult, RPCAttributeError, RPCInvalidArguments, RPCInvalidObject, NotAuthenticated, ObjectId

from .iter_deferred import MultiDeferredIterator

#pylint: disable=protected-access

logger = logging.getLogger(__name__)

"""
debug: errors which result from wrong usage on remote side (eg. calling non existing function)
info: errors which could result from above or below case (eg. accessing invalid object ids)
warning: errors which result from intentional wrong usage of protocol (eg. sending wrongly formated data)
exception: unexpected exceptions which point to source code errors
error:
"""

L = ARROW_POINTING_DOWNWARDS_THEN_CURVING_RIGHTWARDS = "\u2937"

class RPCUserError(Exception):
	"""Can by raised by functions in RPC service to signal user defined error codes"""

class RPCError(Exception):
	"""Signals a general RPC error"""

class NetworkError(Exception):
	"""Signals a general rpc network error"""

class ConnectionLost(NetworkError):
	"""Raised when the rpc connection is lost or closed"""

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
		return None

	def update_by_addr(self, addr, conn):
		pass

	def set_addr(self, name, addr):
		pass

class AllFriends(IFriends):

	"""Simple implementation of IFriends interface.
	Assigns a unique number as name for every key.
	"""

	def __init__(self):
		self.friends = {}
		self.seq = Seq(0)

	def identify(self, public_key):
		try:
			return self.friends[public_key]
		except KeyError:
			self.friends[public_key] = self.seq.next()
			return self.friends[public_key]

	def get_connection(self, name):
		return None

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

	def close(self): # called when iteration is not finished, so resources can be cleaned up
		pass

	def send(self, value):
		raise NotImplementedError

	def throw(self, mytype, value=None, traceback=None):
		raise NotImplementedError()

	def __iter__(self):
		return self

	def __next__(self): # returns a piece of data
		raise NotImplementedError()
	
	def __repr__(self):
		return "'<Streamable>'"

# unfinished, untested
class PushProducerRoundRobin:
	def __init__(self, consumer):
		self.consumer = consumer
		self.queue = Queue.Queue()
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

		except Queue.Empty:
			pass

	def pauseProducing(self):
		self.pushing = False

	def stopProducing(self):
		#self.consumer.unregisterProducer()
		pass

from twisted.internet.threads import deferToThread
class file_sender:

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

class RPCPullProducer:

	"""
	it should be able to use this producer on both sides.
	for sending rpc requests and streams, and replying to rpc and stream requests.

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
		if isinstance(obj, RemoteInstance):
			return msgpack.ExtType(self.RemoteInstanceID, msgpack.dumps(obj.__getstate__(), use_bin_type=True, encoding="utf-8"))
		elif isinstance(obj, Streamable):
			return msgpack.ExtType(self.StreamableID, b"")
		return obj

	def add(self, senders, iterable): # called from rpc
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

	def send_error(self, sequid, code):
		msg = (MessageTypes.STREAM_ERROR, sequid, code, None)
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

	def _add(self, senders, iterable): # called from add()
		raise NotImplementedError

	def resumeProducing(self): # to be called from consumer
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
	accepts blobs and streamables which return blobs or deferreds.
	directly write blobs to consumer
	streamables are iterated and send when requested
		blobs are written to consumer instantly.
		deferreds will have write callbacks added and execution is given up until result is ready.
	"""

	def __init__(self, consumer, maxsize=0):
		RPCPullProducer.__init__(self, consumer)
		self.queue = Queue.Queue(maxsize) # use queue size to signal high resource usage
		self.current = None

	def _add(self, senders, iterable):
		assert isinstance(iterable, GeneratorType)
		try:
			self.queue.put_nowait((senders, iterable)) #raises if queue is full, can dataReceived be slowed? (by pauseProducing?), just send resource error
		except Queue.Full:
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

	def resumeProducing(self):
		try:
			if not self.current:
				self.current = self.queue.get_nowait()

			(send_result, send_end, send_error), iterable = self.current
			try:
				self._write(send_result, send_error, next(iterable))
			except StopIteration:
				send_end()
				self.current = None
			except Exception:
				send_error(RPCBase.ERRORS.GeneralError)
				logger.exception("Calling iterator failed")
				# stop on error?

		except Queue.Empty:
			#logger.debug("Producer has run out of data, unregistering...")
			self.consumer.unregisterProducer()
			self.registered = False

class PullProducerRoundRobin(RPCPullProducer):
	pass

class RemoteResultDeferred(defer.Deferred, RemoteResult):

	def __init__(self, conn, sequid, classname):
		defer.Deferred.__init__(self)
		RemoteResult.__init__(self, conn, sequid, classname)

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

#Decorator to avoid copy&paste
def ValidateConnection(func):
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
	CALL = 3
	CALL_WITH_STREAMS = 4
	CALLMETHOD = 5
	CALLMETHOD_WITH_STREAMS = 6
	DELINSTANCE = 7

	STREAM_ARGUMENT = 11
	ARGUMENT_END = 12
	ARGUMENT_ERROR = 13

	# SERVER TO CLIENT
	RESULT = 21
	OBJECT = 22
	ERROR = 23
	STREAM_RESULT = 24
	STREAM_ERROR = 25
	STREAM_END = 26

	NOTIFYMETHOD_ON_RESULT = 31
	CALLMETHOD_ON_RESULT = 32
	CALLMETHOD_WITH_STREAMS_ON_RESULT = 33
	DELINSTANCE_ON_RESULT = 34

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
		self.connid = self.connids.next()
		self._sequid = Seq(0) #was static/class var before
		self.friends = friends
		self.tp = transport_protocol
		self.name = None
		self.addr = None
		self.service = None
		self._deferreds = {} # deferreds saved on client side to process normal calls
		self._multideferreds = {} # deferreds saved on client side to process streaming calls
		self._calldeferreds = {} # deferreds saved on server side to process incoming streaming calls
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
		pass

	### msgpack hooks

	RemoteInstanceID = 0x05
	StreamableID = 0x06

	def ext_hook(self, n, obj):
		if n == self.RemoteInstanceID:
			objectid, classname = msgpack.loads(obj, use_list=False, encoding="utf-8")
			return RemoteInstance(self, objectid, classname)
		elif n == self.StreamableID:
			return Streamable()
		return obj

	### converting messages <-> calls

	def _success(self, sequid, result): # check if GeneratorType also
		if isinstance(result, ObjectId):
			self.send_msgpack((MessageTypes.OBJECT, sequid, int(result))) # there is no automatic conversion for ObjectId so far
		else:
			self.send_msgpack((MessageTypes.RESULT, sequid, result))

	def _failure(self, sequid, failure):
		msg = (MessageTypes.ERROR, sequid, self.ERRORS.Deferred, None)
		logger.exception(failure.getErrorMessage())
		self.send_msgpack(msg)

	#@needs_service
	def proc_notifymethod(self, objectid, name, args, kwargs):
		assert isinstance(name, unicode)
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

	#@needs_service
	def proc_call(self, sequid, name, args, kwargs):
		assert isinstance(name, unicode)
		try:
			#if name.startswith("_") check not needed. Service does that and raises RPCAttributeError

			result = self.service._call(self.connid, name, *args, **kwargs)
			print("local yielded result of type:", type(result))
			if isinstance(result, defer.Deferred):
				result.addCallbacks(partial(self._success, sequid), partial(self._failure, sequid))
				return
			elif isinstance(result, ObjectId):
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

	#@needs_service
	def proc_callmethod(self, sequid, objectid, name, args, kwargs):
		assert isinstance(name, unicode)
		try:
			result = self.service._callmethod(self.connid, objectid, name, *args, **kwargs)
			if isinstance(result, defer.Deferred):
				result.addCallbacks(partial(self._success, sequid), partial(self._failure, sequid))
				return None
			elif isinstance(result, ObjectId):
				self.results[sequid] = result
				msg = (MessageTypes.OBJECT, sequid, int(result))
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

	def recv_msgpack(self, msg):
		try:
			type = msg[0]
		except (IndexError, TypeError):
			logger.warning("Received invalid formated rpc message")
			return
		except: # replace with Exception for py3
			# import exceptions #msgpack 0.4.8 throws TypeError from this module...
			logger.exception("Received invalid formated rpc message")
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
					except RPCUserError as e:
						logger.info("%sUser Error", L)
					except RPCAttributeError as e:
						logger.debug("%sNo Such Function %s", L, name)
					except RPCInvalidArguments as e:
						logger.debug("%sWrong Arguments", L)
					except Exception as e:
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

			elif type == MessageTypes.NOTIFYMETHOD_ON_RESULT:
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

					def defilter_args(args, sequid):
						""" this could be put in msgpack custom unpacking also.
							but this would require sendin the sequid and argument position
						"""
						for arg_pos, arg in enumerate(args):
							if isinstance(arg, Streamable):
								deferred = MultiDeferredIterator()
								self._calldeferreds[(sequid, arg_pos)] = (deferred, name)
								#self._calldeferreds[sequid][arg_pos] = (deferred, name)
								yield deferred
							else:
								yield arg

					args = defilter_args(args, sequid) # only handle positional args for now

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

			elif type == MessageTypes.CALLMETHOD_ON_RESULT:
				sequid, previous_sequid, name, args, kwargs = msg[1:]

				logger.debug("calling local method on result [%s].%s(%s) [%s]", previous_sequid, name, args_str(args, kwargs), sequid)
				if self.service:
					try:
						objectid = self.results[previous_sequid]
						msg = self.proc_callmethod(sequid, objectid, name, args, kwargs)
						if msg is None:
							return
					except KeyError:
						msg = (MessageTypes.ERROR, sequid, self.ERRORS.InvalidObject, None)
						logger.info("Invalid Object %s", previous_sequid)
				else:
					msg = (MessageTypes.ERROR, sequid, self.ERRORS.NoService, None)
					logger.debug("No Service [%s]", sequid)

				self.send_msgpack(msg)

			elif type == MessageTypes.DELINSTANCE:
				objectid, = msg[1:]

				logger.debug("deleting local instance [%s]", objectid)
				if self.service:
					try:
						self.service._delete(self.connid, objectid)
					except RPCInvalidObject:
						logger.info("Tried to delete invalid Object %s", objectid)
					except Exception:
						logger.exception("RPC delete object %s failed", objectid)
				else:
					logger.debug("No Service")

			elif type == MessageTypes.DELINSTANCE_ON_RESULT:
				previous_sequid, = msg[1:]

				logger.debug("deleting local instance on result [%s]", previous_sequid)
				if self.service:
					try:
						objectid = self.results[previous_sequid]
					except KeyError:
						logger.info("Invalid Object %s", previous_sequid)
						return

					try:
						self.service._delete(self.connid, objectid)
					except RPCInvalidObject:
						logger.info("Tried to delete invalid Object %s", objectid)
					except Exception:
						logger.exception("RPC delete object %s failed", objectid)
				else:
					logger.debug("No Service")

			elif type == MessageTypes.STREAM_ARGUMENT: # like STREAM_RESULT

				sequid, arg_pos, result = msg[1:]

				try:
					deferred, name = self._calldeferreds[(sequid, arg_pos)]
					#deferred = self._calldeferreds[sequid][arg_pos]
					logger.debug("Received argument stream %s([%s]) [%s], calling iterator", name, arg_pos, sequid)
					deferred.callback(result)
				except KeyError:
					logger.info("Received stream with unknown Sequence ID %s or argument number %s", sequid, arg_pos)

			elif type == MessageTypes.ARGUMENT_ERROR: # how do i handle stream errors? can i interrupt remote streams?
				sequid, arg_pos, errortype, errormsg = msg[1:]

				raise RuntimeError("not implemented")

			elif type == MessageTypes.ARGUMENT_END:

				sequid, arg_pos = msg[1:]

				try:
					deferred, name = self._calldeferreds.pop((sequid, arg_pos))
					logger.debug("Received end of argument stream %s([%s]) [%s], deleting iterator", name, arg_pos, sequid)
					deferred.completed()
				except KeyError:
					logger.info("Received stream with unknown Sequence ID %s or argument number %s", sequid, arg_pos)

			elif type == MessageTypes.RESULT:
				sequid, result = msg[1:]

				try:
					deferred, name = self._deferreds.pop(sequid)
					logger.debug("Received result %s() [%s], calling callback", name, sequid)
					deferred.callback(result)
				except KeyError:
					logger.info("Unknown Sequence ID received: %s", sequid)

			elif type == MessageTypes.OBJECT:
				sequid, objectid = msg[1:]

				try:
					deferred, classname = self._deferreds.pop(sequid)
					logger.debug("Received object [%s]=%s [%s], calling callback", objectid, classname, sequid)
					deferred.callback(RemoteInstance(self, objectid, classname))
				except KeyError:
					logger.info("Unknown Sequence ID received: %s", sequid)

			elif type == MessageTypes.ERROR: # how do I handle stream errors? can I interrupt remote streams?
				sequid, errortype, errormsg = msg[1:]

				logger.debug("Received error %s [%s], calling errback", errortype, sequid)
				try:
					deferred, name = self._deferreds.pop(sequid) #removes deferred (cannot receive errors with same sequid, change?)
					if errortype == self.ERRORS.UserError:
						deferred.errback(RPCUserError(errormsg))
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
					logger.info("Unknown Sequence ID received: %s", sequid)

			elif type == MessageTypes.STREAM_RESULT:
				sequid, result = msg[1:]

				try:
					deferred, name = self._multideferreds[sequid]
					logger.debug("Received stream %s() [%s], calling iterator", name, sequid)
					deferred.callback(result)
				except KeyError:
					logger.info("Unknown Sequence ID received: %s", sequid)

			elif type == MessageTypes.STREAM_ERROR:
				sequid, errortype, errormsg = msg[1:]

				raise RuntimeError("not implemented")

			elif type == MessageTypes.STREAM_END:
				sequid, = msg[1:]

				try:
					deferred, name = self._multideferreds.pop(sequid)
					logger.debug("Received end of stream %s() [%s], deleting iterator", name, sequid)
					deferred.completed()
				except KeyError:
					logger.info("Unknown Sequence ID received: %s", sequid)

			else:
				logger.warning("Unknown message type received: %s", type)
		except ValueError:
			logger.warning("Received invalid formated rpc message")

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
		logger.debug("notifying remote %s(%s)", _name, args_str(args, kwargs))
		msg = (MessageTypes.NOTIFY, _name, args, kwargs)
		self.send_msgpack(msg)

	@ValidateConnection
	def _notifymethod(self, _objectid, _name, *args, **kwargs):
		logger.debug("notifying remote method [%s].%s(%s)", _objectid, _name, args_str(args, kwargs))
		msg = (MessageTypes.NOTIFYMETHOD, _objectid, _name, args, kwargs)
		self.send_msgpack(msg)

	@ValidateConnection
	def _call(self, _name, *args, **kwargs):
		assert isinstance(_name, unicode), type(_name)

		sequid = self._sequid.next()
		logger.debug("calling remote %s(%s) [%s]", _name, args_str(args, kwargs), sequid)
		msg = (MessageTypes.CALL, sequid, _name, args, kwargs)
		assert sequid not in self._deferreds, "Must not reuse sequence id"
		deferred = RemoteResultDeferred(self, sequid, _name)
		self._deferreds[sequid] = (deferred, _name)
		self.send_msgpack(msg)
		return deferred

	@ValidateConnection
	def _call_with_streams(self, _name, *args, **kwargs): # same for _stream_with_streams, copy
		assert isinstance(_name, unicode), type(_name)

		sequid = self._sequid.next()

		def filter_args(args, sequid):
			for arg_pos, arg in enumerate(args): # only handle positional args for now
				if isinstance(arg, GeneratorType):
					self.stream_msgpack_call(sequid, arg_pos, arg)
					yield Streamable() # (sequid, arg_pos)
				else:
					yield arg

		args = tuple(filter_args(args, sequid))

		logger.debug("calling remote with stream %s(%s) [%s]", _name, args_str(args, kwargs), sequid)
		msg = (MessageTypes.CALL_WITH_STREAMS, sequid, _name, args, kwargs)
		assert sequid not in self._deferreds, "Must not reuse sequence id"
		deferred = RemoteResultDeferred(self, sequid, _name)
		self._deferreds[sequid] = (deferred, _name)
		self.send_msgpack(msg)
		return deferred

	@ValidateConnection
	def _callmethod(self, _objectid, _name, *args, **kwargs):
		sequid = self._sequid.next()
		logger.debug("calling remote method [%s].%s(%s) [%s]", _objectid, _name, args_str(args, kwargs), sequid)
		msg = (MessageTypes.CALLMETHOD, sequid, _objectid, _name, args, kwargs)
		assert sequid not in self._deferreds, "Must not reuse sequence id"
		deferred = RemoteResultDeferred(self, sequid, _name)
		self._deferreds[sequid] = (deferred, _name)
		self.send_msgpack(msg)
		return deferred

	@ValidateConnection
	def _callmethod_with_streams(self, _objectid, _name, *args, **kwargs):
		raise NotImplementedError()

	@ValidateConnection
	def _stream(self, _name, *args, **kwargs):
		assert isinstance(_name, unicode), type(_name)

		sequid = self._sequid.next()
		logger.debug("requesting stream from remote %s(%s) [%s]", _name, args_str(args, kwargs), sequid)
		msg = (MessageTypes.CALL, sequid, _name, args, kwargs)
		assert sequid not in self._multideferreds, "Must not reuse sequence id"
		deferred = MultiDeferredIterator()
		self._multideferreds[sequid] = (deferred, _name)
		self.send_msgpack(msg)
		return deferred

	@ValidateConnection
	def _streammethod(self, _objectid, _name, *args, **kwargs):
		assert isinstance(_name, unicode), type(_name)

		sequid = self._sequid.next()
		logger.debug("requesting stream from remote method [%s].%s(%s) [%s]", _objectid, _name, args_str(args, kwargs), sequid)
		msg = (MessageTypes.CALLMETHOD, sequid, _objectid, _name, args, kwargs)
		assert sequid not in self._multideferreds, "Must not reuse sequence id"
		deferred = MultiDeferredIterator()
		self._multideferreds[sequid] = (deferred, _name)
		self.send_msgpack(msg)
		return deferred

	@ValidateConnection
	def _callmethod_onresult(self, prev_sequid, _name, *args, **kwargs):

		sequid = self._sequid.next()
		logger.debug("calling remote method on result [%s].%s(%s) [%s]", prev_sequid, _name, args_str(args, kwargs), sequid)
		msg = (MessageTypes.CALLMETHOD_ON_RESULT, sequid, prev_sequid, _name, args, kwargs)
		assert sequid not in self._deferreds, "Must not reuse sequence id"
		deferred = RemoteResultDeferred(self, sequid, _name)
		self._deferreds[sequid] = (deferred, _name)
		self.send_msgpack(msg)
		return deferred

	@ValidateConnection
	def _delinstance(self, objectid):
		logger.debug("deleting remote instance [%s]", objectid)
		msg = (MessageTypes.DELINSTANCE, objectid)
		self.send_msgpack(msg)

	@ValidateConnection
	def _delinstance_onresult(self, sequid):
		logger.debug("deleting remote result [%s]", sequid)
		msg = (MessageTypes.DELINSTANCE_ON_RESULT, sequid)
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
		peer_pubkey = crypto.dump_privatekey(crypto.FILETYPE_ASN1, peer_x509.get_pubkey())

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

	### Callbacks

	def connection_made(self): # todo: use host and port as args?
		self.addr = IPAddr(self.tp.transport.getPeer().host, self.tp.transport.getPeer().port)
		logger.debug("Connection to %s started [TCP_NODELAY=%s, SO_KEEPALIVE=%s]",
			self.addr, self.tp.transport.getTcpNoDelay(), self.tp.transport.getTcpKeepAlive())

	def connection_open(self): # might be called multiple time
		#self.check_certificate()
		self.service._OnConnect() #use RemoteObject(self) as argument?
		logger.debug("Connection to %s established", self.addr)
		self.tp.send_data(b"") #because there is no SSLconnectionMade function. well there is now!

	def connection_lost(self, reason):
		self.service._OnDisconnect() #use RemoteObject(self) as argument?

		if self.authed:
			if reason.check(error.ConnectionDone):
				logger.debug("Connection to %s closed", self.name)
			else:
				logger.info("Connection to %s lost: %s", self.name, reason.getErrorMessage())

			self.authed = False
			self.friends.reset_connection(self.name, RemoteObject(self))

			self.service._deleteAllObjects(self.connid) # makes use by other peers impossible

			logger.debug("%s outstanding requests, %s streams", len(self._deferreds), len(self._multideferreds))

			if reason.check(error.ConnectionDone):
				for sequid, (deferred, __) in itertools.chain(self._deferreds.iteritems(), self._multideferreds.iteritems()):
					deferred.errback(ConnectionLost("Connection to {} closed".format(self.name)))
			else:
				for sequid, (deferred, __) in itertools.chain(self._deferreds.iteritems(), self._multideferreds.iteritems()):
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
				msg = msgpack.loads(data, use_list=False, encoding="utf-8", ext_hook=self.ext_hook)
				self.recv_msgpack(msg)
			except msgpack.exceptions.UnpackException: # Deprecated. Use Exception instead.
				logger.exception("msgpack loading error") # should be logger.warning
		elif self.name is None and data == b"": #because there is no SSLconnectionMade function. well in twisted 16.4.0+ there is: handshakeCompleted
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

class IPAddr(object):
	"""Simple class which containts IP and port"""
	def __init__(self, ip, port):
		#self.atyp
		self.ip = ip
		self.port = port

	def __str__(self):
		return "{!s}:{!s}".format(self.ip, self.port)

	def __repr__(self):
		return "IPAddr({!r}, {!r})".format(self.ip, self.port)

	def __iter__(self):
		return iter((self.ip, self.port))

	def __eq__(self, other):
		if other is None:
			return False
		return self.ip == other.ip and self.port == other.port

	__hash__ = object.__hash__ #needed in py3 because of __eq__ override
