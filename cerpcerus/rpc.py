from __future__ import absolute_import, division, print_function, unicode_literals
from builtins import str

from future.utils import iteritems

from functools import partial
from itertools import chain
from abc import abstractmethod
import inspect, warnings
try:
	from inspect import signature #py3.3+
except ImportError:
	from funcsigs import signature #backport

from .utils import cast, Seq, log_methodcall_decorator # decorator only needed for development
from . import __modulename__

#pylint: disable=protected-access

import logging # debug
logger = logging.getLogger(__name__) # debug

"""
todo: take care when remote objects are destroyed... __del__

"""

class RPCAttributeError(AttributeError):
	"""Raised if method access is not allowed. For internal use."""

class RPCInvalidArguments(TypeError):
	"""Raised if method is accessed with an invalid number of arguments
	or unexpected keyword arguments. For internal use."""

class RPCInvalidObject(RuntimeError):
	"""Raised if an invalid object is accessed."""

class NotAuthenticated(Exception):
	"""Raised if method is called on object, whose connection
	is not yet or not anymore authenticated."""

class ObjectId(int):
	"""Wrapper to pass around object references"""

class CallAnyPublic(object):
	"""Baseclass which delegates method calls based on leading "_"."""

	def __getattr__(self, name): # only gets invoked for attributes that are not already defined. __getattribute__ would be called always
		# name is byte string in python 2 and unicode string in python 3
		if not name.startswith("_"):
			return self._callpublic(name)
		else:
			return self._callprivate(name)

	def __dir__(self):
		raise NotImplementedError("No introspection available")

	@abstractmethod
	def _callpublic(self, name):
		raise NotImplementedError()

	@abstractmethod
	def _callprivate(self, name):
		raise NotImplementedError()

class RemoteObjectGeneric(CallAnyPublic):

	"""Generic proxy class for remote network objects."""

	# __getattr__ from CallAnyPublic is not called, if attribute is defined in this class

	def __init__(self, conn):
		self._conn = conn
		self._alias = {}

	"""def __getitem__(self, key):
		return self._alias[key]

	def __setitem__(self, key, value):
		self._alias[key] = value

	def __delitem__(self, key):
		del self._alias[key]"""

	def _callpublic(self, name):
		return partial(self._call, self._alias.get(name, name))

	def _callprivate(self, name):
		"""called from user, so return user friendly exception """

		# vs: __class__.__name__?
		raise AttributeError("{} instance has no attribute '{}'".format(type(self).__name__, name)) # str(name) needed for python2?

	@property
	def _connid(self):
		return self._conn.connid

	@property
	def _name(self):
		return self._conn.name

	@property
	def _addr(self):
		return self._conn.addr

	@property
	def _service(self):
		return self._conn.service

	def _lose(self):
		self._conn._soft_disconnect()

	def _abort(self):
		self._conn._hard_disconnect()

	def __repr__(self):
		return "'<RemoteObject object to {} at {}>'".format(self._conn.name, self._conn.addr)

	def __dir__(self):
		return ["_connid", "_name", "_addr", "_service", "_lose", "_abort"]

	def __getstate__(self):
		""" todo: return enough information to reestablish the connection later """
		return (self._conn, self._alias)

	def __setstate__(self, state):
		""" reestablish the connection """
		self._conn, self._alias = state

class RemoteObject(RemoteObjectGeneric):

	"""Proxy class for remote functions."""

	def __init__(self, conn):
		RemoteObjectGeneric.__init__(self, conn)

	def _call(self, _name, *args, **kwargs):
		# type: (str, *Any, **Any) -> RemoteResultDeferred
		_name = str(_name) # this is needed for python2 is it?
		return self._conn._call(_name, *args, **kwargs)

	def _call_with_streams(self, _name, *args, **kwargs):
		# type: (str, *Any, **Any) -> RemoteResultDeferred
		_name = str(_name)
		return self._conn._call_with_streams(_name, *args, **kwargs)

	def _notify(self, _name, *args, **kwargs):
		# type: (str, *Any, **Any) -> None
		_name = str(_name)
		self._conn._notify(_name, *args, **kwargs)

	def _notify_with_streams(self, _name, *args, **kwargs):
		# type: (str, *Any, **Any) -> None
		_name = str(_name)
		self._conn._notify_with_streams(_name, *args, **kwargs)

	def _stream(self, _name, *args, **kwargs): # could return a async iterator in the far future
		# type: (str, *Any, **Any) -> MultiDeferredIterator
		_name = str(_name)
		return self._conn._stream(_name, *args, **kwargs)

	def _stream_with_streams(self, _name, *args, **kwargs): # could return a async iterator in the far future
		# type: (str, *Any, **Any) -> MultiDeferredIterator
		_name = str(_name)
		return self._conn._stream_with_streams(_name, *args, **kwargs)

	def __repr__(self):
		# type: () -> str
		return "'<RemoteObject object to {} at {}>'".format(self._conn.name, self._conn.addr)

	def __dir__(self):
		return RemoteObjectGeneric.__dir__(self) + ["_call", "_notify"]

	def __del__(self):
		pass #todo: disconnect conn?

