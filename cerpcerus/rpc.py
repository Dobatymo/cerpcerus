from __future__ import absolute_import, unicode_literals

from functools import partial
from itertools import chain
import inspect, copy, warnings
try:
	from inspect import signature #py3.3+
except ImportError:
	from funcsigs import signature #backport

import logging # debug
logger = logging.getLogger(__name__) # debug

from .utils import cast, Seq, log_methodcall_decorator # decorator only needed for development
from . import __modulename__

"""
todo: take care when remote objects are destroyed... __del__

"""

class RPCAttributeError(AttributeError):
	"""Raised if method access is not allowed. For internal use."""

class RPCInvalidObject(RuntimeError):
	"""Raised if an invalid object is accessed. For internal use."""

class RPCInvalidArguments(TypeError):
	"""Raised if method is accessed with an invalid number of arguments
	or unexpected keyword arguments. For internal use."""

class NotAuthenticated(Exception):
	"""Raised if method is called on object, whose connection
	is not yet or not anymore authenticated."""

class RPCNotAClass(TypeError):
	"""Not used."""

class RPCUserError(int):
	"""Not used yet. Could be raised by functions in rpc service and returns a (self.ERROR, USERERROR, int)"""

class ObjectId(int):
	"""Wrapper to pass around object references"""

class CallAnyPublic(object):
	"""Baseclass which delegates method calls based on leading "_"."""

	def __getattr__(self, name): # only gets invoked for attributes that are not already defined. __getattribute__ would be called always
		if not name.startswith("_"):
			return self._callpublic(name)
		else:
			return self._callprivate(name)

	def __dir__(self):
		raise NotImplementedError("No introspection available")

	def _callpublic(self, name):
		raise NotImplementedError()

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
		raise AttributeError("{} instance has no attribute '{}'".format(type(self).__name__, name)) # vs: __class__.__name__?. don't use RPCAttributeError, because this exception is exposed to the user

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

	def __setstate__(self, conn):
		self._conn = conn

class RemoteObject(RemoteObjectGeneric):

	"""Proxy class for remote functions."""

	def __init__(self, conn):
		RemoteObjectGeneric.__init__(self, conn)
		self._answers = 1

	def _call(self, _name, *args, **kwargs):
		_name = unicode(_name)
		return self._conn._call(_name, self._answers, *args, **kwargs) # type: RemoteResultDeferred

	def _call_with_streams(self, _name, *args, **kwargs):
		_name = unicode(_name)
		return self._conn._call_with_streams(_name, *args, **kwargs) # type: RemoteResultDeferred

	def _notify(self, _name, *args, **kwargs):
		_name = unicode(_name)
		self._conn._notify(_name, *args, **kwargs) # type: None

	def _stream(self, _name, *args, **kwargs): # could return a async iterator in the far future
		_name = unicode(_name)
		return self._conn._stream(_name, *args, **kwargs) # type: MultiDeferredIterator

	def __repr__(self):
		return "'<RemoteObject object to {} at {}>'".format(self._conn.name, self._conn.addr)

	def __dir__(self):
		return RemoteObjectGeneric.__dir__(self) + ["_call", "_notify"]

	def __del__(self):
		pass #todo: disconnect conn?

class RemoteInstance(RemoteObjectGeneric):

	"""Proxy class for remote objects."""

	def __init__(self, conn, objectid, classname):
		RemoteObjectGeneric.__init__(self, conn)
		assert isinstance(classname, unicode)
		self._objectid = objectid
		self._classname = classname
		self._answers = 1

	def _call(self, _name, *args, **kwargs):
		return self._conn._callmethod(self._objectid, _name, self._answers, *args, **kwargs) # type: RemoteResultDeferred

	def _notify(self, _name, *args, **kwargs):
		self._conn._notifymethod(self._objectid, _name, *args, **kwargs) # type: None

	def _stream(self, _name, *args, **kwargs): # could return a async iterator in the far future
		return self._conn._streammethod(self._objectid, _name, *args, **kwargs) # type: MultiDeferredIterator

	def __repr__(self):
		return "'<RemoteInstance object {} [{}] to {} at {}>'".format(self._classname, self._objectid, self._conn.name, self._conn.addr)

	def __dir__(self):
		return RemoteObjectGeneric.__dir__(self) + ["_call", "_notify", "_stream", "_objectid", "_classname"]

	def __getstate__(self):
		return (self._objectid, self._classname)

	def __setstate__(self, conn, objectid, classname):
		RemoteObjectGeneric.__setstate__(self, conn)
		self._objectid = objectid
		self._classname = classname

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
		self._sequid = sequid
		self._classname = classname

	def _call(self, _name, *args, **kwargs):
		return self._conn._callmethodonresult(self._sequid, _name, *args, **kwargs) # type: CallOnDeferred

	def _notify(self, _name, *args, **kwargs):
		self._conn._notifymethodonresult(self._sequid, _name, *args, **kwargs) # type: None

	def _stream(self, _name, *args, **kwargs): # could return a async iterator in the far future
		return self._conn._streammethodonresult(self._sequid, _name, *args, **kwargs) # type: MultiDeferredIterator

	def __repr__(self):
		return "'<RemoteResult object {} [{}] to {} at {}>'".format(self._classname, self._sequid, self._conn.name, self._conn.addr)

	def __dir__(self):
		return RemoteObjectGeneric.__dir__(self) + ["_call", "_notify", "_stream", "_sequid", "_classname"]

	def __getstate__(self):
		return (self._sequid, self._classname)

	def __setstate__(self, conn, sequid, classname):
		RemoteObjectGeneric.__setstate__(self, conn)
		self._sequid = sequid
		self._classname = classname

	@log_methodcall_decorator
	def __del__(self): # called when garbage collected
		# RemoteObjectGeneric.__del__() # should be called, but doesn't exist
		try:
			#self._conn._delinstanceonresult(self._sequid) # this tries to delete results which are not actually objects
			pass
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

