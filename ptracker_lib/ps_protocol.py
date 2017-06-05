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

import pickle
import struct
import zlib
import random
import traceback
import time
try:
    from stracker_lib.stacktracer import ShortlyLockedRLock as RLock
except ImportError:
    from threading import RLock
from threading import Thread
from ptracker_lib.helpers import *
from ptracker_lib.message_types import *

class ProtocolError(Exception):
    def __init__(self, value):
        self.value = value

    def __str__(self):
        return 'Protocol error: %s' % self.value

def simulateConnectionProblem(f):
    def new_f(self, *args, **kw):
        if self.clientMode:
            myassert (random.randint(0, 1000) > 200)
        return f(self, *args, **kw)
    return new_f

class CompressedConnection:
    cnt = 0

    def __init__(self, socket):
        self.cid = CompressedConnection.cnt
        CompressedConnection.cnt += 1
        acdebug("Creating connection monitor (%d)", self.cid)
        self.socket = socket
        self.prot_version = 0

        self.compObj = None
        self.decompObj = None
        self.pendingReadData = b""

    def enableCompression(self):
        self.enableRcvCompression()
        self.enableSendCompression()

    def enableRcvCompression(self):
        if self.decompObj is None:
            self.decompObj = zlib.decompressobj()

    def enableSendCompression(self):
        if self.compObj is None:
            self.compObj = zlib.compressobj()

    def sendCompressionEnabled(self):
        return not self.compObj is None

    def sendall(self, dgram, dgramID = -1):
        if not self.compObj is None:
            dgram = self.compObj.compress(dgram)
            dgram += self.compObj.flush(zlib.Z_SYNC_FLUSH)
            dgram = struct.pack('I', len(dgram)) + dgram
        return self.socket.sendall(dgram)

    def recv(self, cnt):

        def recv(socket,cnt):
            res = b""
            while len(res) < cnt:
                d = socket.recv(cnt-len(res))
                if len(d) == 0:
                    acdebug("Socket recv received 0 bytes. Something's wrong?")
                    acdebug("\n".join(traceback.format_stack()))
                    myassert(0)
                res += d
            return res

        if self.decompObj is None:
            return recv(self.socket, cnt)
        else:
            if len(self.pendingReadData) < cnt:
                assert(len(self.pendingReadData) == 0)
                d = recv(self.socket, 4)
                s, = struct.unpack('I', d)
                self.pendingReadData = self.decompObj.decompress(recv(self.socket,s))
            res = self.pendingReadData[:cnt]
            self.pendingReadData = self.pendingReadData[cnt:]
            return res

    def recvDone(self, dgramID = -1):
        pass

    def shutdown(self):
        pass

