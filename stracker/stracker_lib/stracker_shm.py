
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

import mmap
import sys
import socket
import os.path
import os
import tempfile
import hashlib
import struct
import pickle
import time
import platform

from stracker_lib.config import config
from ptracker_lib.helpers import *

__all__ = ["get", "set", "ServerError"]

SHM_SIZE = 16384
KEYS = ['alive', 'logfile', 'car_positions', 'session_info', 'classification', 'chat_messages', 'command_from_http']
VERSION = 2
interfaces = {}

class ShmInterface:
    def __init__(self, server):
        if config.DATABASE.database_type == config.DBTYPE_SQLITE3:
            unique_db_id = os.path.abspath(config.DATABASE.database_file)
        elif config.DATABASE.database_type == config.DBTYPE_POSTGRES:
            unique_db_id = config.DATABASE.postgres_db + "@" + socket.gethostbyname(config.DATABASE.postgres_host)
        else:
            raise RuntimeError("database type unknown")
        uuid = hashlib.md5(unique_db_id.encode('utf-8', errors='ignore')).hexdigest()
        self.alive_cnt = 0
        self.alive_cnt_read = 0
        self.lastAliveCntChange = time.time()-1000
        tagname = "stracker-" + uuid + "-" + server
        if platform.system().lower() == "windows":
            self.shm = mmap.mmap(-1, SHM_SIZE, tagname=tagname)
        else:
            filename = os.path.join(tempfile.gettempdir(), tagname)
            self.unique_file = filename
            acdebug("Using '%s' for stracker-internal communications.", self.unique_file)
            self.unique_file_obj = open(filename, "a+b", 0)
            try:
                os.ftruncate(self.unique_file_obj.fileno(), SHM_SIZE)
            except:
                pass
            self.shm = mmap.mmap(self.unique_file_obj.fileno(), SHM_SIZE)
        struct.pack_into("<I", self.shm, 0, VERSION)
        if server == config.STRACKER_CONFIG.server_name:
            self.set('logfile',os.path.abspath(config.STRACKER_CONFIG.log_file))

    def _find(self, key, write = False):
        version, timestamp = struct.unpack_from("<Id", self.shm, 0)
        if version != VERSION:
            raise RuntimeError("Non-matching protocol version")
        if write:
            timestamp = time.time()
            struct.pack_into("<Id", self.shm, 0, version, timestamp)
        offset = struct.calcsize("<Id")
        for k in KEYS:
            #acdebug("%s: %d/%d", k, offset, len(self.shm))
            size, = struct.unpack_from("<I", self.shm, offset)
            offset += struct.calcsize("<I")
            if k == key:
                return offset, size, timestamp
            offset += size
        raise ServerError()

    def alive(self):
        try:
            alive_cnt_read = self.get('alive')
            t = time.time()
            if alive_cnt_read != self.alive_cnt_read:
                self.alive_cnt_read = alive_cnt_read
                self.lastAliveCntChange = t
            if t - self.lastAliveCntChange > 5:
                return False
            else:
                return True
        except KeyError:
            return False

    def get(self, key):
        offset, size, timestamp = self._find(key)
        if size == 0:
            raise ServerError()
        #acdebug("Getting %s (%d bytes) %s", key, size,self.shm[offset:(offset + size)])
        return pickle.loads(self.shm[offset:(offset + size)])

    def set(self, key, value):
        if not key in ["alive", "command_from_http"]:
            self.alive_cnt = (self.alive_cnt + 1)%1000
            self.set('alive', self.alive_cnt)
        vp = pickle.dumps(value)
        reqSize = 64
        while reqSize <= len(vp):
            reqSize *= 2
        offset, size, timestamp = self._find(key)
        if size < reqSize:
            acdebug('allocating %d bytes for %s', reqSize, key)
            new_contents = struct.pack("<I", reqSize)
            new_contents += vp + b" "*(reqSize-len(vp))
            new_contents += self.shm[offset+size:]
            offset -= struct.calcsize("<I")
            acdebug('offset=%d len(shm)=%d len(new_contents)=%d reqSize=%d size=%d', offset, len(self.shm), len(new_contents), reqSize, size)
            self.shm[offset:] = new_contents[:-(reqSize-size)]
        else:
            reqSize = size
            self.shm[offset:offset+len(vp)] = vp
            #acdebug("Setting %s (%d bytes) %s", key, len(vp), vp)

def get(server, key):
    if server is None:
        server = config.STRACKER_CONFIG.server_name
    if not server in interfaces:
        interfaces[server] = ShmInterface(server)
    if not interfaces[server].alive():
        raise ServerError()
    return interfaces[server].get(key)

def set(key, value, server=None):
    if server is None:
        server = config.STRACKER_CONFIG.server_name
    if not server in interfaces:
        interfaces[server] = ShmInterface(server)
    interfaces[server].set(key, value)

class ServerError(RuntimeError):
    pass