class RemoteInstance(RemoteObjectGeneric):

	"""Proxy class for remote objects."""

	def __init__(self, conn, objectid, classname):
		RemoteObjectGeneric.__init__(self, conn)
		assert isinstance(classname, str)
		self._objectid = objectid
		self._classname = classname

	def _call(self, _name, *args, **kwargs):
		# type: (str, *Any, **Any) -> RemoteResultDeferred
		_name = str(_name) # this is needed for python2 is it?
		return self._conn._callmethod(self._objectid, _name, *args, **kwargs)

	def _call_with_streams(self, _name, *args, **kwargs):
		# type: (str, *Any, **Any) -> RemoteResultDeferred
		_name = str(_name)
		return self._conn._callmethod_with_streams(_name, *args, **kwargs)

	def _notify(self, _name, *args, **kwargs):
		# type: (str, *Any, **Any) -> None
		_name = str(_name)
		self._conn._notifymethod(self._objectid, _name, *args, **kwargs)

	def _notify_with_streams(self, _name, *args, **kwargs):
		# type: (str, *Any, **Any) -> None
		_name = str(_name)
		self._conn._notifymethod_with_streams(self._objectid, _name, *args, **kwargs)

	def _stream(self, _name, *args, **kwargs): # could return a async iterator in the far future
		# type: (str, *Any, **Any) -> MultiDeferredIterator
		_name = str(_name)
		return self._conn._streammethod(self._objectid, _name, *args, **kwargs)

	def _stream_with_streams(self, _name, *args, **kwargs): # could return a async iterator in the far future
		# type: (str, *Any, **Any) -> MultiDeferredIterator
		_name = str(_name)
		return self._conn._streammethod_with_streams(self._objectid, _name, *args, **kwargs)

	def __repr__(self):
		# type: () -> str
		return "'<RemoteInstance object {} [{}] to {} at {}>'".format(self._classname, self._objectid, self._conn.name, self._conn.addr)

	def __dir__(self):
		return RemoteObjectGeneric.__dir__(self) + ["_call", "_notify", "_stream", "_objectid", "_classname"]

	def __getstate__(self):
		""" just get the state of the remote instance, not of the underlying connection """
		return (self._objectid, self._classname)

	def __setstate__(self, state):
		""" restore the remote instance, assuming there already is the correct underlying connection """
		self._objectid, self._classname = state

	@log_methodcall_decorator
	def __del__(self): # called when garbage collected
		# RemoteObjectGeneric.__del__() # should be called, but doesn't exist
		try:
			self._conn._delinstance(self._objectid)
		except NotAuthenticated:
			pass

class RemoteResult(RemoteObjectGeneric):

	"""Proxy class for remote objects."""

	def __init__(self, conn, sequid, classname):
		RemoteObjectGeneric.__init__(self, conn)
		assert isinstance(classname, str)
		self._sequid = sequid
		self._classname = classname

	def _call(self, _name, *args, **kwargs):
		# type: (str, *Any, **Any) -> RemoteResultDeferred
		_name = str(_name) # this is needed for python2 is it?
		return self._conn._callmethod_by_result(self._sequid, _name, *args, **kwargs)

	def _notify(self, _name, *args, **kwargs):
		# type: (str, *Any, **Any) -> None
		_name = str(_name)
		self._conn._notifymethod_by_result(self._sequid, _name, *args, **kwargs)

	def _stream(self, _name, *args, **kwargs): # could return a async iterator in the far future
		# type: (str, *Any, **Any) -> MultiDeferredIterator
		_name = str(_name)
		return self._conn._streammethod_by_result(self._sequid, _name, *args, **kwargs)

	def __repr__(self):
		return "'<RemoteResult object {} [{}] to {} at {}>'".format(self._classname, self._sequid, self._conn.name, self._conn.addr)

	def __dir__(self):
		return RemoteObjectGeneric.__dir__(self) + ["_call", "_notify", "_stream", "_sequid", "_classname"]

	@log_methodcall_decorator
	def __del__(self): # called when garbage collected
		# RemoteObjectGeneric.__del__() # should be called, but doesn't exist
		try:
			self._conn._delinstance_by_result(self._sequid)
		except NotAuthenticated:
			pass

