from __future__ import unicode_literals

from functools import partial
from itertools import chain
import inspect, copy, warnings

import logging #debug
logger = logging.getLogger(__name__) #debug

from utils import log_methodcall_decorator #only needed for development

class RPCAttributeError(AttributeError):
    pass
class RPCInvalidObject(RuntimeError):
    pass
class RPCNotAClass(TypeError):
    pass
class RPCInvalidArguments(TypeError):
    pass
class NotAuthenticated(Exception):
    pass

class RPCUserError(int): #could be raised by functions in rpc service and returns a (self.ERROR, USERERROR, int)
    pass

class ObjectId(int):
    pass

class Seq:
    """A sequence class. Used to abstract something like i+=1 for unique ids."""
    def __init__(self, state=0):
        self.state = state

    def next(self):
        self.state += 1
        return self.state

class CallAnyPublic(object):
    """Baseclass which delegates method calls based on leading "_"."""
    def __getattr__(self, name):
        if not name.startswith("_"):
            return self._callpublic(name)
        else:
            return self._callprivate(name)

    def __dir__(self):
        raise NotImplementedError("No introspection available")

    def _callpublic(self, name, *args, **kwargs): #*args etc needed?
        raise NotImplementedError()

    def _callprivate(self, name, *args, **kwargs):
        raise NotImplementedError()

class RemoteObjectGeneric(CallAnyPublic):

    """Generic proxy class for remote network objects."""

    #__getattr__ from CallAnyPublic is not called, if attibute is defined in this class

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
        try:
            name = self._alias[name]
        except KeyError:
            pass
        return partial(self._call, name)

    def _callprivate(self, name, *args, **kwargs):
        if name == "_connid":
            return self._conn.connid
        if name == "_name":
            return self._conn.name
        elif name == "_addr":
            return self._conn.addr
        elif name == "_service":
            return self._conn.service
        else:
            raise AttributeError("{} instance has no attribute '{}'".format(type(self).__name__, name)) #don't use RPCAttributeError, because this exception is exposed to the user

    def _loose(self):
        self._conn.softDisconnect()

    def _abort(self):
        self._conn.hardDisconnect()

    def __repr__(self):
        return "'<RemoteObject object to {} at {}>'".format(self._conn.name, self._conn.addr)

    def __dir__(self):
        return ["_connid", "_name", "_addr", "_service", "_loose", "_abort"]

    def __setstate__(self, conn):
        self._conn = conn

class RemoteObject(RemoteObjectGeneric):

    """Proxy class for remote functions."""

    def __init__(self, conn):
        RemoteObjectGeneric.__init__(self, conn)
        self._answers = 1

    def _call(self, name, *args, **kwargs):
        return self._conn._call(name, self._answers, *args, **kwargs)

    def _notify(self, name, *args, **kwargs):
        self._conn._notify(name, *args, **kwargs)

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
        self._objectid = objectid
        self._classname = classname
        self._answers = 1

    def _call(self, name, *args, **kwargs):
        return self._conn._callmethod(self._objectid, name, self._answers, *args, **kwargs)

    def _notify(self, name, *args, **kwargs):
        self._conn._notifymethod(self._objectid, name, *args, **kwargs)

    def __repr__(self):
        return "'<RemoteInstance object {} [{}] to {} at {}>'".format(self._classname, self._objectid, self._conn.name, self._conn.addr)

    def __dir__(self):
        return RemoteObjectGeneric.__dir__(self) + ["_call", "_notify", "_objectid", "_classname"]

    def __getstate__(self):
        return (self._objectid, self._classname)

    def __setstate__(self, conn, objectid, classname):
        RemoteObjectGeneric.__setstate__(self, conn)
        self._objectid = objectid
        self._classname = classname

    @log_methodcall_decorator
    def __del__(self):
        try:
            self._conn._delinstance(self._objectid)
        except NotAuthenticated:
            pass

def cast(object, class_, instanceof=object, *args, **kwargs):
    """Changes the class of 'object' to class_ if object is an instance of 'instanceof' calls the constructor and returns it"""
    object = copy.copy(object)
    if isinstance(object, instanceof):
        object.__class__ = class_
        object.__init__(*args, **kwargs)
    else:
        raise TypeError("Object is not of type {}".format(class_.__name__))
    return object

class NotifyRemoteObject(RemoteObject):
    """Notifies methods instead of calls"""
    def __init__(self):
        """__init__ of super class is no called by design"""

    def _call(self, name, *args, **kwargs):
        self._notify(name, *args, **kwargs)

    def __repr__(self):
        return "'<NotifyRemoteObject object to {} at {}>'".format(self._conn.name, self._conn.addr)

class MultiRemoteObject(RemoteObject):

    def __init__(self, answers):
        """__init__ of super class is no called by design"""
        self.answers = answers

    def __repr__(self):
        return "'<MultiRemoteObject object to {} at {}>'".format(self._conn.name, self._conn.addr)

Notify = partial(cast, class_=NotifyRemoteObject, instanceof=RemoteObject)
Multi = partial(cast, class_=MultiRemoteObject, instanceof=RemoteObject)

