"""stupid blocking code which cannot work"""

import Queue
from functools import partial

from twisted.internet import defer

from cerpcerus.utils import cast
from cerpcerus.rpc import RemoteObject

class RPCTimeout(Queue.Empty): pass

class BlockRemoteObjectQueue(RemoteObject):

    def __init__(self, reactor, timeout=None):
        self._reactor = reactor
        self._timeout = timeout

    def _call(self, name, *args, **kwargs):
        self._queue = Queue.Queue(1)
        d = RemoteObject._call(self, name, *args, **kwargs)
        d.addCallbacks(self._success, self._failure)
        try:
            result, failure = self._queue.get(True, self._timeout)
        except Queue.Empty:
            d.cancel()
            raise RPCTimeout("No result available after {}s".format(self._timeout))
        if failure:
            failure.raiseException()
        else:
            return result

    def _success(self, result):
        self._queue.put((result, None))

    def _failure(self, failure):
        self._queue.put((None, failure))

class BlockRemoteObjectInlineCallback(RemoteObject):

    def __init__(self, timeout = None):
        self._timeout = timeout

    def _call(self, name, *args, **kwargs):
        return self._waitcall(name, *args, **kwargs).result

    @defer.inlineCallbacks
    def _waitcall(self, name, *args, **kwargs):
        d = RemoteObject._call(self, name, *args, **kwargs)
        logging.debug("Waiting on deferred")
        res = yield d
        logging.debug("Deferred called: {}".format(res))
        defer.returnValue(res)

#Blocking call seems to be impossible without threads
Block = partial(cast, class_ = BlockRemoteObjectQueue, instanceof = RemoteObject)
Block = partial(cast, class_ = BlockRemoteObjectInlineCallback, instanceof = RemoteObject)