class NotifyRemoteObject(RemoteObject):
	"""Notifies methods instead of calls"""

	def __init__(self):
		"""__init__ of super class is not called by design"""

	def _call(self, _name, *args, **kwargs):
		self._notify(_name, *args, **kwargs)

	def __repr__(self):
		return "'<NotifyRemoteObject object to {} at {}>'".format(self._conn.name, self._conn.addr)

class StreamRemoteObject(RemoteObject):
	"""Expect a streamed (iterator) response"""

	def __init__(self):
		"""__init__ of super class is not called by design"""

	def _call(self, _name, *args, **kwargs):
		return self._stream(_name, *args, **kwargs) # handle deferred iterator here?

	def __repr__(self):
		return "'<StreamRemoteObject object to {} at {}>'".format(self._conn.name, self._conn.addr)

Notify = partial(cast, class_=NotifyRemoteObject, instanceof=RemoteObject)
Stream = partial(cast, class_=StreamRemoteObject, instanceof=RemoteObject)

def Block(obj):
	assert obj
	raise Exception("Use 'defer.inlineCallbacks' or 'threads.blockingCallFromThread' for that in your function")

"""
def expose(func):
	"Decorator to set exposed flag on a function."
	func._exposed = True
	return func

def is_exposed(func):
	"Test whether another function should be publicly exposed."
	return getattr(func, "_exposed", False)
"""

def call_and_catch_signature_error(_attr, *args, **kwargs):
	try:
		return _attr(*args, **kwargs)
	except TypeError as e:
		try:
			signature(_attr).bind(*args, **kwargs) # do sig test only in error case to preserve resources on successful calls
			raise
		except TypeError:
			raise RPCInvalidArguments(e)

class Service(object):
	"""Baseclass used for RPC Services
	Don't forget to call Service.__init__(self, introspection) in your constructor
	if you don't have a constructor:
		the 'introspection' argument might be exposed to the remote user of the class
	if you do:
		Service is not properly initialized and will lack certain features"""

	def __init__(self, introspection=False, allow_foreign_access=False):
		"""introspection (bool): allows user to remotely call introspection functions
		allow_foreign_access (bool): allow access to objects created by other connections"""

		self._alias = {}

		self._objects = {}
		self._objectids = Seq(0)
		self._allow_foreign_access = allow_foreign_access

		if introspection:
			self.introspect = self._introspect
			self.aliases = self._aliases

	"""def __getitem__(self, key):
		return self._alias[key]

	def __setitem__(self, key, value):
		self._alias[key] = value

	def __delitem__(self, key):
		del self._alias[key]"""

	@classmethod
	def _aliases(cls, aliases):

		""" this is intended to be a decorator used for functions in services.
			yet the decorator is applied at class construction time and has thus no
			access to self. but class wide aliases would be bad."""

		def decorator(func):
			for alias in aliases:
				cls._alias[alias] = func.__name__
			return func
		return decorator

	def _introspect(self):
		"""Returns (classes, methods, functions) with signatures.
		Does not take exposed aliases for private functions into account."""

		"""
		getargspec() is deprecated for python3, replace with signature
		"""

		classes = []
		methods = []
		functions = []
		for key in dir(self):
			if not key.startswith("_"):
				attr = getattr(self, key)
				if inspect.isclass(attr):
					try:
						class_sig = inspect.getargspec(attr.__init__)._asdict()
						class_sig.update({"name": key})
					except ValueError:
						pass
					classes.append(class_sig)
				elif inspect.ismethod(attr):
					method_sig = inspect.getargspec(attr)._asdict()
					method_sig.update({"name": key})
					methods.append(method_sig)
				elif inspect.isfunction(attr):
					function_sig = inspect.getargspec(attr)._asdict()
					function_sig.update({"name": key})
					functions.append(function_sig)
		return (tuple(classes), tuple(methods), tuple(functions))

	def _call(self, _connid, _name, *args, **kwargs):
		"""Dispatches calls on service based on name and type."""
		if not _name.startswith("_"):
			try:
				_name = self._alias.get(_name, _name)
			except AttributeError:
				logger.exception("Maybe '%s.Service.__init__' was not called within service", __modulename__)
			try:
				attr = getattr(self, _name)
			except AttributeError as e:
				raise RPCAttributeError(e)

			# don't differentiate between CALL and NEWINSTANCE
			# decide on called attribute NOT on result, because it would get to powerful otherwise,
			# because every function could (by accident) return any valid object (like rpyc)

			#result = bind_deferreds(call_and_catch_signature_error, attr, *args, **kwargs)
			result = call_and_catch_signature_error(attr, *args, **kwargs) #verify: this should not be able to modify attr
			if inspect.isclass(attr):
				objectid = next(self._objectids)
				self._objects[objectid] = (result, _connid)
				return ObjectId(objectid)
			else:
				return result
		else:
			raise RPCAttributeError("{} instance has no attribute '{}'".format(type(self).__name__, _name))

	def _callmethod(self, _connid, _objectid, _name, *args, **kwargs):
		"""Calls method on objects, created by _call()."""
		try:
			obj, connid_ = self._objects[_objectid]
			if not self._allow_foreign_access and _connid != connid_: # untested security feature
				raise KeyError
		except KeyError:
			raise RPCInvalidObject("No object with id {}".format(_objectid))
		except AttributeError:
			logger.exception("Maybe '%s.Service.__init__' was not called within service", __modulename__)
		return obj._call(_connid, _name, *args, **kwargs) # if this fails with AttributeError: Not inherited from Service?

	def _delete(self, connid, objectid):
		"""Deletes object created by _call."""
		try:
			del self._objects[objectid] # compare connid?
		except KeyError:
			raise RPCInvalidObject("No object with id {}".format(objectid))

	def _delete_all_objects(self, connid):
		"""Deletes all objects created by this connection."""
		try:
			self._objects = {oid: (obj, connid_) for oid, (obj, connid_) in iteritems(self._objects) if connid_ != connid}
		except AttributeError:
			logger.exception("Maybe '%s.Service.__init__' was not called within service", __modulename__)

	def _OnConnect(self): # why doesn't it have 'conn' as argument?
		"""Is called when a new connection to the service is established"""
		pass

	def _OnAuthenticated(self): # why doesn't it have 'pubkey' as argument?
		"""Is called when the connection to the service is authenticated"""
		pass

	def _OnDisconnect(self):
		"""Is called when the connection to the service is closed"""
		pass

	@log_methodcall_decorator
	def __del__(self):
		pass