"""import Queue
class RPCTimeout(Queue.Empty): pass
class BlockRemoteObjectQueue(RemoteObject):

    def __init__(self, timeout = None):
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

from twisted.internet import defer
import logging
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
Block = partial(Cast, class_ = BlockRemoteObjectQueue, instanceof = RemoteObject)
Block = partial(Cast, class_ = BlockRemoteObjectInlineCallback, instanceof = RemoteObject)"""
def Block(obj):
    raise Exception("Use defer.inlineCallbacks for that in your function")

class Service(object):
    """Baseclass used for RPC Services
    Dont forget to call Service.__init__(self, introspection) in your contstructor
    if you don't have a constructor:
        the 'introspection' argument might be exposed to the remote user of the class
    if you do:
        Service is not properly initialized and will lack certain features"""

    def __init__(self, introspection=False):
        """introspection (bool): allows user to remotely call introspection functions"""
        self._objects = {}
        self._objectids = Seq(0)
        self._alias = {}
        
        if introspection:
            self.introspect = self._introspect
            self.aliases = self._aliases

    """def __getitem__(self, key):
        return self._alias[key]

    def __setitem__(self, key, value):
        self._alias[key] = value

    def __delitem__(self, key):
        del self._alias[key]"""

    def _introspect(self):
        """returns (classes, methods, functions) with signatures
        does not take exposed aliases for private functions into account"""

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

    def _call(self, connid, name, *args, **kwargs):
        if not name.startswith("_"):
            try:
                try:
                    name = self._alias[name]
                except KeyError:
                    pass
                except AttributeError:
                    logging.exception("Maybe 'myrpc.Service.__init__' was not called within service")
                attr = getattr(self, name)
            except AttributeError as e:
                
                raise RPCAttributeError(e)

            #don't differentiate between CALL and NEWINSTANCE
            #decide on called attribute NOT on result, because if would get to powerful otherwise,
            #because every function could (by accident) return any valid object (like rpyc)

            if inspect.isclass(attr):
                objectid = self._objectids.next()
                self._objects[objectid] = (attr(*args, **kwargs), connid)
                return ObjectId(objectid)
            else:
                return attr(*args, **kwargs)
        else:
            raise RPCAttributeError("{} instance has no attribute '{}'".format(type(self).__name__, name))

    def _callmethod(self, connid, objectid, name, *args, **kwargs):
        try:
            obj, connid_ = self._objects[objectid] #todo: check if connid == connid_
        except KeyError:
            raise RPCInvalidObject("No object with id {}".format(objectid))
        except AttributeError:
            logging.exception("Maybe 'myrpc.Service.__init__' was not called within service")
        return obj._call(connid, name, *args, **kwargs) #if this fails with AttributeError: Not inherited from Service?

    def _delete(self, connid, objectid):
        try:
            del self._objects[objectid]
        except KeyError:
            raise RPCInvalidObject("No object with id {}".format(objectid))

    def _deleteAllObjects(self, connid):
        self._objects = {oid:(obj, connid_) for oid, (obj, connid_) in self._objects.iteritems() if connid_ != connid}

    def _OnConnect(self): #why doesn't it have 'conn' as argument?
        """Is called when a new connection to the service is established"""
        pass

    def _OnAuthenticated(self): #why doesn't it have 'pubkey' as argument?
        """Is called when the connection to the service is authenticated"""
        pass

    def _OnDisconnect(self):
        """Is called when the connection to the service is closed"""
        pass

    @log_methodcall_decorator
    def __del__(self):
        pass

class VoidService(Service):
    """Service which does nothing"""
    pass

"""class SubServices(Service):

    services = {}

    def _call(self, methodname, servicename, *args, **kwargs):
        try:
            service = self.services[servicename]
        except KeyError:
            raise RPCNoSuchService(servicename)

        return service._call(methodname, *args, **kwargs)

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
    def __init__(self, service, *args, **kwargs):
        self.service = service(*args, **kwargs)

    def build(self, *args, **kwargs):
        if len(args) != 0 or len(kwargs) != 0:
            warnings.warn("build() of SharedService called with arguments, although they are ignored", RuntimeWarning, stacklevel=2)
        return self.service

class SharedUpdatedService(ServiceFactory):
    def __init__(self, service, *args, **kwargs):
        self.service = service(*args, **kwargs)

    def build(self, *args, **kwargs):
        self.service.build(*args, **kwargs)
        return self.service

class SeperatedService(ServiceFactory):
    """Service factory which builds a new service for each connections."""
    def __init__(self, service, *args, **kwargs):
        self.service = service
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

if __name__ == "__main__":
    #Some stupid tests...

    #c = CallAnyPublic()
    #c._asd()

    class CallAny(CallAnyPublic):

        def _private(self, num):
            raise NotImplementedError()

    class TestObject(CallAny):

        publicattr = 1
        _privateattr = 1

        def _callpublic(self, name):
            return self.public(1)

        def _callprivate(self, name, *args, **kwargs):
            raise RPCAttributeError("{} instance has no attribute '{}'".format(type(self).__name__, name))

        def public(self, num):
            print("public: {}".format(num))

        def _private(self, num):
            print("private: {}".format(num))

    t = TestObject()
    print(t.publicattr)
    print(t._privateattr)
    t.public(0)
    t._private(0)
