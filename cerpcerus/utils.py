from __future__ import absolute_import, division, print_function, unicode_literals

from builtins import zip, range

from functools import wraps
from collections import OrderedDict
from typing import TYPE_CHECKING

from genutility.object import cast
from genutility.func import partial_decorator
from genutility.debug import args_str

if TYPE_CHECKING:
	from typing import Iterable
	from OpenSSL.crypto import X509
	from twisted.internet.base import ReactorBase, DelayedCall

# twisted

from twisted.internet import reactor as _reactor
from twisted.internet.defer import Deferred

def sleep(secs, reactor=None):
	# type: (float, ReactorBase) -> Deferred
	if reactor is None:
		reactor = _reactor
	d = Deferred()
	reactor.callLater(secs, d.callback, None)
	return d

def stopreactor(reactor=None):
	# type: (ReactorBase,) -> DelayedCall
	if reactor is None:
		reactor = _reactor
	return reactor.callLater(0, reactor.stop)

# random

from random import choice
from string import ascii_lowercase
def random(size, num):
	for _ in range(num):
		yield "".join(choice(ascii_lowercase) for _ in range(size))

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


class Seq(object):
	"""A sequence class. Used to abstract something like i+=1 for unique ids."""

	def __init__(self, state=0):
		self.state = state

	def __iter__(self):
		"""for iter protocol"""
		return self

	def __next__(self):
		"""Call to set and return next state."""
		self.state += 1
		return self.state

	next = __next__ # py2

def cert_info(cert):
	# type: (X509, ) -> str
	"""user readable certificate information"""

	return "Subject: {}, Issuer: {}, Serial Number: {}, Version: {}".format(cert.get_subject().commonName, cert.get_issuer().commonName, cert.get_serial_number(), cert.get_version())

def argspec_str(name, argspec_od):
	# type: (name, OrderedDict) -> str

	""" test more, make use of OrderedDict property of argspec._asdict() """

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
	arguments = ", ".join(i for i in (args_str(args, kwargs, repr_args=False), prepend_if(d["varargs"], "*"), prepend_if(d["keywords"], "**")) if i)
	return "{}({})".format(name, arguments)

def pprint_introspect(callables):
	# type: (Iterable[Iterable[dict]], ) -> None

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
	
	this is needed because RPCBase cannot inherit from user defined class. But if different protocols
		are to be supported, there needs to be a way to connect the twisted protcol callbacks.
	
	btw:
	def asd(protcol_class):
		class rpc_class(protcol_class):
			pass
		return rpc_class
	a = asd()
	that works...
	"""
	transport.recv_data = protocol.recv_data
	transport.connection_made = protocol.connection_made
	transport.connection_open = protocol.connection_open
	transport.connection_lost = protocol.connection_lost
	#makeConnection ?