from .utils import random
class DebugService(Service):

	def __init__(self, *args, **kwargs):
		Service.__init__(self, *args, **kwargs)

	# generator
	def random(self, size, num):
		return random(size, num)

	def echo(self, data):
		return data

class VoidService(Service):
	"""Service which does nothing"""

"""class SubServices(Service):

	services = {}

	def _call(self, _methodname, _servicename, *args, **kwargs):
		try:
			service = self.services[_servicename]
		except KeyError:
			raise RPCNoSuchService(_servicename)

		return service._call(_methodname, *args, **kwargs)

	def _AddService(self, servicefactory, name):
		self.services[name] = servicefactory.build(self)

	def _DelService(self, name):
		del self.services[name]

class SubServicesWithDefault(SubServices): #how will _callSubService be called? use special call, like notify?

	_callSubService = SubService._call
	#_call = SubService.Service._call #does not work
	_call = Service._call #does this work?
"""

class ServiceFactory:
	"""Baseclass for Service factories"""

	def build(self, *args, **kwargs):
		raise NotImplementedError()

class VoidServiceFactory(ServiceFactory):
	"""Factory for services which do nothing"""

	def __init__(self):
		self.service = VoidService()

	def build(self, *args, **kwargs):
		return self.service

class SharedService(ServiceFactory):
	"""Service factory which uses the same service for all connections."""

	def __init__(self, _service, *args, **kwargs):
		self.service = _service(*args, **kwargs)

	def build(self, *args, **kwargs):
		if args or kwargs:
			warnings.warn("build() of SharedService called with arguments, although they are ignored", RuntimeWarning, stacklevel=2)
		return self.service

class SharedUpdatedService(ServiceFactory):
	"""Service factory which uses the same service for all connection but calls build method for each new connection"""

	def __init__(self, _service, *args, **kwargs):
		self.service = _service(*args, **kwargs)

	def build(self, *args, **kwargs):
		self.service.build(*args, **kwargs)
		return self.service

class SeparatedService(ServiceFactory):
	"""Service factory which builds a new service for each connections."""

	def __init__(self, _service, *args, **kwargs):
		self.service = _service
		self.args = args
		self.kwargs = kwargs

	def build(self, *args, **kwargs):
		return self.service(*(self.args + args), **dict(chain(iteritems(self.kwargs), iteritems(kwargs)))) #change order?

"""class SeperatedSubServices(SeperatedService):
	services = {}
	def AddSubService(self, servicefactory, name):
		self.services[name] = servicefactory.build(self) #build here, or build in SubServices._AddService?

	def DelSubService(self, name):
		del self.services[name]

	def build(self, *args, **kwargs):
		service = SeperatedService.build(*args, **kwargs)
		for name, service in iteritems(self.services):
			service._AddService(service, name)
"""
