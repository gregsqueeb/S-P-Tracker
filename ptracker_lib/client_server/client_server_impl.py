# Copyright 2015-2016 NEYS
# This file is part of sptracker.
#
#    sptracker is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.
#
#    sptracker is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with Foobar.  If not, see <http://www.gnu.org/licenses/>.

import ctypes
import mmap
import time
import struct
import pickle
import pickletools
import traceback
import functools
import io
from collections import namedtuple, deque

PRINT = print

SHM_SIZE = 10*1024*1024 # 10 MB of memory

ServerFunction = namedtuple('ServerFunction', ('args', 'ret', 'id', 'func'))

class CSTimeoutError(Exception):
    pass

class PendingResult:
    __slots__ = ["callback", "call_id", "func_ret", "interface", "func_id", "retVal"]

    def __init__(self, callback, call_id, func_ret, interface, func_id):
        self.callback = callback
        self.call_id = call_id
        self.func_ret = func_ret
        self.interface = interface
        self.func_id = func_id

    def __call__(self):
        if hasattr(self, "retVal"):
            return self.retVal
        raise RuntimeError("Retrieving result before available")

    def __reduce__(self):
        try:
            r = self.retVal
        except AttributeError:
            #PRINT("result of call_id %d not yet available, using reference" % self.call_id)
            return (ARG_REFERENCE, (self.call_id,))
        #PRINT("result of call_id %d available, using it: %s" %(self.call_id, r))
        return (r.__class__, (r,))

def protocol_assert(cond):
    if not cond:
        raise RuntimeError("Protocol Error occurred.")

debug_protocol = 0

if debug_protocol >= 2:
    def debug(f):
        def new_f(*args):
            PRINT("START", f, args)
            r = f(*args)
            PRINT("STOP", f, r)
            return r
        return new_f

    debug_proto = f
elif debug_protocol == 1:
    def debug(f):
        return f

    def debug_proto(f):
        def new_f(*args):
            try:
                r = "Exception!"
                r = f(*args)
                return r
            finally:
                PRINT("%s(%s) -> %s" % (f.__name__, str(args), str(r)))
        return new_f
else:
    def debug(f):
        return f
    debug_proto = debug

class PickleReader:
    def __init__(self):
        self._up = None
        self._file = None
        self._len = 0
        self._batch = None
        self.read = self.read_orig

    def unpack_from(self, file):
        self._file = file
        self._batch = None
        self.read = self.read_orig
        r = self._len
        self._len = 0
        self._up = pickle.Unpickler(file)
        return r

    def read_orig(self):
        if not self._batch is None:
            self.read = self._batch.pop
            return self._batch.pop()
        r = self._up.load()
        try:
            self._len = self._file.tell()
        except io.UnsupportedOperation:
            pass
        if type(r) == PickleBatch:
            self._batch = r
            return self.read()
        return r

class PickleBatch:
    def __init__(self):
        self.objects = deque()

    def add(self, o):
        self.objects.append(o)

    def pop(self):
        return self.objects.popleft()

class PickleWriter:
    def __init__(self, optimize):
        self.optimize = optimize
        self.create()

    def create(self):
        self._b = io.BytesIO()
        self._p = pickle.Pickler(self._b)
        self._batch = PickleBatch()

    def write(self, args):
        self._batch.add(args)

    def pack_to(self, file):
        self._p.dump(self._batch)
        b = self._b.getvalue()
        if self.optimize:
            b = pickletools.optimize(b)
        file.write(b)
        self.create()
        return len(b)

class BaseIF:
    DESC_INT = 0
    DESC_BYTES = 1
    DESC_TUPLE = 2
    DESC_RAW = 3
    DESC_REFERENCE = 4

    ARG_PICKLE = 0
    ARG_STRING = 1
    ARG_BYTES = 2
    class ARG_CALLBACK:
        def __init__(self, *args):
            self.args = args

        def __hash__(self):
            return id(self.args)

        def to_tuple(self):
            return self.args
    class ARG_REFERENCE:
        __slots__ = ["callid"]
        def __init__(self, callid):
            self.callid = callid

    def __init__(self, optimize):
        self.read_stream = PickleReader()
        self.write_stream = PickleWriter(optimize)
        self.read_int = debug_proto(self.read_stream.read)
        self.write_int = debug_proto(self.write_stream.write)
        self.read_bytes = debug_proto(self.read_stream.read)
        self.write_bytes = debug_proto(self.write_stream.write)
        self.read_str = debug_proto(self.read_stream.read)
        self.write_str = debug_proto(self.write_stream.write)

    @debug_proto
    def unpack(self, desc):
        return self.read_stream.read()

    @debug_proto
    def pack(self, desc, data):
        self.write_stream.write(data)

    @debug_proto
    def syncReadBuffer(self, file):
        return self.read_stream.unpack_from(file)

    @debug_proto
    def syncWriteBuffer(self, file):
        return self.write_stream.pack_to(file)


class SharedMemoryHelper(ctypes.Structure):
    _pack_ = 1
    _fields_ = [
        ('numItems', ctypes.c_int32),
    ]