class ProtocolHandler:

    # protocol version
    PROT_VERSION = 16

    # requests as seen from ptracker as client and stracker as server
    REQ_PROTO_START = 0
    ANS_PROTO_START = 1
    REQ_SIGNIN = 2
    ANS_SIGNIN = 3
    REQ_SEND_LAP_INFO = 4
    ANS_SEND_LAP_INFO = 5
    REQ_GET_GUID = 6
    ANS_GET_GUID = 7
    REQ_GET_LAP_STATS = 8
    ANS_GET_LAP_STATS = 9
    REQ_GET_SESSION_STATS = 10
    ANS_GET_SESSION_STATS = 11
    REQ_SERVER_DATA_CHANGED = 12 # sent from server to client to inform him, that it is a good idea to request server data, no answer expected
    REQ_GET_SERVER_DATA = 14
    ANS_GET_SERVER_DATA = 15
    REQ_SEND_SETUP = 16
    ANS_SEND_SETUP = 17
    REQ_GET_LAP_DETAILS = 18
    ANS_GET_LAP_DETAILS = 19
    REQ_DEPOSIT_GET = 20
    ANS_DEPOSIT_GET = 21
    REQ_DEPOSIT_SAVE = 22
    ANS_DEPOSIT_SAVE = 23
    REQ_DEPOSIT_REMOVE = 24
    ANS_DEPOSIT_REMOVE = 25
    REQ_SERVER_DATA_CHANGED_WITH_PAYLOAD = 26 # no answer expected
    REQ_GET_LAP_DETAILS_WITH_HI = 28
    ANS_GET_LAP_DETAILS_WITH_HI = 29
    REQ_ENABLE_SEND_COMPRESSION = 30 # no answer expected
    REQ_GET_PTS_RESPONSE = 32
    ANS_GET_PTS_RESPONSE = 33
    REQ_POST_PTS_REQUEST = 34 # same like GET_PTS_RESPONSE, but the answer is transmitted asynchronously by REQ_POST_PTS_REQEUST
    ANS_POST_PTS_REQUEST = 35
    REQ_POST_PTS_REPLY = 36 # no answer expected

    # capabilities
    CAP_HAS_STRACKER                   = (1 << 0)
    CAP_SEND_SETUP                     = (1 << 1)
    CAP_PUSH_SERVER_DATA               = (1 << 2)
    CAP_LAPCNT_BESTTIMES_AND_LASTTIMES = (1 << 3)
    CAP_LAP_DETAILS                    = (1 << 4)
    CAP_SETUP_DEPOSIT                  = (1 << 5)
    CAP_PTS_PROTOCOL                   = (1 << 6)

    def __init__(self, sock, clientMode = False):
        self.maxTransmitSize_pre12 = 32768
        self.maxTransmitSize_post12 = 1024*1024*10 # 10 MB should be plenty
        self.maxHistoryInfoSize = 16384
        self.socket = CompressedConnection(sock)
        self.prot_version = self.PROT_VERSION
        self.clientMode = clientMode
        self.server_data_state = {'pti':{}, 'session_state':{}}

    def shutdown(self):
        self.socket.shutdown()

    def getCapabilities(self):
        res = self.CAP_HAS_STRACKER
        if self.prot_version >= 3:
            res = res | self.CAP_SEND_SETUP
            res = res | self.CAP_PUSH_SERVER_DATA
        if self.prot_version >= 4:
            res = res | self.CAP_LAPCNT_BESTTIMES_AND_LASTTIMES
        if self.prot_version >= 5:
            res = res | self.CAP_LAP_DETAILS
        if self.prot_version >= 6:
            res = res | self.CAP_SETUP_DEPOSIT
        if self.prot_version >= 12:
            res = res | self.CAP_PTS_PROTOCOL
        return res

    def req_proto_start(self, port):
        dgram = self._request_pack(self.REQ_PROTO_START, trackerid="ptracker client", port=port)
        self.socket.sendall(dgram, self.REQ_PROTO_START)
        self.socket.prot_version = self.prot_version

    def ans_proto_start(self):
        dgram = self._request_pack(self.ANS_PROTO_START, trackerid="stracker server")
        self.socket.sendall(dgram, self.ANS_PROTO_START)
        self.socket.prot_version = self.prot_version
        if self.prot_version == 8:
            self.socket.enableCompression()

    def req_enable_send_compression(self):
        dgram = self._request_pack(self.REQ_ENABLE_SEND_COMPRESSION)
        self.socket.sendall(dgram, self.REQ_ENABLE_SEND_COMPRESSION)
        self.socket.enableSendCompression()

    def req_signin(self, trackname, guid, car,
                   ac_version, pt_version,
                   track_checksum, car_checksum):
        dgram= self._request_pack(self.REQ_SIGNIN, trackname=trackname, guid=guid, car=car,
                                  ac_version=ac_version, pt_version=pt_version,
                                  track_checksum=track_checksum, car_checksum=car_checksum)
        self.socket.sendall(dgram, self.REQ_SIGNIN)

    def ans_signin(self, ok):
        dgram= self._request_pack(self.ANS_SIGNIN, ok=ok)
        self.socket.sendall(dgram, self.ANS_SIGNIN)

    def req_send_lap_info(self, lapTime, sectorTimes, sectorsAreSoftSplits, tyre,
                          valid, lapHistoryCompressed, staticAssists, dynamicAssists,
                          maxSpeed, timeInPitLane, timeInPit, escKeyPressed, ballast,
                          fuelRatio):
        dgram= self._request_pack(self.REQ_SEND_LAP_INFO, lapTime=lapTime, sectorTimes=sectorTimes,
                                  sectorsAreSoftSplits=sectorsAreSoftSplits,
                                  tyre=tyre, valid=valid, lapHistoryCompressed=lapHistoryCompressed,
                                  staticAssists=staticAssists, dynamicAssists=dynamicAssists,
                                  maxSpeed=maxSpeed, timeInPitLane=timeInPitLane, timeInPit=timeInPit,
                                  escKeyPressed=escKeyPressed, ballast=ballast, fuelRatio=fuelRatio)
        self.socket.sendall(dgram, self.REQ_SEND_LAP_INFO)

    def ans_send_lap_info(self, ok):
        if self.prot_version < 8:
            dgram= self._request_pack(self.ANS_SEND_LAP_INFO, ok=ok)
            self.socket.sendall(dgram,self.ANS_SEND_LAP_INFO)

    def req_get_guid(self, driver):
        dgram= self._request_pack(self.REQ_GET_GUID, driver=driver)
        self.socket.sendall(dgram,self.REQ_GET_GUID)

    def ans_get_guid(self, guid):
        dgram= self._request_pack(self.ANS_GET_GUID, guid=guid)
        self.socket.sendall(dgram,self.ANS_GET_GUID)

    def req_lap_stats(self, mode, limit, track, artint, cars, ego_guid, valid, minSessionStartTime):
        dgram= self._request_pack(self.REQ_GET_LAP_STATS,
                                  mode=mode,
                                  limit=limit,
                                  track=track,
                                  artint=artint,
                                  cars=cars,
                                  ego_guid=ego_guid,
                                  valid=valid,
                                  minSessionStartTime=minSessionStartTime)
        self.socket.sendall(dgram,self.REQ_GET_LAP_STATS)

    def ans_lap_stats(self, bestSectors, laps, totalNumLaps):
        dgram= self._request_pack(self.ANS_GET_LAP_STATS, bestSectors=bestSectors, laps=laps)
        self.socket.sendall(dgram,self.ANS_GET_LAP_STATS)

    def req_session_stats(self, limit, tracks, sessionTypes, ego_guid, minSessionStartTime, minNumPlayers, multiplayer):
        dgram = self._request_pack(self.REQ_GET_SESSION_STATS,
                                   limit=limit,
                                   tracks=tracks,
                                   sessionTypes=sessionTypes,
                                   ego_guid=ego_guid,
                                   minSessionStartTime=minSessionStartTime,
                                   minNumPlayers=minNumPlayers,
                                   multiplayer=multiplayer)
        self.socket.sendall(dgram,self.REQ_GET_SESSION_STATS)

    def ans_session_stats(self, sessions):
        if self.prot_version >= 2:
            dgram = self._request_pack(self.ANS_GET_SESSION_STATS, sessions=sessions)
            self.socket.sendall(dgram,self.ANS_GET_SESSION_STATS)

    def req_lap_details(self, lapid):
        dgram = self._request_pack(self.REQ_GET_LAP_DETAILS, lapid=lapid)
        self.socket.sendall(dgram,self.REQ_GET_LAP_DETAILS)

    def req_lap_details_with_hi(self, lapid):
        dgram = self._request_pack(self.REQ_GET_LAP_DETAILS_WITH_HI, lapid=lapid)
        self.socket.sendall(dgram,self.REQ_GET_LAP_DETAILS_WITH_HI)

    def ans_lap_details(self, lap_details):
        if self.prot_version >= 5:
            dgram = self._request_pack(self.ANS_GET_LAP_DETAILS, lap_details=lap_details)
            self.socket.sendall(dgram,self.ANS_GET_LAP_DETAILS)

    def ans_lap_details_with_hi(self, lap_details):
        if self.prot_version >= 5:
            dgram = self._request_pack(self.ANS_GET_LAP_DETAILS_WITH_HI, lap_details=lap_details)
            self.socket.sendall(dgram,self.ANS_GET_LAP_DETAILS_WITH_HI)

    def req_server_data_changed(self):
        if self.prot_version >= 3:
            dgram = self._request_pack(self.REQ_SERVER_DATA_CHANGED)
            self.socket.sendall(dgram,self.REQ_SERVER_DATA_CHANGED)

    def get_sd_payload(self, pti, session_state, messages):

        def get_delta(new_dict, old_dict):
            res = {}
            for k in new_dict.keys():
                if not k in old_dict:
                    res[k] = new_dict[k]
                elif type(new_dict[k]) == dict:
                    d = get_delta(new_dict[k], old_dict[k])
                    res[k] = d
                else:
                    if new_dict[k] != old_dict[k]:
                        res[k] = new_dict[k]
            return res

        opti = self.server_data_state['pti']
        oss = self.server_data_state['session_state']

        pti_dict = {}
        for pi in pti:
            pti_dict[pi['guid']] = pi
        delta_pti = get_delta(pti_dict, opti)
        for guid in pti_dict.keys():
            if not guid in delta_pti:
                delta_pti[guid] = {}
        delta_session_state = get_delta(session_state, oss)

        self.server_data_state['pti'] = pti_dict
        self.server_data_state['session_state'] = session_state

        delta_pti_list = []
        for guid in pti_dict.keys():
            delta_pti_list.append(delta_pti[guid])
            delta_pti_list[-1]['guid'] = guid

        return dict(delta_pti=delta_pti_list, delta_session_state=delta_session_state, messages=messages)

    def set_sd_payload(self, delta_pti, delta_session_state, messages):
        delta_pti_dict = {}
        for pti in delta_pti:
            delta_pti_dict[pti['guid']] = pti

        pti_dict = {}
        for guid in delta_pti_dict:
            # set old data
            pti_dict[guid] = self.server_data_state['pti'].get(guid, {})
            # replace with delta data
            for k in delta_pti_dict[guid]:
                pti_dict[guid][k] = delta_pti_dict[guid][k]

        session_state = self.server_data_state['session_state']
        for k in delta_session_state:
            session_state[k] = delta_session_state[k]

        self.server_data_state = {'pti': pti_dict, 'session_state': session_state}

        pti_list = []
        for guid in pti_dict:
            pti_list.append(pti_dict[guid])
            pti_list[-1]['guid'] = guid
        return dict(ptracker_instances = pti_list, session_state = session_state, messages = messages)

    def req_server_data_changed_with_payload(self, ptracker_instances, session_state, messages):
        if self.prot_version >= 8:
            req = self.REQ_SERVER_DATA_CHANGED_WITH_PAYLOAD
            dgram = self._request_pack(req, **self.get_sd_payload(ptracker_instances, session_state, messages))
        elif self.prot_version >= 3:
            req = self.REQ_SERVER_DATA_CHANGED
            dgram = self._request_pack(req)
        self.socket.sendall(dgram,req)

    def req_get_server_data(self, guid):
        if self.prot_version >= 3:
            dgram = self._request_pack(self.REQ_GET_SERVER_DATA, guid=guid)
            self.socket.sendall(dgram,self.REQ_GET_SERVER_DATA)

    def ans_get_server_data(self, ptracker_instances, session_state, messages):
        if self.prot_version >= 8:
            req = self.REQ_SERVER_DATA_CHANGED_WITH_PAYLOAD
            dgram = self._request_pack(req, **self.get_sd_payload(ptracker_instances, session_state, messages))
        if self.prot_version >= 3:
            req = self.ANS_GET_SERVER_DATA
            dgram = self._request_pack(req, ptracker_instances=ptracker_instances, session_state=session_state, messages=messages)
        self.socket.sendall(dgram,req)

    def req_send_setup(self, target_guid, setup, setup_car):
        if self.prot_version >= 3:
            dgram = self._request_pack(self.REQ_SEND_SETUP, target_guid=target_guid, setup=setup, setup_car=setup_car)
            self.socket.sendall(dgram,self.REQ_SEND_SETUP)

    def ans_send_setup(self, ok):
        if self.prot_version >= 3 and self.prot_version < 8:
            dgram = self._request_pack(self.ANS_SEND_SETUP, ok=ok)
            self.socket.sendall(dgram,self.ANS_SEND_SETUP)

    def req_deposit_get(self, car, track, setupid):
        if self.prot_version >= 6:
            dgram = self._request_pack(self.REQ_DEPOSIT_GET, car=car, track=track, setupid=setupid)
            self.socket.sendall(dgram,self.REQ_DEPOSIT_GET)

    def ans_deposit_get(self, setups, selectedSet, memberOfGroup):
        if self.prot_version >= 6:
            dgram = self._request_pack(self.ANS_DEPOSIT_GET, setups=setups, selectedSet=selectedSet, memberOfGroup=memberOfGroup)
            self.socket.sendall(dgram,self.ANS_DEPOSIT_GET)

    def req_deposit_save(self, car, track, name, groupid, setup):
        if self.prot_version >= 6:
            dgram = self._request_pack(self.REQ_DEPOSIT_SAVE, car=car, track=track, name=name, groupid=groupid, setup=setup)
            self.socket.sendall(dgram,self.REQ_DEPOSIT_SAVE)

    def ans_deposit_save(self, ok):
        if self.prot_version >= 6:
            dgram = self._request_pack(self.ANS_DEPOSIT_SAVE, ok=ok)
            self.socket.sendall(dgram,self.ANS_DEPOSIT_SAVE)

    def req_deposit_remove(self, setupid):
        if self.prot_version >= 6:
            dgram = self._request_pack(self.REQ_DEPOSIT_REMOVE, setupid=setupid)
            self.socket.sendall(dgram,self.REQ_DEPOSIT_REMOVE)

    def ans_deposit_remove(self, ok):
        if self.prot_version >= 6:
            dgram = self._request_pack(self.ANS_DEPOSIT_REMOVE, ok=ok)
            self.socket.sendall(dgram,self.ANS_DEPOSIT_REMOVE)

    # following requests are deprecated and will be removed...
    def req_get_pts_response(self, url):
        if self.prot_version >= 12:
            dgram = self._request_pack(self.REQ_GET_PTS_RESPONSE, url=url)
            self.socket.sendall(dgram, self.REQ_GET_PTS_RESPONSE)
        else:
            raise NotImplementedError

    def ans_get_pts_response(self, content, ctype, cacheable):
        if self.prot_version >= 12:
            dgram = self._request_pack(self.ANS_GET_PTS_RESPONSE, content=content, ctype=ctype, cacheable=cacheable)
            self.socket.sendall(dgram, self.ANS_GET_PTS_RESPONSE)
        else:
            raise NotImplementedError

    # use these instead
    def req_post_pts_request(self, url):
        if self.prot_version >= 13:
            dgram = self._request_pack(self.REQ_POST_PTS_REQUEST, url=url)
            self.socket.sendall(dgram, self.REQ_POST_PTS_REQUEST)
        else:
            raise NotImplementedError

    def ans_post_pts_request(self, ansId):
        if self.prot_version >= 13:
            dgram = self._request_pack(self.ANS_POST_PTS_REQUEST, ansId=ansId)
            self.socket.sendall(dgram, self.ANS_POST_PTS_REQUEST)
        else:
            raise NotImplementedError

    def req_post_pts_reply(self, content, ctype, cacheable, ansId):
        if self.prot_version >= 13:
            dgram = self._request_pack(self.REQ_POST_PTS_REPLY, content=content, ctype=ctype, cacheable=cacheable, ansId=ansId)
            self.socket.sendall(dgram, self.REQ_POST_PTS_REPLY)
        else:
            raise NotImplementedError

    # uncomment the following for simulating a connection prob
    #@simulateConnectionProblem
    def _request_pack(self, req, **kw):
        packed = struct.pack('<HH', self.prot_version, req)
        if req == self.REQ_PROTO_START:
            trackerid = kw['trackerid']
            port = kw['port']
            packed += self._pack_short_string(trackerid)
            packed += struct.pack('<I', port)
        elif req == self.ANS_PROTO_START:
            trackerid = kw['trackerid']
            packed += self._pack_short_string(trackerid)
        elif req == self.REQ_SIGNIN:
            trackname = kw['trackname']
            guid = kw['guid']
            car = kw['car']
            ac_version = kw['ac_version']
            pt_version = kw['pt_version']
            track_checksum = kw['track_checksum']
            car_checksum = kw['car_checksum']
            packed += self._pack_string(trackname)
            packed += self._pack_string(guid)
            packed += self._pack_string(car)
            packed += self._pack_string(ac_version)
            packed += self._pack_string(pt_version)
            packed += self._pack_string(track_checksum)
            packed += self._pack_string(car_checksum)
        elif req in [self.ANS_SIGNIN, self.ANS_SEND_LAP_INFO]:
            ok = kw['ok']
            packed += struct.pack('<B', int(ok))
        elif req == self.REQ_SEND_LAP_INFO:
            lapTime = kw['lapTime']
            sectorTimes = list(map(lambda x: x or 0, kw['sectorTimes']))
            sectorTimes = sectorTimes + [0]*(10-len(sectorTimes))
            tyre = kw['tyre']
            valid = kw['valid']
            sectorsAreSoftSplits = kw['sectorsAreSoftSplits']
            acdebug("REQ_SEND_LAP_INFO: %s %s", lapTime, str(sectorTimes))
            packed += struct.pack('<11I', lapTime, *sectorTimes)
            packed += self._pack_string(tyre)
            packed += struct.pack('<bb', int(valid), int(sectorsAreSoftSplits))
            if self.prot_version <= 7:
                lapHistoryCompressed = kw['lapHistoryCompressed']
                if len(lapHistoryCompressed) > self.maxHistoryInfoSize:
                    # avoid sending a very large lap history
                    lapHistoryCompressed = b""
                packed += self._pack_bytes(lapHistoryCompressed)
            if self.prot_version >= 4:
                assists = kw['dynamicAssists'].copy()
                assists.update(kw['staticAssists'])
                packed += self._pack_dict(assists,
                    [("ABS","i"),("autoBlib","i"),("autoBrake","i"),("autoClutch","i"),
                     ("autoShifter","i"),("idealLine","i"),("input_method",self._pack_string),
                     ("shifter","i"),("stabilityControl","f"),
                     ("tractionControl","i"),("visualDamage","i")])
                packed += self._pack_dict(kw['dynamicAssists'], [("ABS","f"),("tractionControl","f"),("ambientTemp","i"),("trackTemp","i")])
            if self.prot_version >= 5:
                packed += struct.pack('<f', kw['maxSpeed'])
                packed += self._pack_dict(kw['staticAssists'], [("tyreBlankets", "i"), ("slipStream", "f")])
            if self.prot_version >= 6:
                packed += struct.pack('<ii', kw['timeInPitLane'], kw['timeInPit'])
            if self.prot_version >= 7:
                packed += struct.pack('<B', kw['escKeyPressed'])
            if self.prot_version >= 11:
                packed += struct.pack('<f', kw['ballast'])
            if self.prot_version >= 14:
                packed += struct.pack('<f', kw['fuelRatio'])
        elif req == self.REQ_GET_GUID:
            driver = kw['driver']
            packed += self._pack_string(driver)
        elif req == self.ANS_GET_GUID:
            guid = kw['guid']
            packed += self._pack_string(guid)
        elif req == self.REQ_GET_LAP_STATS:
            mode = kw['mode']
            limit = kw['limit']
            track = kw['track']
            artint = kw['artint']
            cars = kw['cars']
            ego_guid = kw['ego_guid']
            valid = kw['valid']
            minSessionStartTime = kw['minSessionStartTime']
            packed += self._pack_string(mode)
            if limit[0] is None:
                packed += struct.pack('<bII', 1, 0, limit[1])
            else:
                packed += struct.pack('<bII', 2, max(0,limit[0]), limit[1])
            packed += self._pack_string(track)
            packed += struct.pack('<bI', artint, len(cars))
            for c in cars:
                packed += self._pack_string(c)
            packed += self._pack_string(ego_guid)
            if self.prot_version >= 2:
                packed += struct.pack('<%db' % (len(valid)+1), len(valid), *valid)
                packed += struct.pack('<I', minSessionStartTime)
        elif req == self.ANS_GET_LAP_STATS:
            laps = kw['laps']
            bestSectors = [int(x+0.5) if not x is None and x >= 0 else 0 for x in kw['bestSectors']]
            packed += struct.pack('<b%dI' % len(bestSectors), len(bestSectors), *bestSectors)
            packed += struct.pack('<I', len(laps))
            for r in laps:
                packed += struct.pack('<IIbII', r['pos'], r['lapTime'], r['valid'], r['timeStamp'], r['id'])
                packed += self._pack_string(r['name'])
                packed += self._pack_string(r['car'])
                packed += self._pack_string(r['tyre'])
                packed += self._pack_string(r['guid'])
                sectors = list(map(lambda x: x or 0, r['sectors']))
                packed += struct.pack('<b%dI' % len(sectors), len(sectors), *sectors)
                if self.prot_version >= 4:
                    packed += self._pack_dict(r,[("penalties", "b"),
                                                 ("tyreWear", "f"),
                                                 ("fuelRate", "f"),
                                                 ("damage", "f"),
                                                 ("abs", "i"),
                                                 ("autoBlib", "b"),
                                                 ("autoBrake", "b"),
                                                 ("autoClutch", "b"),
                                                 ("autoShift", "b"),
                                                 ("idealLine", "b"),
                                                 ("stabilityControl", "f"),
                                                 ("tractionControl", "b"),
                                                 ("visualDamage", "b"),
                                                 ("inputMethod", self._pack_string),
                                                 ("inputShifter", "b"),
                                                 ("maxABS", "f"),
                                                 ("maxTC", "f"),
                                                 ("tempAmbient", "i"),
                                                 ("tempTrack", "i")])
                if self.prot_version >= 5:
                    packed += self._pack_dict(r,[("tyreBlankets", "i"), ("slipStream", "f"), ("maxSpeed", "f"), ("bestServerLap", "i")])
        elif req == self.REQ_GET_SESSION_STATS:
            if self.prot_version < 2:
                raise NotImplementedError()
            limit=kw['limit']
            tracks=kw['tracks']
            sessionTypes=kw['sessionTypes']
            ego_guid=kw['ego_guid']
            minSessionStartTime=kw['minSessionStartTime']
            minNumPlayers=kw['minNumPlayers']
            multiplayer=kw['multiplayer']
            if limit[0] is None:
                packed += struct.pack('<bII', 1, 0, limit[1])
            else:
                packed += struct.pack('<bII', 2, max(0,limit[0]), limit[1])
            if tracks is None:
                packed += struct.pack('<b', 1)
            else:
                packed += struct.pack('<bI', 2, len(tracks))
                for t in tracks:
                    packed += self._pack_string(t)
            if sessionTypes is None:
                packed += struct.pack('<b', 1)
            else:
                packed += struct.pack('<bI', 2, len(sessionTypes))
                for t in sessionTypes:
                    packed += self._pack_string(t)
            packed += self._pack_string(ego_guid)
            packed += struct.pack('<II', minSessionStartTime, minNumPlayers)
            packed += struct.pack('<I%dI' % len(multiplayer), len(multiplayer), *multiplayer)
        elif req == self.ANS_GET_SESSION_STATS:
            if self.prot_version < 2:
                raise NotImplementedError()
            sessions = kw['sessions']
            packed += struct.pack('<I', len(sessions))
            for r in sessions:
                packed += struct.pack('<bbbbbbbbbb', *map(lambda x: x is None,
                                      [r['id'], r['type'], r['podium'][0], r['podium'][1], r['podium'][2],
                                       r['posSelf'], r['numPlayers'], r['timeStamp'], r['multiplayer'], r['counter']]))
                if not r['id'] is None: packed += struct.pack('<I', r['id'])
                if not r['type'] is None: packed += self._pack_string(r['type'])
                if not r['podium'][0] is None: packed += self._pack_string(r['podium'][0])
                if not r['podium'][1] is None: packed += self._pack_string(r['podium'][1])
                if not r['podium'][2] is None: packed += self._pack_string(r['podium'][2])
                if not r['posSelf'] is None: packed += struct.pack('<H', r['posSelf'])
                if not r['numPlayers'] is None: packed += struct.pack('<H', r['numPlayers'])
                if not r['timeStamp'] is None: packed += struct.pack('<I', r['timeStamp'])
                if not r['multiplayer'] is None: packed += struct.pack('<b', r['multiplayer'])
                if not r['counter'] is None: packed += struct.pack('<I', r['counter'])
        elif req in [self.REQ_GET_LAP_DETAILS, self.REQ_GET_LAP_DETAILS_WITH_HI]:
            if self.prot_version < 5:
                raise NotImplementedError
            lapid = kw['lapid']
            packed += struct.pack('<I', lapid)
        elif req in [self.ANS_GET_LAP_DETAILS, self.ANS_GET_LAP_DETAILS_WITH_HI]:
            if self.prot_version < 5:
                raise NotImplementedError
            ld = kw['lap_details']
            hi = ld['historyinfo']
            if not hi is None and len(hi) > self.maxHistoryInfoSize:
                ld['historyinfo'] = None
            if self.prot_version >= 9 and req == self.ANS_GET_LAP_DETAILS:
                # remove the historyInfo blob and just add information,
                # that there is a historyinfo
                if not ld['historyinfo'] is None:
                    ld['historyinfo_available'] = True
                    ld['historyinfo'] = None
            pickleStr = pickle.dumps(ld)
            packed += self._pack_bytes(pickleStr)
        elif req == self.REQ_SERVER_DATA_CHANGED:
            if self.prot_version < 3:
                raise NotImplementedError()
            if self.prot_version >= 8:
                pass
        elif req == self.REQ_GET_SERVER_DATA:
            if self.prot_version < 3:
                raise NotImplementedError()
            packed += self._pack_string(kw['guid'])
        elif req == self.ANS_GET_SERVER_DATA:
            ptracker_instances = kw['ptracker_instances']
            packed += struct.pack('<I', len(ptracker_instances))
            for pi in ptracker_instances:
                packed += self._pack_string(pi['guid'])
                packed += self._pack_string(pi['name'])
                packed += struct.pack('<I', pi['ptracker_conn'])
                if 'setup' in pi:
                    packed += struct.pack('<b', 1)
                    packed += self._pack_string(pi['setup_car'])
                    packed += self._pack_bytes(zlib.compress(pi['setup']))
                else:
                    packed += struct.pack('<b', 0)
                if self.prot_version >= 4:
                    packed += self._pack_dict(pi, [("best_time","i"),("lap_count","i"),("last_time","i")])
            if self.prot_version >= 4:
                packed += self._pack_dict(kw['session_state'],
                    [("penaltiesEnabled", "i"), ("allowedTyresOut", "i"), ("tyreWearFactor", "f"), ("fuelRate", "f"), ("damage", "f")])
            if self.prot_version >= 5:
                msgs = kw['messages']
                packed += struct.pack('<I', len(msgs))
                for m in msgs:
                    packed += self._pack_string(m['text'])
                    packed += struct.pack('<ffff', *m['color'])
                    if self.prot_version >= 6:
                        packed += struct.pack('<i', m['type'])
        elif req == self.REQ_SEND_SETUP:
            target_guid = kw['target_guid']
            carname = kw['setup_car']
            setup = kw['setup']
            packed += self._pack_string(target_guid)
            packed += self._pack_string(carname)
            packed += self._pack_bytes(zlib.compress(setup))
        elif req == self.ANS_SEND_SETUP:
            ok = kw['ok']
            packed += struct.pack('<b', ok)
        elif req == self.REQ_DEPOSIT_GET:
            #dgram = self._request_pack(self.REQ_DEPOSIT_GET, car=car, track=track, setupid=setupid)
            packed += self._pack_dict(kw, [("car", self._pack_string), ("track", self._pack_string), ("setupid", "i")])
        elif req == self.ANS_DEPOSIT_GET:
            #dgram = self.request_pack(self.ANS_DEPOSIT_GET, setups=setups, selectedSet=selectedSet)
            setups = kw['setups']
            selset = kw['selectedSet']
            memberOfGroup = kw['memberOfGroup']
            if not selset['set'] is None:
                selset['set'] = zlib.compress(selset['set'])
            packed += struct.pack('<i', len(setups))
            for s in setups:
                #setupid=a[0], name=a[1], sender=a[2], group=a[3]))
                packed += self._pack_dict(s, [("setupid", "i"),
                                              ("name", self._pack_string),
                                              ("sender", self._pack_string),
                                              ("group", self._pack_string),
                                              ("owner", "i")])
            packed += self._pack_dict(selset, [("id", "i"), ("set", self._pack_bytes)])
            packed += struct.pack('<i', len(memberOfGroup))
            for g in memberOfGroup:
                packed += self._pack_dict(g, [("group_id", "i"), ("group_name", self._pack_string)])
        elif req == self.REQ_DEPOSIT_SAVE:
            #dgram = self.request_pack(self.REQ_DEPOSIT_SAVE, car=car, track=track, name=name, groupid=groupid, setup=setup)
            kw['setup'] = zlib.compress(kw['setup'])
            packed += self._pack_dict(kw, [("car", self._pack_string),
                                             ("track", self._pack_string),
                                             ("name", self._pack_string),
                                             ("groupid", "i"),
                                             ("setup", self._pack_bytes)])
        elif req == self.ANS_DEPOSIT_SAVE:
            #dgram = self.request_pack(self.ANS_DEPOSIT_SAVE, ok=ok)
            packed += self._pack_dict(kw, [("ok", "i")])
        elif req == self.REQ_DEPOSIT_REMOVE:
            #dgram = self._request_pack(self.REQ_DEPOSIT_REMOVE, setupid=setupid)
            packed += self._pack_dict(kw, [("setupid", "i")])
        elif req == self.ANS_DEPOSIT_REMOVE:
            #dgram = self._request_pack(self.ANS_DEPOSIT_REMOVE, ok=ok)
            packed += self._pack_dict(kw, [("ok", "i")])
        elif req == self.REQ_SERVER_DATA_CHANGED_WITH_PAYLOAD:
            # - num_guids: byte
            #   for_each guid:
            #   - guid: byte[8]
            #   - features: byte (1: name | 2: ptconn | 4: setup | 8: best_time | 16:  last_time | 32: lap_count | 64: team | 128: tyre | 256: connected | 512: currLapInvalidated |
            #                     1024: mr rating | 2048: server carid
            #   [ - name: string ]
            #   [ - ptconn: byte ]
            #   [ - setup: - car: string, - file: bytes]
            #   [ - best_time: int ]
            #   [ - last_time: int ]
            #   [ - lap_count: int16 ]
            #   [ - team: string ]
            #   [ - tyre: string ]
            #   [ - connected: int8]
            #   [ - currLapInvalidated: int8]
            #   [ - mr rating: string ]
            #   [ - server carId: int8 ]
            # - session_state_features: byte (1: penaltiesEnabled | 2: allowedTyresOut | 4: tyreWearFactor | 8: fuelRate | 16: damage)
            # [- penaltiesEnabled: byte]
            # [- allowedTyresOut: byte]
            # [- tyreWearFactor: float]
            # [- fuelRate: float]
            # [- damage: float]
            # - number_of_messages: byte
            #   for each message:
            #   - message_text: string
            #   - type: int16
            #   - message_color: (byte, byte, byte, byte)
            pti = kw['delta_pti']
            session_state = kw['delta_session_state']
            messages = kw['messages']
            npti = []
            # kicked players have an invalid guid :(
            for pi in pti:
                try:
                    guid = pi['guid']
                    int(guid)
                    npti.append(pi)
                except ValueError:
                    pass
            pti = npti
            packed += struct.pack('<b', len(pti))
            for pi in pti:
                guid = pi['guid']
                features = 0
                if 'name' in pi: features = features | 1
                if 'ptracker_conn' in pi: features = features | 2
                if 'setup' in pi: features = features | 4
                if 'best_time' in pi: features = features | 8
                if 'last_time' in pi: features = features | 16
                if 'lap_count' in pi: features = features | 32
                if 'team' in pi: features = features | 64
                if 'tyre' in pi: features = features | 128
                if self.prot_version >= 11 and 'connected' in pi: features = features | 256
                if self.prot_version >= 11 and 'currLapInvalidated' in pi: features = features | 512
                if self.prot_version >= 15 and 'mr_rating' in pi: features = features | 1024
                if self.prot_version >= 16 and 'carid' in pi: features = features | 2048
                if self.prot_version >= 11:
                    packed += struct.pack('<QH', int(guid), features)
                else:
                    packed += struct.pack('<QB', int(guid), features)
                if features & 1 : packed += self._pack_string(pi['name'])
                if features & 2 : packed += struct.pack('<b', pi['ptracker_conn'])
                if features & 4 : packed += self._pack_string(pi['setup_car'])
                if features & 4 : packed += self._pack_bytes(zlib.compress(pi['setup']))
                if features & 8 : packed += struct.pack('<i', pi['best_time'] if not pi['best_time'] is None else -4242)
                if features & 16: packed += struct.pack('<i', pi['last_time'] if not pi['last_time'] is None else -4242)
                if features & 32: packed += struct.pack('<h', pi['lap_count'] if not pi['lap_count'] is None else -4242)
                if features & 64: packed += self._pack_string(pi['team'])
                if features & 128: packed += self._pack_string(pi['tyre'])
                if features & 256: packed += struct.pack('<b', pi['connected'])
                if features & 512: packed += struct.pack('<b', pi['currLapInvalidated'])
                if features & 1024: packed += self._pack_string(pi['mr_rating'])
                if features & 2048: packed += struct.pack('<b', pi['carid'])
            features = 0
            if 'penaltiesEnabled' in session_state: features = features | 1
            if 'allowedTyresOut' in session_state: features = features | 2
            if 'tyreWearFactor' in session_state: features = features | 4
            if 'fuelRate' in session_state: features = features | 8
            if 'damage' in session_state: features = features | 16
            if self.prot_version >= 10:
                if 'ptrackerTyresOut' in session_state: features = features | 32
            packed += struct.pack('<b', features)
            if features & 1 : packed += struct.pack('<b', session_state['penaltiesEnabled'])
            if features & 2 : packed += struct.pack('<b', session_state['allowedTyresOut'])
            if features & 4 : packed += struct.pack('<f', session_state['tyreWearFactor'])
            if features & 8 : packed += struct.pack('<f', session_state['fuelRate'])
            if features & 16: packed += struct.pack('<f', session_state['damage'])
            if self.prot_version >= 10:
                if features & 32: packed += struct.pack('<b', session_state['ptrackerTyresOut'])
            if self.prot_version >= 11:
                adminpwd = session_state.get('adminpwd', None)
                if adminpwd != None:
                    packed += struct.pack('<b', 1)
                    packed += self._pack_string(adminpwd)
                else:
                    packed += struct.pack('<b', 0)
            packed += struct.pack('<b', len(messages))
            for m in messages:
                packed += self._pack_string(m['text'])
                packed += struct.pack('<hBBBB', m['type'], *(round(m['color'][k]*255) for k in range(4)))
        elif req == self.REQ_ENABLE_SEND_COMPRESSION:
            # just a notify
            pass
        elif req in [self.REQ_GET_PTS_RESPONSE, self.REQ_POST_PTS_REQUEST]:
            packed += self._pack_string(kw['url'])
        elif req in [self.ANS_GET_PTS_RESPONSE, self.REQ_POST_PTS_REPLY]:
            packed += self._pack_string(kw['ctype'])
            packed += self._pack_bytes(kw['content'])
            packed += struct.pack('<B', kw['cacheable'])
            if req == self.REQ_POST_PTS_REPLY:
                packed += struct.pack('<I', kw['ansId'])
        elif req == self.ANS_POST_PTS_REQUEST:
            packed += struct.pack('<I', kw['ansId'])
        else:
            raise ProtocolError('Unknown request ID %d' % req)
        return packed

    def _pack_string(self, s):
        return self._pack_bytes(s.encode('utf-8'))

    def _pack_short_string(self, s):
        return self._pack_short_bytes(s.encode('utf-8'))

    def _pack_bytes(self, b):
        mts = self.maxTransmitSize_pre12 if self.prot_version < 12 else self.maxTransmitSize_post12
        if len(b) > mts:
            raise ProtocolError('Size to transmit is too large: %d bytes' % len(b))
        if self.prot_version < 12:
            return struct.pack('<H%ds' % len(b), len(b), b)
        else:
            return struct.pack('<I%ds' % len(b), len(b), b)

    def _pack_short_bytes(self, b):
        mts = self.maxTransmitSize_pre12
        if len(b) > mts:
            raise ProtocolError('Size to transmit is too large: %d bytes' % len(b))
        return struct.pack('<H%ds' % len(b), len(b), b)

    def _pack_dict(self, d, keys):
        res = b""
        for k,pid in keys:
            v = d.get(k, None)
            if type(pid) == type(""):
                res += struct.pack("<b" + pid, [0,1][not v is None], [0,v][not v is None])
            elif pid == self._pack_string:
                res += struct.pack("<b", [0,1][not v is None]) + self._pack_string(["",v][not v is None])
            elif pid == self._pack_bytes:
                res += struct.pack("<b", [0,1][not v is None]) + self._pack_bytes([bytes(),v][not v is None])
            else:
                myassert(False)
        return res

    def unpack_item(self):
        prot_version, req = self._unpack_from_format('<HH')
        self.prot_version = min(self.prot_version, prot_version)
        res = {}
        #if prot_version != self.PROT_VERSION:
        #    raise ProtocolError('Protocol version mismatch (received %d, implemented %d).' % (prot_version, self.PROT_VERSION))
        if req == self.REQ_SIGNIN:
            res['trackname'] = self._unpack_string()
            res['guid'] = self._unpack_string()
            res['car'] = self._unpack_string()
            res['ac_version'] = self._unpack_string()
            res['pt_version'] = self._unpack_string()
            res['track_checksum'] = self._unpack_string()
            res['car_checksum'] = self._unpack_string()
        elif req == self.REQ_PROTO_START:
            res['trackerid'] = self._unpack_short_string()
            res['port'], = self._unpack_from_format('<I')
        elif req == self.ANS_PROTO_START:
            res['trackerid'] = self._unpack_short_string()
        elif req in [self.ANS_SIGNIN, self.ANS_SEND_LAP_INFO]:
            res['ok'], = self._unpack_from_format('<B', )
        elif req == self.REQ_SEND_LAP_INFO:
            res['lapTime'], *res['sectorTimes'] = self._unpack_from_format('<11I')
            res['tyre'] = self._unpack_string()
            res['valid'],res['sectorsAreSoftSplits'] = self._unpack_from_format('<bb')
            if self.prot_version <= 7:
                res['lapHistoryCompressed'] = self._unpack_bytes()
                if res['lapHistoryCompressed'] == b"":
                    res['lapHistoryCompressed'] = None
            else:
                res['lapHistoryCompressed'] = None
            if self.prot_version >= 4:
                res['staticAssists'] = self._unpack_dict(
                    [("ABS","i"),("autoBlib","i"),("autoBrake","i"),("autoClutch","i"),
                     ("autoShifter","i"),("idealLine","i"),("input_method",self._unpack_string),
                     ("shifter","i"),("stabilityControl","f"),
                     ("tractionControl","i"),("visualDamage","i")])
                res['dynamicAssists'] = self._unpack_dict([("ABS","f"),("tractionControl","f"),("ambientTemp","i"),("trackTemp","i")])
                res['dynamicAssists']['autoShifter'] = res['staticAssists'].get('autoShifter', None)
                res['dynamicAssists']['idealLine'] = res['staticAssists'].get('idealLine', None)
            if self.prot_version >= 5:
                res['maxSpeed'], = self._unpack_from_format('<f')
                res['staticAssists'].update(self._unpack_dict(
                    [("tyreBlankets", "i"), ("slipStream", "f")]))
            if self.prot_version >= 6:
                res['timeInPitLane'], res['timeInPit'] = self._unpack_from_format('<ii')
            if self.prot_version >= 7:
                res['escKeyPressed'], = self._unpack_from_format('<B')
            if self.prot_version >= 11:
                res['ballast'], = self._unpack_from_format('<f')
            if self.prot_version >= 14:
                res['fuelRatio'], = self._unpack_from_format('<f')
        elif req == self.REQ_GET_GUID:
            res['driver'] = self._unpack_string()
        elif req == self.ANS_GET_GUID:
            res['guid'] = self._unpack_string()
        elif req == self.REQ_GET_LAP_STATS:
            res['mode'] = self._unpack_string()
            lm, *limit = self._unpack_from_format('<bII')
            if lm == 1:
                limit[0] = None
            else:
                myassert (lm == 2)
            res['limit'] = limit
            res['track'] = self._unpack_string()
            res['artint'], lenCars = self._unpack_from_format('<bI')
            myassert(lenCars < 30)
            res['cars'] = []
            for i in range(lenCars):
                res['cars'].append(self._unpack_string())
            res['ego_guid'] = self._unpack_string()
            if prot_version >= 2:
                lv, = self._unpack_from_format('<b')
                res['valid'] = self._unpack_from_format('<%db' % lv)
                res['minSessionStartTime'], = self._unpack_from_format('<I')
            else:
                res['valid'] = [1,2]
                res['minSessionStartTime'] = 0
        elif req == self.ANS_GET_LAP_STATS:
            n, = self._unpack_from_format('<b')
            bestSectors = self._unpack_from_format('<%dI' % n)
            bestSectors = list(map(lambda x: x or None, bestSectors))
            n, = self._unpack_from_format('<I')
            laps = []
            for i in range(n):
                r = {}
                r['pos'], r['lapTime'], r['valid'], r['timeStamp'], r['id'] = self._unpack_from_format('<IIbII')
                r['name'] = self._unpack_string()
                r['car'] = self._unpack_string()
                r['tyre'] = self._unpack_string()
                r['guid'] = self._unpack_string()
                ns, = self._unpack_from_format('<b')
                r['sectors'] = self._unpack_from_format('<%dI' % ns)
                r['sectors'] = list(map(lambda x: x or None, r['sectors']))
                if self.prot_version >= 4:
                    r.update(self._unpack_dict([("penalties", "b"),
                                                ("tyreWear", "f"),
                                                ("fuelRate", "f"),
                                                ("damage", "f"),
                                                ("abs", "i"),
                                                ("autoBlib", "b"),
                                                ("autoBrake", "b"),
                                                ("autoClutch", "b"),
                                                ("autoShift", "b"),
                                                ("idealLine", "b"),
                                                ("stabilityControl", "f"),
                                                ("tractionControl", "b"),
                                                ("visualDamage", "b"),
                                                ("inputMethod", self._unpack_string),
                                                ("inputShifter", "b"),
                                                ("maxABS", "f"),
                                                ("maxTC", "f"),
                                                ("tempAmbient", "i"),
                                                ("tempTrack", "i")]))
                if self.prot_version >= 5:
                    r.update(self._unpack_dict([("tyreBlankets", "i"),
                                                ("slipStream", "f"),
                                                ("maxSpeed", "f"),
                                                ("bestServerLap", "i")]))
                laps.append(r)
            res = {'bestSectors':bestSectors, 'laps':laps}
        elif req == self.REQ_GET_SESSION_STATS:
            lm, *limit = self._unpack_from_format('<bII')
            if lm == 1:
                limit[0] = None
            else:
                myassert (lm == 2)
            tn, = self._unpack_from_format('<b')
            if tn == 1:
                tracks = None
            else:
                myassert (tn == 2)
                tn, = self._unpack_from_format('<I')
                tracks = []
                for i in range(tn):
                    tracks.append(self._unpack_string())
            tn, = self._unpack_from_format('<b')
            if tn == 1:
                sessionTypes = None
            else:
                myassert (tn == 2)
                tn, = self._unpack_from_format('<I')
                sessionTypes = []
                for i in range(tn):
                    sessionTypes.append(self._unpack_string())
            ego_guid = self._unpack_string()
            minSessionStartTime, minNumPlayers, lmp = self._unpack_from_format('<III')
            multiplayer = self._unpack_from_format('<%dI' % lmp)
            res = {'limit':limit, 'tracks':tracks, 'sessionTypes':sessionTypes,
                   'ego_guid':ego_guid, 'minSessionStartTime':minSessionStartTime,
                   'minNumPlayers':minNumPlayers, 'multiplayer':multiplayer}
        elif req == self.ANS_GET_SESSION_STATS:
            sessions = []
            n, = self._unpack_from_format('<I')
            for i in range(n):
                r = {'id':None,'type':None,'podium':[None,None,None],'posSelf':None,'numPlayers':None,'timeStamp':None,'multiplayer':None,'counter':None}
                idIsNone,typeIsNone,podium0IsNone,podium1IsNone,podium2IsNone,posSelfIsNone,numPlayersIsNone,timeStampIsNone,mpIsNone,cntIsNone = (
                    self._unpack_from_format('<bbbbbbbbbb'))
                if not idIsNone:            r['id'], =          self._unpack_from_format('<I')
                if not typeIsNone:          r['type'] =         self._unpack_string()
                if not podium0IsNone:       r['podium'][0] =    self._unpack_string()
                if not podium1IsNone:       r['podium'][1] =    self._unpack_string()
                if not podium2IsNone:       r['podium'][2] =    self._unpack_string()
                if not posSelfIsNone:       r['posSelf'], =     self._unpack_from_format('<H')
                if not numPlayersIsNone:    r['numPlayers'], =  self._unpack_from_format('<H')
                if not timeStampIsNone:     r['timeStamp'], =   self._unpack_from_format('<I')
                if not mpIsNone:            r['multiplayer'], = self._unpack_from_format('<b')
                if not cntIsNone:           r['counter'], =     self._unpack_from_format('<I')
                sessions.append(r)
            res = {'sessions':sessions}
        elif req in [self.REQ_GET_LAP_DETAILS, self.REQ_GET_LAP_DETAILS_WITH_HI]:
            lapid, = self._unpack_from_format('<I')
            res = {'lapid':lapid}
        elif req in [self.ANS_GET_LAP_DETAILS, self.ANS_GET_LAP_DETAILS_WITH_HI]:
            pickleStr = self._unpack_bytes()
            ld = pickle.loads(pickleStr)
            res = ld
        elif req == self.REQ_SERVER_DATA_CHANGED:
            res = {}
        elif req == self.REQ_GET_SERVER_DATA:
            res = {'guid':self._unpack_string()}
        elif req == self.ANS_GET_SERVER_DATA:
            ptracker_instances = []
            n, = self._unpack_from_format('<I')
            for i in range(n):
                pi = {}
                pi['guid'] = self._unpack_string()
                pi['name'] = self._unpack_string()
                pi['ptracker_conn'], = self._unpack_from_format('<I')
                hasSetup, = self._unpack_from_format('<b')
                if hasSetup:
                    pi['setup_car'] = self._unpack_string()
                    pi['setup'] = zlib.decompress(self._unpack_bytes())
                if self.prot_version >= 4:
                    pi.update(self._unpack_dict([("best_time","i"),("lap_count","i"),("last_time","i")]))
                ptracker_instances.append(pi)
            res = {'ptracker_instances':ptracker_instances}
            if self.prot_version >= 4:
                res['session_state'] = self._unpack_dict(
                    [("penaltiesEnabled", "i"), ("allowedTyresOut", "i"), ("tyreWearFactor", "f"), ("fuelRate", "f"), ("damage", "f")])
            if self.prot_version >= 5:
                msgs = []
                numMsg, = self._unpack_from_format('<I')
                for i in range(numMsg):
                    m = {}
                    m['text'] = self._unpack_string()
                    m['color'] = self._unpack_from_format('<ffff')
                    if self.prot_version >= 6:
                        m['type'], = self._unpack_from_format('<i')
                    else:
                        m['type'] = messageColorToType(m['color'])
                    msgs.append(m)
                res['messages'] = msgs
        elif req == self.REQ_SEND_SETUP:
            res = {}
            res['target_guid'] = self._unpack_string()
            res['setup_car'] = self._unpack_string()
            res['setup'] = zlib.decompress(self._unpack_bytes())
        elif req == self.ANS_SEND_SETUP:
            res = {}
            res['ok'], = self._unpack_from_format('<b')
        elif req == self.REQ_DEPOSIT_GET:
            res = self._unpack_dict([("car", self._unpack_string), ("track", self._unpack_string), ("setupid", "i")])
        elif req == self.ANS_DEPOSIT_GET:
            setups = []
            nsetups, = self._unpack_from_format('<i')
            for i in range(nsetups):
                setups.append(self._unpack_dict([("setupid", "i"),
                                                 ("name", self._unpack_string),
                                                 ("sender", self._unpack_string),
                                                 ("group", self._unpack_string),
                                                 ("owner", "i")]))
            selset = self._unpack_dict([("id", "i"), ("set", self._unpack_bytes)])
            if not selset['set'] is None:
                selset['set'] = zlib.decompress(selset['set'])
            memberOfGroup = []
            ngroups, = self._unpack_from_format('<i')
            for g in range(ngroups):
                memberOfGroup.append(self._unpack_dict([("group_id", "i"), ("group_name", self._unpack_string)]))
            res = {'setups':setups, 'selectedSet':selset, 'memberOfGroup':memberOfGroup}
        elif req == self.REQ_DEPOSIT_SAVE:
            res = self._unpack_dict([("car", self._unpack_string),
                                     ("track", self._unpack_string),
                                     ("name", self._unpack_string),
                                     ("groupid", "i"),
                                     ("setup", self._unpack_bytes)])
            res['setup'] = zlib.decompress(res['setup'])
        elif req == self.ANS_DEPOSIT_SAVE:
            res = self._unpack_dict([("ok", "i")])
        elif req == self.REQ_DEPOSIT_REMOVE:
            res = self._unpack_dict([("setupid", "i")])
        elif req == self.ANS_DEPOSIT_REMOVE:
            res = self._unpack_dict([("ok", "i")])
        elif req == self.REQ_SERVER_DATA_CHANGED_WITH_PAYLOAD:
            # - num_guids: byte
            #   for_each guid:
            #   - guid: byte[8]
            #   - features: byte (1: name | 2: ptconn | 4: setup | 8: best_time | 16:  last_time | 32: lap_count | 64: team | 128: tyre | 256: connected | 512: currLapInvalidated
            #                     1024: mr rating | 2048: carid
            #   [ - name: string ]
            #   [ - ptconn: byte ]
            #   [ - setup: - car: string, - file: bytes]
            #   [ - best_time: int ]
            #   [ - last_time: int ]
            #   [ - lap_count: int16 ]
            #   [ - team: string ]
            #   [ - tyre: string ]
            #   [ - connected: int8]
            #   [ - currLapInvalidated: int8]
            #   [ - mr rating: string ]
            #   [ - carid: int8 ]
            # - session_state_features: byte (1: penaltiesEnabled | 2: allowedTyresOut | 4: tyreWearFactor | 8: fuelRate | 16: damage)
            # [- penaltiesEnabled: byte]
            # [- allowedTyresOut: byte]
            # [- tyreWearFactor: float]
            # [- fuelRate: float]
            # [- damage: float]
            # - number_of_messages: byte
            #   for each message:
            #   - message_text: string
            #   - type: int16
            #   - message_color: (byte, byte, byte, byte)
            pti = []
            session_state = {}
            messages = []
            n_guids, = self._unpack_from_format('<b')
            for i in range(n_guids):
                if self.prot_version >= 11:
                    guid, features =  self._unpack_from_format('<QH')
                else:
                    guid, features =  self._unpack_from_format('<QB')
                guid = str(guid)
                r = {'guid':guid}
                if features & 1 : r['name'] = self._unpack_string()
                if features & 2 : r['ptracker_conn'], = self._unpack_from_format('<b')
                if features & 4 : r['setup_car'] = self._unpack_string()
                if features & 4 : r['setup'] = zlib.decompress(self._unpack_bytes())
                if features & 8 : r['best_time'], = self._unpack_from_format('<i')
                if features & 8 and r['best_time'] == -4242: r['best_time'] = None
                if features & 16: r['last_time'], = self._unpack_from_format('<i')
                if features & 16 and r['last_time'] == -4242: r['last_time'] = None
                if features & 32: r['lap_count'], = self._unpack_from_format('<h')
                if features & 32 and r['lap_count'] == -4242: r['lap_count'] = None
                if features & 64: r['team'] = self._unpack_string()
                if features & 128: r['tyre'] = self._unpack_string()
                if self.prot_version >= 11 and features & 256: r['connected'], = self._unpack_from_format('<b')
                if self.prot_version >= 11 and features & 512: r['currLapInvalidated'], = self._unpack_from_format('<b')
                if self.prot_version >= 15 and features & 1024: r['mr_rating'] = self._unpack_string()
                if self.prot_version >= 16 and features & 2048: r['carid'], = self._unpack_from_format('<b')
                pti.append(r)
            features, = self._unpack_from_format('<b')
            if features & 1 : session_state['penaltiesEnabled'], = self._unpack_from_format('<b')
            if features & 2 : session_state['allowedTyresOut'], = self._unpack_from_format('<b')
            if features & 4 : session_state['tyreWearFactor'], = self._unpack_from_format('<f')
            if features & 8 : session_state['fuelRate'], = self._unpack_from_format('<f')
            if features & 16: session_state['damage'], = self._unpack_from_format('<f')
            if features & 32: session_state['ptrackerTyresOut'], = self._unpack_from_format('<b')
            if self.prot_version >= 11:
                adminav, = self._unpack_from_format('<b')
                if adminav:
                    session_state['adminpwd'] = self._unpack_string()
            n_messages, = self._unpack_from_format('<b')
            for i in range(n_messages):
                m = {}
                m['text'] = self._unpack_string()
                m['type'], = self._unpack_from_format('<h')
                c = self._unpack_from_format('BBBB')
                m['color'] = [c[k]/255. for k in range(4)]
                messages.append(m)
            res = self.set_sd_payload(delta_pti=pti, delta_session_state=session_state, messages=messages)
        elif req == self.REQ_ENABLE_SEND_COMPRESSION:
            self.socket.enableRcvCompression()
        elif req in [self.REQ_GET_PTS_RESPONSE, self.REQ_POST_PTS_REQUEST]:
            res = {'url': self._unpack_string()}
            acdebug("got url: %s", res['url'])
        elif req in [self.ANS_GET_PTS_RESPONSE, self.REQ_POST_PTS_REPLY]:
            ctype = self._unpack_string()
            content = self._unpack_bytes()
            cacheable, = self._unpack_from_format('<B')
            if req == self.REQ_POST_PTS_REPLY:
                ansId, = self._unpack_from_format('<I')
                res = (content, ctype, cacheable, ansId)
            else:
                res = (content, ctype, cacheable)
        elif req == self.ANS_POST_PTS_REQUEST:
            ansId, = self._unpack_from_format('<I')
            res = ansId
        else:
            raise ProtocolError('Unknown request ID %d' % req)
        self.socket.recvDone(req)
        if req == self.ANS_PROTO_START and self.prot_version == 8:
            # doesn't seem to work robustly
            self.socket.enableCompression()
        if self.prot_version >= 9 and not self.socket.sendCompressionEnabled():
            self.req_enable_send_compression()
        return req, res

    def _unpack_string(self):
        return self._unpack_bytes().decode('utf-8')

    def _unpack_short_string(self):
        return self._unpack_short_bytes().decode('utf-8')

    def _unpack_bytes(self):
        mts = self.maxTransmitSize_pre12 if self.prot_version < 12 else self.maxTransmitSize_post12
        if self.prot_version < 12:
            size, = self._unpack_from_format('<H')
            if size > mts:
                raise ProtocolError('size to unpack seems too large: %d bytes' % size)
        else:
            size, = self._unpack_from_format('<I')
            if size > mts:
                raise ProtocolError('size to unpack seems too large: %d bytes' % size)
        return self._unpack_from_format('%ds' % size)[0]

    def _unpack_short_bytes(self):
        mts = self.maxTransmitSize_pre12
        size, = self._unpack_from_format('<H')
        if size > mts:
            raise ProtocolError('size to unpack seems too large: %d bytes' % size)
        return self._unpack_from_format('%ds' % size)[0]

    def _unpack_dict(self, keys):
        res = {}
        for k,pid in keys:
            if type(pid) == type(""):
                h,v = self._unpack_from_format("<b"+pid)
            elif pid == self._unpack_string:
                h, = self._unpack_from_format("<b")
                v = self._unpack_string()
            elif pid == self._unpack_bytes:
                h, = self._unpack_from_format("<b")
                v = self._unpack_bytes()
            else:
                myassert(False)
            if not h: v = None
            res[k] = v
        return res

    def _unpack_from_format(self, fmt):
        size = struct.calcsize(fmt)
        buf = b""
        while len(buf) < size:
            r = self.socket.recv(size-len(buf))
            if len(r) == 0:
                acdebug("Socket recv received 0 bytes. Something's wrong?")
                acdebug("\n".join(traceback.format_stack()))
                myassert(0)
            buf += r
        return struct.unpack(fmt, buf)

