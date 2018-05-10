import hashlib
import time
import struct
from ptracker_lib.helpers import *

class DBGuidMapper:
    def __init__(self):
        self.map_orig_to_new = {}
        self.map_new_to_orig = {}
        self.map_new_to_numeric = {}
        self.map_numeric_to_new = {}

        self.new_access_timestamps = {}

    def register_guid_mapping(self, guid_orig, guid_new):
        self.map_orig_to_new[guid_orig] = guid_new
        self.map_new_to_orig[guid_new] = guid_orig
        self.new_access_timestamps[guid_new] = time.clock()
        d = hashlib.md5(guid_new.encode('utf8')).digest() # 16 bytes
        d = struct.unpack('qq', d)
        d = abs(d[0] ^ d[1])
        self.map_new_to_numeric[guid_new] = str(d)
        self.map_numeric_to_new[str(d)] = guid_new

    def guid_orig(self, guid_new):
        if guid_new in self.map_orig_to_new:
            acdebug("GUIDMapper: guid %s seems to be orig already.", guid_new)
            return guid_new
        self.new_access_timestamps[guid_new] = time.clock()
        return self.map_new_to_orig.get(guid_new, guid_new)

    def guid_new(self, guid_orig):
        res = self.map_orig_to_new.get(guid_orig, guid_orig)
        self.new_access_timestamps[res] = time.clock()
        return res

    def guid_numeric(self, guid_new):
        self.new_access_timestamps[guid_new] = time.clock()
        return self.map_new_to_numeric(guid_new)

    def cleanup(self):
        tcurr = time.clock()
        threshold = 24*3600
        todel = []
        for guid,acct in self.new_access_timestamps.items():
            if tcurr - acct > threshold:
                todel.append(guid)
        for guid in todel:
            orig = self.map_new_to_orig[guid]
            num = self.map_new_to_numeric[guid]
            del self.map_orig_to_new[orig]
            del self.map_numeric_to_new[num]
            del self.map_new_to_orig[guid]
            del self.map_new_to_numeric[guid]

    def raw_hash(self, guid):
        if guid.startswith("sha256"):
            raise RuntimeError("Hash of a hash, this is not wanted.")
        m = hashlib.sha256()
        m.update(guid.encode())
        guid_new = "sha256#" + m.hexdigest()
        return guid_new

dbGuidMapper = DBGuidMapper()

