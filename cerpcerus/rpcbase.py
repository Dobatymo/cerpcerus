from __future__ import unicode_literals

import logging
from functools import partial

import msgpack
from OpenSSL import SSL, crypto
from twisted.internet import ssl, defer, error

from simple_protocol import SimpleProtocol
from utils import cert_info, args_str
from rpc import Seq, RemoteObject, RemoteInstance, RPCAttributeError, RPCInvalidArguments, RPCInvalidObject, NotAuthenticated, ObjectId

logger = logging.getLogger(__name__)

class RPCError(StandardError):
    """Signals a general rpc error"""

class NetworkError(StandardError):
    """Signals a general rpc network error"""

class ConnectionLost(NetworkError):
    """Raised when the rpc connection is lost or closed"""

class EndAnswer(Exception):
    """Used for flow control like StopIteration."""

class IFriends(object):

    """Interface which defines all methods which friend classes must implement"""

    def key_to_name(self, public_key):
        raise NotImplementedError()

    def update_by_addr(self, addr, conn): #used?
        raise NotImplementedError()

    ### needed for sure, below

    def set_connecting(self, name, deferred):
        raise NotImplementedError()

    def get_by_name(self, name):
        raise NotImplementedError()

    def reset_connection(self, name):
        raise NotImplementedError()

    def reset_connecting(self, name):
        raise NotImplementedError()

    def update_connection_by_name(self, name, conn):
        raise NotImplementedError()

    def update_addr_by_name(self, name, addr):
        raise NotImplementedError()

class SameFriend(IFriends):

    """Simple implementation of IFriends interface.
    Uses the same name for every connection.
    """

    def __init__(self, name):
        self.name = name

    def key_to_name(self, public_key):
        return self.name

    def update_by_addr(self, addr, conn):
        pass

    def set_connecting(self, name, deferred):
        pass

    def get_by_name(self, name):
        return (None, None, None)

class AllFriends(IFriends):

    """Simple implementation of IFriends interface.
    Assigns a unique number as name for every key.
    """

    def __init__(self):
        self.friends = {}
        self.seq = Seq(0)

    def key_to_name(self, public_key):
        try:
            return self.friends[public_key]
        except KeyError:
            self.friends[public_key] = self.seq.next()
            return self.friends[public_key]

    def update_by_addr(self, addr, conn):
        pass

    def set_connecting(self, name, deferred):
        pass

    def reset_connection(self, name):
        pass

    def reset_connecting(self, name):
        pass

    def get_by_name(self, name):
        return (None, None, None)

    def update_connection_by_name(self, name, conn):
        pass

    def update_addr_by_name(self, name, addr):
        pass

#Decorator to avoid c&p
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