class MultiRemoteObject(RemoteObject):

	"""Can be used to set the number of expected answers in RemoteObject"""

	def __init__(self, answers):
		"""__init__ of super class is not called by design"""
		self.answers = answers

	def __repr__(self):
		return "'<MultiRemoteObject object to {} at {}>'".format(self._conn.name, self._conn.addr)

Notify = partial(cast, class_=NotifyRemoteObject, instanceof=RemoteObject)
Multi = partial(cast, class_=MultiRemoteObject, instanceof=RemoteObject)

def Block(obj):
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

def CallWithSignatureError(_attr, *args, **kwargs):
	try:
		return _attr(*args, **kwargs)
	except TypeError as e:
		try:
			signature(_attr).bind(*args, **kwargs) #do sig test only in error case to preserve resources on successful calls
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

	_alias = {}

	def __init__(self, introspection=False, allow_foreign_access=False):
		"""introspection (bool): allows user to remotely call introspection functions
		allow_foreign_access (bool): allow access to objects created by other connections"""

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
		def decorator(func):
			for alias in aliases:
				cls._alias[alias] = func.__name__
			return func
		return decorator

	def _introspect(self):
		"""Returns (classes, methods, functions) with signatures.
		Does not take exposed aliases for private functions into account."""

		classes = []
		methods = []
		functions = []
		for key in dir(self):
			if not key.startswith("_"):
				attr = getattr(self, key)
				if inspect.isclass(attr):
					try:
						signature = inspect.getargspec(attr.__init__)._asdict()
						signature.update({"name": key})
					except ValueError:
						pass
					classes.append(signature)
				elif inspect.ismethod(attr):
					signature = inspect.getargspec(attr)._asdict()
					signature.update({"name": key})
					methods.append(signature)
				elif inspect.isfunction(attr):
					signature = inspect.getargspec(attr)._asdict()
					signature.update({"name": key})
					functions.append(signature)
		return (tuple(classes), tuple(methods), tuple(functions))

	def _aliases(self):
		"""return dict of method aliases. (name -> name) mapping."""
		return self._alias

	def _call(self, _connid, _name, *args, **kwargs):
		"""Dispatches calls on service based on name and type."""
		if not _name.startswith("_"):
			try:
				_name = self._alias.get(_name, _name)
			except AttributeError:
				logging.exception("Maybe '{}.Service.__init__' was not called within service".format(__modulename__))
			try:
				attr = getattr(self, _name)
			except AttributeError as e:
				raise RPCAttributeError(e)

			# don't differentiate between CALL and NEWINSTANCE
			# decide on called attribute NOT on result, because it would get to powerful otherwise,
			# because every function could (by accident) return any valid object (like rpyc)

			#result = bind_deferreds(CallWithSignatureError, attr, *args, **kwargs)
			result = CallWithSignatureError(attr, *args, **kwargs) #verify: this should not be able to modify attr
			if inspect.isclass(attr):
				objectid = self._objectids.next()
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
			logging.exception("Maybe '{}.Service.__init__' was not called within service".format(__modulename__))
		return obj._call(_connid, _name, *args, **kwargs) # if this fails with AttributeError: Not inherited from Service?

	def _delete(self, connid, objectid):
		"""Deletes object created by _call."""
		try:
			del self._objects[objectid] # compare connid?
		except KeyError:
			raise RPCInvalidObject("No object with id {}".format(objectid))

	def _deleteAllObjects(self, connid):
		"""Deletes all objects created by this connection."""
		try:
			self._objects = {oid: (obj, connid_) for oid, (obj, connid_) in self._objects.iteritems() if connid_ != connid}
		except AttributeError:
			logging.exception("Maybe '{}.Service.__init__' was not called within service".format(__modulename__))

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
	def build(self):
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
		if len(args) != 0 or len(kwargs) != 0:
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
		return self.service(*(self.args + args), **dict(chain(self.kwargs.iteritems(), kwargs.iteritems()))) #change order?

"""class SeperatedSubServices(SeperatedService):
	services = {}
	def AddSubService(self, servicefactory, name):
		self.services[name] = servicefactory.build(self) #build here, or build in SubServices._AddService?

	def DelSubService(self, name):
		del self.services[name]

	def build(self, *args, **kwargs):
		service = SeperatedService.build(*args, **kwargs)
		for name, service in self.services.iteritems():
			service._AddService(service, name)
"""
