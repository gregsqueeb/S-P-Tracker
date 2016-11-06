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

import select

from .client_server_impl import BaseIF

class TcpIF(BaseIF):

    MODE_SERVER = 0
    MODE_CLIENT = 1
    strMode = {MODE_CLIENT: '[client]',
               MODE_SERVER: '[server]'}

    def __init__(self, mode, parent, optimize, socket):
        BaseIF.__init__(self, optimize)
        self.mode = mode
        self.socket = socket
        self.socket_file_read = socket.makefile('rb')
        self.socket_file_write = socket.makefile('wb')
        self.parent = parent
        self.nWrites = 0
        self.read_dgram = b""

    @debug
    def inc(self):
        self.nWrites += 1

    @debug
    def commit(self):
        #f = io.BytesIO()
        self.socket_file_write.write(struct.pack('<I', self.nWrites))
        self.syncWriteBuffer(self.socket_file_write)
        self.socket_file_write.flush()
        #b = f.getvalue()
        #dgram = struct.pack('<II', self.nWrites, len(b)) + b
        #self.socket.sendall(dgram)
        self.nWrites = 0

    @debug
    def wait(self, lock, timeout = None):
        def recvall(socket, n):
            r = b""
            while len(r) < n:
                chunk = socket.recv(n-len(r))
                protocol_assert(len(chunk) > 0)
                r += chunk
            return r

        t = time.time()
        while 1:
            rlist, wlist, xlist = select.select([self.socket_file_read],[],[],0)
            if len(rlist) > 0:
                with lock:
                    #dgram = recvall(self.socket, 8)
                    nRequests, = struct.unpack('<I', self.socket_file_read.read(4))
                    self.syncReadBuffer(self.socket_file_read)
                    return nRequests
            if not timeout is None and time.time() - t > timeout:
                if debug_protocol >= 1:
                    PRINT("[%s] timout!"%self.strMode[self.mode])
                raise CSTimeoutError
            time.sleep(0.01)

    def statistics(self):
        return ""
