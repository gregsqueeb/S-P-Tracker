
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

import struct
import bisect
import time
import traceback

import cherrypy

from ptracker_lib.helpers import *
from stracker_lib import config

class ByteCountWrapper(object):

    """Wraps a file-like object, counting the number of bytes read."""

    def __init__(self, rfile):
        self.rfile = rfile
        self.bytes_read = 0

    def read(self, size=-1):
        data = self.rfile.read(size)
        self.bytes_read += len(data)
        return data

    def readline(self, size=-1):
        data = self.rfile.readline(size)
        self.bytes_read += len(data)
        return data

    def readlines(self, sizehint=0):
        # Shamelessly stolen from StringIO
        total = 0
        lines = []
        line = self.readline()
        while line:
            lines.append(line)
            total += len(line)
            if 0 < sizehint <= total:
                break
            line = self.readline()
        return lines

    def close(self):
        self.rfile.close()

    def __iter__(self):
        return self

    def next(self):
        data = self.rfile.next()
        self.bytes_read += len(data)
        return data

class MyStatsTool(cherrypy.Tool):
    def __init__(self):
        cherrypy.Tool.__init__(self, 'on_end_request', self.record_stop)

    def _setup(self):
        cherrypy.Tool._setup(self)
        self.record_start()

    def record_start(self):
        request = cherrypy.serving.request
        if not hasattr(request.rfile, 'bytes_read'):
            request.rfile = ByteCountWrapper(request.rfile)
            request.body.fp = request.rfile

    def record_stop(self, **kwargs):
        try:
            bytesRead = cherrypy.request.rfile.bytes_read
            resp = cherrypy.serving.response
            if not resp.stream:
                bytesWritten = int(resp.headers.get('Content-Length', 0))
            else:
                acdebug("request seems to be streaming...")
                bytesWritten = 0
            globalConnMon.notify_send(time.time(), 255, 254, bytesWritten, 255)
            globalConnMon.notify_rcv(time.time(), 255, 255, bytesRead, 255)
        except:
            acdebug(traceback.format_exc())

cherrypy.tools.mystats = MyStatsTool()

class GlobalConnectionMonitor:
    def __init__(self):
        self.t0 = None
        self.sendTraffic = b""
        self.rcvTraffic = b""
        self.maxSize = 1*1024*1024
        self.fmt = '=IBBHH'
        self.maxItems = self.maxSize // struct.calcsize(self.fmt)

    def pack(self, t, prot_version, request_id, num_bytes, cid):
        if self.t0 is None:
            self.t0 = t
        msSinceStart = int((t-self.t0)*1000.)
        return struct.pack(self.fmt, msSinceStart, prot_version, request_id, num_bytes, cid)

    def trim(self, b):
        l = len(b)
        if l > self.maxSize:
            itemsize = struct.calcsize(self.fmt)
            nItems = l//itemsize
            b = b[(-self.maxItems*itemsize):]
        return b

    def notify_send(self, *args):
        try:
            self.sendTraffic += self.pack(*args)
            self.sendTraffic = self.trim(self.sendTraffic)
        except:
            acdebug("notify_send failed (%s)", str(args))

    def notify_rcv(self, *args):
        try:
            self.rcvTraffic += self.pack(*args)
            self.rcvTraffic = self.trim(self.rcvTraffic)
        except:
            acdebug("notify_rcv failed (%s)", str(args))

    def unpack(self, b):
        up = struct.unpack('=' + self.fmt[1:]*(len(b)//struct.calcsize(self.fmt)), b)
        t = up[0::5]
        prot_version = up[1::5]
        request_id = up[2::5]
        num_bytes = up[3::5]
        cid = up[4::5]
        assert(len(t) == len(prot_version))
        assert(len(t) == len(request_id))
        assert(len(t) == len(num_bytes))
        return t, prot_version, request_id, num_bytes, cid

    def traffic(self, windowSize, deltaTStart, b, t0, rids, pvs):
        rids = set(rids)
        pvs = set(pvs)
        t, prot_version, request_id, num_bytes, cid = self.unpack(b)
        n = round(deltaTStart / windowSize)
        idx = range(n)
        t0 = (t0-self.t0)*1000. - n*windowSize*1000.
        tsample = [t0 + i*windowSize*1000. for i in idx]
        bandwidth = []
        idx2 = bisect.bisect_left(t,tsample[0])
        for t0 in tsample:
            t1 = t0+windowSize*1000.
            idx1 = idx2
            idx2 = bisect.bisect_right(t,t1,idx1,len(t))
            nb = 0
            for i in range(idx1, idx2):
                if request_id[i] in rids and prot_version[i] in pvs:
                    nb += num_bytes[i]
            bandwidth.append(nb/windowSize)
        return tsample,bandwidth

    def traffic_send(self, windowSize, deltaTStart, t0, request_ids, prot_versions):
        return self.traffic(windowSize, deltaTStart, self.sendTraffic, t0, request_ids, prot_versions)

    def traffic_rcv(self, windowSize, deltaTStart, t0, request_ids, prot_versions):
        return self.traffic(windowSize, deltaTStart, self.rcvTraffic, t0, request_ids, prot_versions)

globalConnMon = GlobalConnectionMonitor()