sres = []

if __name__ == "__main__":
    import socketserver, socket, threading, time
    class TCPServerHandler(socketserver.BaseRequestHandler):
        def handle(self):
            p = ProtocolHandler(self.request)
            while 1:
                sres.append(p.unpack_item())

    HOST,PORT = "localhost", 64242
    server = socketserver.TCPServer((HOST,PORT), TCPServerHandler)
    server_thread = threading.Thread(target=server.serve_forever)
    server_thread.daemon = True
    server_thread.start()

    sock = socket.socket()
    sock.connect((HOST,PORT))
    p = ProtocolHandler(sock)

    kws = []
    reqs = []

    kws.append(dict(trackname='trackname', guid='guid', car='car', ac_version='acv', pt_version='ptv', track_checksum='tcs', car_checksum='ccs'))
    reqs.append(ProtocolHandler.REQ_SIGNIN)
    p.req_signin(**kws[-1])

    kws.append(dict(ok=1))
    reqs.append(ProtocolHandler.ANS_SIGNIN)
    p.ans_signin(**kws[-1])

    kws.append(dict(lapTime=11, sectorTimes=list(range(10)), sectorsAreSoftSplits=0, tyre='tyre', valid=1, lapHistoryCompressed=b"1234567890ab",
                    staticAssists=dict(ABS=0,autoBlib=1,autoBrake=2,autoClutch=3,
                                         autoShifter=4,idealLine=5,input_method="wheel",
                                         shifter=7,stabilityControl=1.5,
                                         tractionControl=10,visualDamage=11,slipStream=13,tyreBlankets=14),
                    dynamicAssists=dict(ABS=2.5,tractionControl=2.25,ambientTemp=26,trackTemp=12),
                    maxSpeed = 1.0
                    ))
    reqs.append(ProtocolHandler.REQ_SEND_LAP_INFO)
    p.req_send_lap_info(**kws[-1])

    kws.append(dict(ok=1))
    reqs.append(ProtocolHandler.ANS_SEND_LAP_INFO)
    p.ans_send_lap_info(**kws[-1])

    kws.append(dict(driver='driver'))
    reqs.append(ProtocolHandler.REQ_GET_GUID)
    p.req_get_guid(**kws[-1])

    kws.append(dict(guid='guid'))
    reqs.append(ProtocolHandler.ANS_GET_GUID)
    p.ans_get_guid(**kws[-1])

    kws.append(dict(limit=[None,1], tracks=None, sessionTypes=None, ego_guid="egoguid", minSessionStartTime=0, minNumPlayers=1, multiplayer=(0,)))
    reqs.append(ProtocolHandler.REQ_GET_SESSION_STATS)
    p.req_session_stats(**kws[-1])

    kws.append(dict(limit=[0,1], tracks=["t1","t2"], sessionTypes=["s1","s2","s4"], ego_guid="egoguid", minSessionStartTime=1235,
                    minNumPlayers=123, multiplayer=(0,1)))
    reqs.append(ProtocolHandler.REQ_GET_SESSION_STATS)
    p.req_session_stats(**kws[-1])

    kws.append(dict(sessions=[
        {'id':None,'type':None,'podium':[None,None,None],'posSelf':None,'numPlayers':None,'timeStamp':None,'multiplayer':None,'counter':None},
        {'id':1234,'type':'Race','podium':['nam1','nam2','nam4'],'posSelf':4,'numPlayers':8,'timeStamp':13456,'multiplayer':1,'counter':123},
    ]))
    reqs.append(ProtocolHandler.ANS_GET_SESSION_STATS)
    p.ans_session_stats(**kws[-1])

    kws.append({})
    reqs.append(ProtocolHandler.REQ_SERVER_DATA_CHANGED)
    p.req_server_data_changed()

    kws.append({'guid':'myguid'})
    reqs.append(ProtocolHandler.REQ_GET_SERVER_DATA)
    p.req_get_server_data(**kws[-1])

    kws.append({'lap_details':'test'})
    reqs.append(ProtocolHandler.ANS_GET_LAP_DETAILS)
    p.ans_lap_details(**kws[-1])

    kws.append(dict(
        ptracker_instances=[
            {'guid':'ptrackerGUID1','name':'the name','ptracker_conn':1,'lap_count':None,'last_time':1, 'best_time':2,'setup':b"a"*10,'setup_car':'mycar'},
            {'guid':'ptrackerGUID2','name':'other name','ptracker_conn':0,'lap_count':1,'last_time':None, 'best_time':None}],
        session_state={'penaltiesEnabled':None, 'allowedTyresOut':None, 'tyreWearFactor':2.5, 'fuelRate':1, 'damage':100},
        messages=[{'text':"Hello World", 'color':(1.0,1.0,1.0,1.0)}],
    ))
    reqs.append(ProtocolHandler.ANS_GET_SERVER_DATA)
    p.ans_get_server_data(**kws[-1])

    kws.append(dict(target_guid='ptrackerGUID', setup=b"a"*10, setup_car='mycar'))
    reqs.append(ProtocolHandler.REQ_SEND_SETUP)
    p.req_send_setup(**kws[-1])

    kws.append(dict(ok=1))
    reqs.append(ProtocolHandler.ANS_SEND_SETUP)
    p.ans_send_setup(**kws[-1])


    sock.close()
    time.sleep(1)
    myassert (len(sres) == len(kws))
    for i,kw in enumerate(kws):
        print("Test %d/%d" % (i+1, len(kws)))
        myassert(kw == sres[i][1] and sres[i][0] == reqs[i])
    print ("all tests passed")
