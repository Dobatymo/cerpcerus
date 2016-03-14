import struct
#import logging

from twisted.internet.protocol import Protocol

from utils import SimpleBuffer

class SimpleProtocol(Protocol):

    """Twisted Protocol that assures that packets are not fragmented.
    That means for every send_data() there will be one recv_data() call.
    """

    def __init__(self):
        self._pos = 0
        self._int_len = 4
        self._buf_len = None
        self._length = self._int_len
        self._buffer = SimpleBuffer()

    def send_data(self, data):
        """Send packet"""
        buf_len = struct.pack("!I", len(data))
        self.transport.write(buf_len + data)

    def recv_data(self, data):
        """Receive packet"""
        raise NotImplementedError("recv_data(self, data)")

    def dataReceived(self, data):
        self._pos = 0
        #logging.debug("len(data): {}, pos: {}, length {}".format(len(data), self._pos, self._length))
        while len(data) >= self._pos + self._length - len(self._buffer):
            if self._buf_len is None: #if not self._buf_len doesn't permit 0
                #logging.debug("int:buf_len: {}".format(self._buf_len))
                missing = self._int_len - len(self._buffer)
                #logging.debug("int:missing: {}".format(missing))
                assert missing >= 0, missing
                self._buffer.append(data[self._pos:self._pos+missing])
                assert len(self._buffer) == self._int_len
                self._length = self._buf_len = struct.unpack("!I", self._buffer.get())[0]
                #logging.debug("int:length: {}".format(self._length))
                self._buffer.clear()
                self._pos += missing #self._int_len
                #logging.debug("int:pos: {}".format(self._pos))
            else:
                #logging.debug("buf:buf_len: {}".format(self._buf_len))
                missing = self._buf_len - len(self._buffer)
                #logging.debug("buf:missing: {}".format(missing))
                assert missing >= 0, missing
                self._buffer.append(data[self._pos:self._pos+missing])
                assert len(self._buffer) == self._buf_len
                self.recv_data(self._buffer.get())
                self._buffer.clear()
                self._pos += missing #self._buf_len
                #logging.debug("buf:pos: {}".format(self._pos))
                self._buf_len = None
                self._length = self._int_len
                #logging.debug("int:length: {}".format(self._length))
        assert self._pos <= len(data), (self._pos, len(data))
        if self._pos < len(data):
            self._buffer.append(data[self._pos:])