class RPCBase(SimpleProtocol):

    NOTIFY = 1
    NOTIFYMETHOD = 2
    CALL = 3
    CALLMETHOD = 4
    DELINSTANCE = 5
    RESULT = 6
    OBJECT = 7
    ERROR = 8

    class ERRORS: #todo: named tuple?
        GeneralError = 0
        NoSuchFunction = 1
        WrongArguments = 2
        NoService = 3
        Deferred = 4
        EndAnswer = 5
        NoSuchClass = 6
        InvalidObject = 7

    connids = Seq(0)

    def __init__(self, friends):
        self.connid = self.connids.next()
        self._sequid = Seq(0) #was static/class var before
        self.friends = friends
        self.name = None
        self.addr = None
        self.service = None
        self._deferreds = {}
        self.authed = False
        self.closed = None

    def connectionMade(self):
        self.addr = IPAddr(self.transport.getPeer().host, self.transport.getPeer().port)
        self.service._OnConnect() #use RemoteObject(self) as argument?
        logger.info("Connection to {!s} established".format(self.addr))
        self.send_data(b"") #because there is no SSLconnectionMade function

    def softDisconnect(self):
        """Disconnects and flushes write buffer first"""
        self.transport.loseConnection()

    def hardDisconnect(self):
        """Disconnects and doesn't flush write buffer"""
        self.transport.abortConnection()

    def connectionLost(self, reason):
        self.service._OnDisconnect() #use RemoteObject(self) as argument?

        if self.authed:
            if reason.check(error.ConnectionDone):
                logger.debug("Connection to {} closed".format(self.name))
            else:
                logger.info("Connection to {} lost: {}".format(self.name, reason.getErrorMessage()))

            self.authed = False
            self.friends.reset_connection(self.name)

            self.service._deleteAllObjects(self.connid)

            if reason.check(error.ConnectionDone):
                for sequid, (deferred, answers, __) in self._deferreds.iteritems(): #untested
                    deferred.errback(ConnectionLost("Connection to {} closed ({} answers remaining)".format(self.name, answers)))
            else:
                for sequid, (deferred, answers, __) in self._deferreds.iteritems(): #untested
                    deferred.errback(ConnectionLost("Connection to {} lost ({} answers remaining): {}".format(self.name, answers, reason.getErrorMessage())))
        else:
            if reason.check(error.ConnectionDone):
                logger.debug("Connection to {} closed".format(self.addr))
            else:
                logger.info("Connection to {} lost: {}".format(self.addr, reason.getErrorMessage()))
            assert len(self._deferreds) == 0
        self.closed = True

    def authenticated(self, name, key):
        self.authed = True
        self.friends.update_addr_by_name(name, self.addr) #bad: sets outgoing instead of incoming  port / overwrites existings addr of possibly currently established connection
        self.friends.update_connection_by_name(name, RemoteObject(self)) # overwrites existings connection
        logger.debug("Connection accepted: {} is now {}".format(self.addr, name))
        self.service._OnAuthenticated() #use RemoteObject(self) as argument?

    def authenticatedFromClient(self, name, key):
        self.authed = True
        self.friends.update_connection_by_name(name, RemoteObject(self)) # overwrites existings connection
        self.friends.reset_connecting(name)
        logger.debug("Connection accepted: {} is now {}".format(self.addr, name))
        self.service._OnAuthenticated() #use RemoteObject(self) as argument?

    ### msgpack hooks

    RemoteInstanceID = 0x05

    def default(self, obj):
        if isinstance(obj, RemoteInstance):
            return msgpack.ExtType(self.RemoteInstanceID, msgpack.dumps(obj.__getstate__()))
        return obj

    def ext_hook(self, n, obj):
        if n == self.RemoteInstanceID:
            objectid, classname = msgpack.loads(obj)
            return RemoteInstance(self, objectid, classname)
        return obj

    ###

    def recv_data(self, data):
        #logger.debug("Received {} {}".format(len(data), hash(data)))
        if self.name and data:
            #msg = msgpack.loads(data, use_list=False, encoding="utf-8") #encoding might create problems with raw data
            msg = msgpack.loads(data, use_list=False, ext_hook=self.ext_hook)
            self.recv_msgpack(msg)
        elif self.name == None and data == b"": #because there is no SSLconnectionMade function
            peer_x509 = self.transport.getPeerCertificate()
            if not peer_x509:
                logger.warning("Peer did not send a certificate")
                self.transport.loseConnection()
                return
            peer_pubkey = crypto.dump_privatekey(crypto.FILETYPE_ASN1, peer_x509.get_pubkey())

            try:
                self.name = self.friends.key_to_name(peer_pubkey)
                #assert conn == None
            except KeyError:
                logger.warning("Connection denied (not in friends list)")
                logger.debug(cert_info(peer_x509))
                self.transport.loseConnection()
                return
            self.authenticated(self.name, peer_pubkey)
        else:
            if not data:
                logger.warning("Received zero length message")
            if not self.name:
                logger.warning("Received unauthenticated message")

    def _success(self, sequid, result):
        if isinstance(result, ObjectId):
            self.send_msgpack((self.OBJECT, sequid, int(result)))
        else:
            self.send_msgpack((self.RESULT, sequid, result))

    def _failure(self, sequid, failure):
        error = failure.trap(EndAnswer)
        if error == EndAnswer:
            msg = (self.ERROR, sequid, self.ERRORS.EndAnswer)
        else:
            msg = (self.ERROR, sequid, self.ERRORS.Deferred)
            logger.exception(failure.getErrorMessage())
        self.send_msgpack(msg)

    def recv_msgpack(self, msg):
        type = msg[0]
        try:
            if type == self.NOTIFY:
                name, args, kwargs = msg[1:]

                logger.debug("notifying local {}({})".format(name, args_str(args, kwargs)))
                if self.service:
                    try:
                        self.service._call(self.connid, name, *args, **kwargs)
                    except RPCAttributeError as e:
                        logger.debug("No Such Function {}".format(name))
                    except TypeError as e: #this is caught even if it is thrown inside the function, instead of while calling the funtion
                        logger.exception("Wrong Arguments")
                    except Exception as e:
                        logger.exception("RPC {}({}) failed".format(name, args_str(args, kwargs)))
                else:
                    logger.debug("No Service")

            elif type == self.NOTIFYMETHOD:
                objectid, name, args, kwargs = msg[1:]

                logger.debug("notifying local method [{}].{}({})".format(objectid, name, args_str(args, kwargs)))
                if self.service:
                    try:
                        self.service._callmethod(self.connid, objectid, name, *args, **kwargs)
                    except RPCInvalidObject as e:
                        logger.debug("Invalid Object {}".format(objectid))
                    except RPCAttributeError as e:
                        logger.debug("No Such Method {}".format(name))
                    except TypeError as e: #this is caught even if it is thrown inside the function, instead of while calling the funtion
                        logger.exception("Wrong Arguments")
                    except Exception as e:
                        logger.exception("RPC {}({}) failed".format(name, args_str(args, kwargs)))
                else:
                    logger.debug("No Service")

            elif type == self.CALL:
                sequid, name, args, kwargs = msg[1:]

                logger.debug("calling local {}({}) [{}]".format(name, args_str(args, kwargs), sequid))
                if self.service:
                    #if name.startswith("_") check not needed. Service does that and raises AttributeError
                    try:
                        result = self.service._call(self.connid, name, *args, **kwargs)
                        #use maybeDeferred ??
                        if isinstance(result, defer.Deferred):
                            result.addCallbacks(partial(self._success, sequid), partial(self._failure, sequid))
                            return
                        elif isinstance(result, ObjectId):
                            msg = (self.OBJECT, sequid, int(result))
                        else:
                            msg = (self.RESULT, sequid, result)

                    except RPCAttributeError as e:
                        msg = (self.ERROR, sequid, self.ERRORS.NoSuchFunction)
                        logger.debug("No Such Function {} [{}]".format(name, sequid))
                    except TypeError as e: #this is caught even if it is thrown inside the function, instead of while calling the funtion
                        msg = (self.ERROR, sequid, self.ERRORS.WrongArguments)
                        logger.exception("Wrong Arguments [{}]".format(sequid))
                    except Exception as e:
                        msg = (self.ERROR, sequid, self.ERRORS.GeneralError)
                        logger.exception("RPC {}({}) [{}] failed".format(name, args_str(args, kwargs), sequid))
                else:
                    msg = (self.ERROR, sequid, self.ERRORS.NoService)
                    logger.debug("No Service [{}]".format(sequid))

                self.send_msgpack(msg)

            elif type == self.CALLMETHOD:
                sequid, objectid, name, args, kwargs = msg[1:]

                logger.debug("calling local method [{}].{}({}) [{}]".format(objectid, name, args_str(args, kwargs), sequid))
                if self.service:
                    try:
                        result = self.service._callmethod(self.connid, objectid, name, *args, **kwargs)
                        if isinstance(result, defer.Deferred):
                            result.addCallbacks(partial(self._success, sequid), partial(self._failure, sequid))
                            return
                        elif isinstance(result, ObjectId):
                            msg = (self.OBJECT, sequid, int(result))
                        else:
                            msg = (self.RESULT, sequid, result)

                    except RPCInvalidObject as e:
                        msg = (self.ERROR, sequid, self.ERRORS.InvalidObject)
                        logger.debug("Invalid Object {}".format(objectid))
                    except RPCAttributeError as e:
                        msg = (self.ERROR, sequid, self.ERRORS.NoSuchFunction)
                        logger.debug("No Such Method {} [{}]".format(name, sequid))
                    except TypeError as e: #this is caught even if it is thrown inside the function, instead of while calling the funtion
                        msg = (self.ERROR, sequid, self.ERRORS.WrongArguments)
                        logger.exception("Wrong Arguments [{}]".format(sequid))
                    except Exception as e:
                        msg = (self.ERROR, sequid, self.ERRORS.GeneralError)
                        logger.exception("RPC {}({}) [{}] failed".format(name, args_str(args, kwargs), sequid))
                else:
                    msg = (self.ERROR, sequid, self.ERRORS.NoService)
                    logger.debug("No Service [{}]".format(sequid))

                self.send_msgpack(msg)

            elif type == self.DELINSTANCE:
                objectid, = msg[1:]

                logger.debug("Deleting local instance [{}]".format(objectid))
                if self.service:
                    try:
                        self.service._delete(self.connid, objectid)
                    except RPCInvalidObject as e:
                        logger.debug("Invalid Object {}".format(objectid))
                    except Exception as e:
                        logger.exception("RPC delete object {} failed".format(objectid))
                else:
                    logger.debug("No Service")

            elif type == self.RESULT:
                sequid, result = msg[1:]
                try:
                    #d = self._deferreds.pop(sequid) #removes deferred (cannot receive replies with same sequid, change?)
                    d, answers, classname = self._deferreds[sequid]
                    if answers == 1:
                        del self._deferreds[sequid]
                    elif answers > 1:
                        self._deferreds[sequid] = (d, answers - 1, classname)
                    #logger.debug("Received result for [{}], calling callback".format(sequid))
                    d.callback(result)
                except KeyError:
                    raise RPCError("Unknown Sequence ID received: {}".format(sequid))

            elif type == self.OBJECT:
                sequid, objectid = msg[1:]
                try:
                    d, answers, classname = self._deferreds.pop(sequid)
                    assert answers == 1
                    #logger.debug("Received object [{}]={} [{}], calling callback".format(objectid, classname, sequid))
                    d.callback(RemoteInstance(self, objectid, classname))
                except KeyError:
                    raise RPCError("Unknown Sequence ID received: {}".format(sequid))

            elif type == self.ERROR:
                sequid, error = msg[1:]
                try:
                    d, answers, classname = self._deferreds.pop(sequid) #removes deferred (cannot receive errors with same sequid, change?)
                    #logger.debug("Received error {} for [{}], calling errback".format(error, sequid))
                    if error == self.ERRORS.EndAnswer:
                        if answers != 0:
                            logger.debug("Error occurred before receiving all remaining {} answer(s) [{}]".format(answers, sequid))
                    elif error == self.ERRORS.NoSuchFunction:
                        d.errback(RPCAttributeError(error))
                    elif error == self.ERRORS.WrongArguments:
                        d.errback(RPCInvalidArguments(error))
                    elif error == self.ERRORS.GeneralError:
                        d.errback(Exception(error))
                    else:
                        d.errback(RPCError(error))
                except KeyError:
                    raise RPCError("Unknown Sequence ID received: {}".format(sequid))
            else:
                raise RPCError("Unknown message type received: {}".format(type))
        except ValueError:
            logger.warning("Received invalid formated rpc message")

    def send_msgpack(self, msg):
        #self.send_data(msgpack.dumps(msg, use_bin_type=True))
        self.send_data(msgpack.dumps(msg, default=self.default))

    @ValidateConnection
    def _notify(self, name, *args, **kwargs):
        logger.debug("notifying remote {}({})".format(name, args_str(args, kwargs)))
        msg = (self.NOTIFY, name, args, kwargs)
        self.send_msgpack(msg)

    @ValidateConnection
    def _notifymethod(self, objectid, name, *args, **kwargs):
        logger.debug("notifying remote method [{}].{}({})".format(objectid, name, args_str(args, kwargs)))
        msg = (self.NOTIFYMETHOD, objectid, name, args, kwargs)
        self.send_msgpack(msg)

    @ValidateConnection
    def _call(self, name, answers, *args, **kwargs):
        sequid = self._sequid.next()
        msg = (self.CALL, sequid, name, args, kwargs)
        logger.debug("calling remote {}({}) [{}]".format(name, args_str(args, kwargs), sequid))
        deferred = defer.Deferred()
        if sequid not in self._deferreds:
            self._deferreds[sequid] = (deferred, answers, name)
        else:
            raise Exception("Should not have happened")
        self.send_msgpack(msg)
        return deferred

    @ValidateConnection
    def _callmethod(self, objectid, name, answers, *args, **kwargs):
        sequid = self._sequid.next()
        msg = (self.CALLMETHOD, sequid, objectid, name, args, kwargs)
        logger.debug("calling remote method [{}].{}({}) [{}]".format(objectid, name, args_str(args, kwargs), sequid))
        deferred = defer.Deferred()
        if sequid not in self._deferreds:
            self._deferreds[sequid] = (deferred, answers, name)
        else:
            raise Exception("Should not have happened")
        self.send_msgpack(msg)
        return deferred

    @ValidateConnection
    def _delinstance(self, objectid):
        msg = (self.DELINSTANCE, objectid)
        logger.debug("deleting remote instance [{}]".format(objectid))
        self.send_msgpack(msg)

