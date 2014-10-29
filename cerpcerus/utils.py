import functools

def partial_decorator(*args, **kwargs):
    def decorator(func):
        return functools.partial(func, *args, **kwargs)
    return decorator

import traceback, logging
def log_methodcall_decorator(func):
    @functools.wraps(func)
    def decorator(self, *args, **kwargs):
        logging.debug("{}.{}({})".format(self.__class__.__name__, func.__name__, args_str(args, kwargs))) #type(self).__name__ ?
        #logging.debug(self.__class__.__name__ + "\n" + "\n".join(map(lambda x: " : ".join(map(str, x)), traceback.extract_stack())))
        return func(self, *args, **kwargs)
    return decorator

def cert_info(cert):
    return "Subject: {}, Issuer: {}, Serial Number: {}, Version: {}".format(cert.get_subject().commonName, cert.get_issuer().commonName, cert.get_serial_number(), cert.get_version())

def args_str(args, kwargs, max=20, app="..."):
    def arg_str(arg):
        arg = repr(arg)
        if len(arg) <= max+len(app):
            return arg
        else:
            return arg[:max] + app
    def kwarg_str(key, value):
        return key + "=" + arg_str(value)
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

class SimpleBuffer(object):

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
        return "".join(self.buffer)

    def __len__(self):
        return self.length
