from __future__ import print_function
import logging
from itertools import izip

from twisted.internet import defer

from cerpcerus.utils import args_str

logger = logging.getLogger(__name__)

def iter_replace(iterable, mytype, replacements):

	""" replace elements of type mytype in iterable with elements from iterable
		replacements"""

	replacements = iter(replacements)
	found_types = []
	replaced = []
	for i in iterable:
		if isinstance(i, mytype):
			found_types.append(i)
			replaced.append(next(replacements))
		else:
			replaced.append(i)
	return (found_types, replaced)

def iter_replace_rec(iterable, mytype, replacements):

	""" unfinished """

	pass

#old
def adv_bind(func, *bind_args):
	"""
	print(adv_bind(test2, 1, "_")(2))
	"""
	def bound(*call_args):
		__, args = iter_replace(bind_args, str, call_args)
		return func(*args)
	return bound

#fixme: correctly handle failures to the next callback
def DeferredDict(dct):
	"""doesn't handle failures"""

	def success(result):
		successes, values = zip(*result)
		return dict(izip(dct.iterkeys(), values))
	
	def failure(failure):
		raise Exception("what to do?")

	if dct:
		deferred = defer.DeferredList(dct.values())
		deferred.addCallbacks(success, failure)
		return deferred
	
	return defer.succeed(dict())

#fixme: correctly handle failures to the next callback
def DeferredTuple(tpl):
	"""doesn't handle failures"""

	def success(result):
		successes, values = zip(*result)
		return values
	
	def failure(failure):
		raise Exception("what to do?")

	if tpl:
		deferred = defer.DeferredList(tpl)
		deferred.addCallbacks(success, failure)
		return deferred
	else:
		return defer.succeed(tuple())

def bind_deferreds(func, *bind_args, **bind_kwargs):
	"""
	func: function to bind arguments to
	bind_args: can be a mix of normal function arguments and deferreds.
	the return value is a deferred whose callback will be called with the
	results of the function evaluated with the bound parameters and succeeded deferreds.
	the same deferred can occur multiple times in the argument list as
	DeferredList handles that case also.
	
	currently unoptimized, meaning the arguments list has to be traversed two times.
	Once to find the deferreds and once during replacement in the callback
	"""

	#deferreds_args = [(pos,i) for i in enumerate(bind_args) if isinstance(i, defer.Deferred)]
	deferreds_args = [i for i in bind_args if isinstance(i, defer.Deferred)]
	deferreds_kwargs = {k:v for k, v in bind_kwargs if isinstance(v, defer.Deferred)}

	def success(result):
		(success_args, value_args), (success_kwargs, value_kwargs) = result
		__, args = iter_replace(bind_args, defer.Deferred, value_args) #is it faster to use pos information here?
		bind_kwargs.update(value_kwargs)
		logger.debug("calling %s(%s) [with deferred results]", func.__name__, args_str(args, bind_kwargs))
		return func(*args, **bind_kwargs)

	def failure(failure): #failure evaluating arguments
		logging.warning(failure)
		failure.raiseException()

	if deferreds_args or deferreds_kwargs:
		d_args = DeferredTuple(deferreds_args)
		d_kwargs = DeferredDict(deferreds_kwargs)
		deferred = defer.DeferredList([d_args, d_kwargs])
		deferred.addCallbacks(success, failure)
		return deferred
	else:
		logger.debug("calling %s(%s) [without deferreds]", func.__name__, args_str(bind_args, bind_kwargs))
		return defer.maybeDeferred(func, *bind_args, **bind_kwargs)