class GenericRPCSSLContextFactory(ssl.ContextFactory):

    def __init__(self, public_key, private_key, verify_ca=True, tls_version=SSL.TLSv1_METHOD):
        """public_key and private_key are paths to certificate files
        when verify_ca is true:
            self signed certs are not allowed. A list of valid CA files can be given with 'valid_ca_cert_files'.
            this list can contain the certificates itself for selfsigned ceritifacates
        else:
            self signed certs are allowed.
        tls_version: can be SSL.SSLv2_METHOD, SSLv3_METHOD, SSLv23_METHOD or SSL.TLSv1_METHOD (default and recommended)
        """
        self.public_key = public_key
        self.private_key = private_key
        self.tls_version = tls_version
        self.verify_ca = verify_ca

        self.ctx = SSL.Context(self.tls_version)
        self.ctx.use_certificate_file(self.public_key)
        self.ctx.use_privatekey_file(self.private_key)

        self.ctx.set_verify(SSL.VERIFY_PEER | SSL.VERIFY_FAIL_IF_NO_PEER_CERT, self.verify_callback) #must be called or client does not send certificate at all
        #self.ctx.set_verify_depth(0) #does not change that 'verify_callback' is called twice, why? maybe it's called for every error until ok

        if self.verify_ca:
            for pubkeyfile in self.valid_ca_cert_files():
                try:
                    self.ctx.load_verify_locations(pubkeyfile) #authenticate client public key
                    logger.debug("Authorised '{}'".format(pubkeyfile))
                except SSL.Error as e:
                    logger.debug("Authorising '{}' failed".format(pubkeyfile))

    def getContext(self):
        """Returns the SSL Context object."""
        return self.ctx

    def valid_ca_cert_files(self):
        """Should return a list of files (paths) with valid CA certificates"""
        raise NotImplementedError()

    def verify_callback(self, connection, x509, errnum, errdepth, ok):
        """Is called to verify a certificate.
        return True to indicate a valid
        return False to indicate an invalid certificate.
        """
        #see https://www.openssl.org/docs/apps/verify.html#DIAGNOSTICS for error codes
        if not ok:
            if not self.verify_ca and errnum == 18: #X509_V_ERR_DEPTH_ZERO_SELF_SIGNED_CERT
                logger.info("Allowing self signed certificate from peer: {!s}".format(x509.get_subject()))
                return True
            else:
                logger.warning("Invalid certificate from peer: {!s} [{},{}]: {}".format(
                    x509.get_subject(), errnum, errdepth, crypto.X509_verify_cert_error_string(errnum)))
                return False
        else:
            logger.info("Certificates are valid: {!s}".format(x509.get_subject()))
            return True

class IPAddr(object):
    """Simple class which containts IP and port"""
    def __init__(self, ip, port):
        #self.atyp
        self.ip = ip
        self.port = port

    def __str__(self):
        return "{}:{}".format(self.ip, self.port)

    def __repr__(self):
        return "IPAddr({}, {})".format(self.ip, self.port)

    def __iter__(self):
        return iter((self.ip, self.port))

    def __eq__(self, other):
        if other == None:
            return False
        return self.ip == other.ip and self.port == other.port
