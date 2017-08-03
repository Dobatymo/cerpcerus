import functools
from collections import OrderedDict

from twisted.internet import reactor, defer
def sleep(secs):
	d = defer.Deferred()
	reactor.callLater(secs, d.callback, None)
	return d

from random import choice
from string import ascii_lowercase
def random(size, num):
	for _ in range(num):
		yield "".join(choice(ascii_lowercase) for _ in range(size))

def partial_decorator(*args, **kwargs):
	def decorator(func):
		return functools.partial(func, *args, **kwargs)
	return decorator

def cast(_object, _class, _instanceof=object, *args, **kwargs):
	"""Changes the class of '_object' to '_class' if '_object' is an instance of '_instanceof', calls the constructor and returns it"""
	_object = copy.copy(_object)
	if isinstance(_object, _instanceof):
		object_.__class__ = _class
		object_.__init__(*args, **kwargs)
	else:
		raise TypeError("Object is not an instance of {}".format(_instanceof.__name__))
	return _object

class Seq:
	"""A sequence class. Used to abstract something like i+=1 for unique ids."""
	def __init__(self, state=0):
		self.state = state

	def __iter__(self):
		"""for iter protocol"""
		return self

	def next(self):
		"""Call to set and return next state."""
		self.state += 1
		return self.state

import traceback, logging
def log_methodcall_decorator(func):
	@functools.wraps(func)
	def decorator(self, *args, **kwargs):
		logging.debug("{}.{}({})".format(self.__class__.__name__, func.__name__, args_str(args, kwargs))) #type(self).__name__ ?
		#logging.debug(self.__class__.__name__ + "\n" + "\n".join(map(lambda x: " : ".join(map(str, x)), traceback.extract_stack())))
		return func(self, *args, **kwargs)
	return decorator

def log_methodcall_result(func):
	@functools.wraps(func)
	def decorator(self, *args, **kwargs):
		logging.debug("{}.{}({})".format(self.__class__.__name__, func.__name__, args_str(args, kwargs))) #type(self).__name__ ?
		#logging.debug(self.__class__.__name__ + "\n" + "\n".join(map(lambda x: " : ".join(map(str, x)), traceback.extract_stack())))
		res = func(self, *args, **kwargs)
		logging.debug("{}.{} => {}".format(self.__class__.__name__, func.__name__, res)) #type(self).__name__ ?
		return res
	return decorator

def cert_info(cert):
	"""user readable certificate information"""

	return "Subject: {}, Issuer: {}, Serial Number: {}, Version: {}".format(cert.get_subject().commonName, cert.get_issuer().commonName, cert.get_serial_number(), cert.get_version())

def args_str(args, kwargs, max=20, app="...", repr_args=True):
	"""creates printable string from callable arguments"""

	def arg_str(arg, repr_args=repr_args):
		if repr_args:
			arg = repr(arg)
		assert isinstance(arg, str)
		if max:
			if len(arg) <= max+len(app):
				return arg
			else:
				return arg[:max] + app
		else:
			return arg

	def kwarg_str(key, value):
		return key + "=" + arg_str(value, repr_args=True)

	args = ", ".join(arg_str(arg) for arg in args)
	kwargs = ", ".join(kwarg_str(k, v) for k, v in kwargs.iteritems())

	if args:
		if kwargs:
			return args + ", " + kwargs
		else:
			return args
	else:
		if kwargs:
			return kwargs
		else:
			return ""

def argspec_str(name, argspec_od):
	"""
	test more, make use of OrderedDict property of argspec._asdict()
	"""

	def prepend_if(obj, prep):
		if obj:
			return prep+obj
		else:
			return obj

	d = argspec_od # rename for shorter code

	if d["defaults"]:
		def_len = len(d["defaults"])
		args = d["args"][:-def_len]
		kwargs = OrderedDict(zip(d["args"][def_len:], d["defaults"]))
	else:
		args = d["args"]
		kwargs = OrderedDict()
	vars = ", ".join(i for i in (args_str(args, kwargs, repr_args=False), prepend_if(d["varargs"], "*"), prepend_if(d["keywords"], "**")) if i)
	return "{}({})".format(name, vars)

def pprint_introspect(callables):
	for c in callables:
		for argspec in c:
			name = argspec.pop("name")
			print(argspec_str(name, argspec))

class SimpleBuffer(object):

	"""Just a list of strings"""

	def __init__(self):
		self.length = 0
		self.buffer = []

	def append(self, data):
		self.buffer.append(data)
		self.length += len(data)

	def clear(self):
		self.buffer = []
		self.length = 0

	def get(self):
		return b"".join(self.buffer)

	def __len__(self):
		return self.length

def IProtocolConnector(transport, protocol):
	"""
	transport: not a twisted transport, but a protocol
	protocol: not a twisted protocol but any class (e.g. RPCBase)
	"""
	transport.recv_data = protocol.recv_data
	transport.connection_made = protocol.connection_made
	transport.connection_open = protocol.connection_open
	transport.connection_lost = protocol.connection_lost
	#makeConnection ?