class SharedMemoryIF(BaseIF):

    MODE_SERVER = 0
    MODE_CLIENT = 1
    strMode = {MODE_CLIENT: '[client]',
               MODE_SERVER: '[server]'}

    # this is the state where the server waits for client requests
    # or the client waits for server answers
    # in this state, the interface is guaranteed not to access any of the buffers
    # except requests[:4]
    # the state can be left after self.requests[:4] != int(-1)
    STATE_WAITING_FOR_REQUESTS = 0
    # this is the state where the server is processing requests or
    # the client reads the server answers
    # in this state the interface modifies both buffers
    #    1. the server reads the number of requests
    #    2. the next request is decoded
    #    3. the answer is generated and stored in the answer buffer
    #    4. proceed with 2. until no more requests
    #    5. set the number of answers into the answer buffer
    # afterwards the state is changed into StATE_WAITING_FOR_REQUESTS
    STATE_PROCESSING_REQUESTS = 1

    def __init__(self, mode, parent, optimize, tagName, clientId, timeout):
        BaseIF.__init__(self, optimize)
        self.clientId = clientId
        self.requests = mmap.mmap(-1, SHM_SIZE, tagName + "-%d-requests" % self.clientId)
        self.answers = mmap.mmap(-1, SHM_SIZE, tagName + "-answers")
        if mode == self.MODE_SERVER:
            pass
        elif mode == self.MODE_CLIENT:
            tmp = self.requests
            self.requests = self.answers
            self.answers = tmp
        else:
            raise NotImplementedError
        self.shmRequestHdr = SharedMemoryHelper.from_buffer(self.requests)
        self.shmAnswerHdr = SharedMemoryHelper.from_buffer(self.answers)
        self.hdrSize = ctypes.sizeof(self.shmRequestHdr)
        self.mode = mode
        self.maxRequestSize = self.hdrSize
        self.maxAnswerSize = self.hdrSize
        self.requests.write(b"\x00"*len(self.requests))
        self.nAnswers = 0
        self.parent = parent
        self.state = self.STATE_PROCESSING_REQUESTS
        self._scache = {}
        self.resetRequestQueue()
        tstart = time.time()
        while 1:
            nAnswers = self.shmAnswerHdr.numItems
            if nAnswers == -1:
                break
            time.sleep(0.1)
            if not timeout is None and time.time() - tstart > timeout:
                raise CSTimeoutError
        if mode == self.MODE_SERVER:
            self.state = self.STATE_WAITING_FOR_REQUESTS
        elif mode == self.MODE_CLIENT:
            self.state = self.STATE_PROCESSING_REQUESTS
        if debug_protocol >= 1: PRINT("[%s] construct answers=%s shadow=%s"%
               (self.strMode[self.mode], type(self.answers), type(self.shadowAnswers))
        )

    @debug
    def resetRequestQueue(self):
        if debug_protocol >= 1: PRINT("[%s] resetRequestQueue oldNRequests=%d"%
               (self.strMode[self.mode], struct.unpack_from('i', self.requests)[0])
        )
        protocol_assert(self.state == self.STATE_PROCESSING_REQUESTS)
        self.shmRequestHdr.numItems = -1
        self.state = self.STATE_WAITING_FOR_REQUESTS

    @debug
    def inc(self):
        if debug_protocol >= 1: PRINT("[%s] inc"%
               (self.strMode[self.mode], )
        )
        self.nAnswers += 1

    @debug
    def commit(self):
        protocol_assert(self.state == self.STATE_PROCESSING_REQUESTS)
        self.answers.seek(self.hdrSize)
        s = self.syncWriteBuffer(self.answers)
        self.maxAnswerSize = max(self.maxAnswerSize, s)
        self.resetRequestQueue()
        protocol_assert(self.shmRequestHdr.numItems == -1)
        if debug_protocol >= 1: PRINT("[%s] commit oldNAnswers=%s newNAnswers=%s answers=%s shadow=%s"%
               (self.strMode[self.mode], self.shmAnswerHdr.numItems, self.nAnswers, type(self.answers), type(self.shadowAnswers))
        )
        self.shmAnswerHdr.numItems = self.nAnswers
        #self.shmAnswerHdr.locked = 0
        self.state = self.STATE_WAITING_FOR_REQUESTS
        self.nAnswers = 0

    @debug
    def wait(self, lock, timeout = None):
        t = time.time()
        while 1:
            needsRelease = False
            if not timeout is None:
                ok = lock.acquire(timeout=timeout)
                if not ok:
                    raise CSTimeoutError
                needsRelease = True
            with lock:
                if needsRelease:
                    needsRelease = False
                    lock.release()
                nRequests = self.shmRequestHdr.numItems
                if nRequests >= 0:
                    self.state = self.STATE_PROCESSING_REQUESTS
                    self.shmRequestHdr.numItems = -1
                    self.requests.seek(self.hdrSize)
                    s = self.syncReadBuffer(self.requests)
                    self.maxRequestSize = max(self.maxRequestSize, s)
                    if debug_protocol >= 1: PRINT("[%s] wait -> numItems = %d" % (self.strMode[self.mode], nRequests))
                    return nRequests
                else:
                    protocol_assert(nRequests == -1)
                if not timeout is None and time.time() - t + 0.01 > timeout:
                    if debug_protocol >= 1:
                        PRINT("[%s] timout!"%self.strMode[self.mode])
                    raise CSTimeoutError
            time.sleep(0.01)

    def statistics(self):
        return """\
Max memory usage request buffer: %d bytes (%.1f %%)
Max memory usage answer  buffer: %d bytes (%.1f %%)
""" % (self.maxRequestSize, self.maxRequestSize*100./SHM_SIZE,
       self.maxAnswerSize, self.maxAnswerSize*100./SHM_SIZE)

ARG_CALLBACK = SharedMemoryIF.ARG_CALLBACK
ARG_REFERENCE = SharedMemoryIF.ARG_REFERENCE