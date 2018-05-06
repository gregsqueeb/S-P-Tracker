# -*- coding: iso-8859-15 -*-

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
import socket
import time
import traceback
from queue import Queue
from urllib.parse import urlparse

import ptracker_lib
from threading import Thread,RLock
from ptracker_lib import dbgeneric
from ptracker_lib.ps_protocol import ProtocolHandler
from ptracker_lib.helpers import *
from ptracker_lib.config import config

def reconnectOnError(f):

    def new_f(self, *args):
        try:
            return f(self, *args)
        except:
            acwarning("connection error caught:")
            acwarning(traceback.format_exc())
            if self.reconnect():
                return f(self, *args)
            else:
                myassert(0)

    return new_f


class PtrackerClient:

    def __init__(self, server_address, server_port, guid):
        server_overrides = config.GLOBAL.override_stracker_server.split(",")
        for so in server_overrides:
            acdebug("found override %s", so)
            so = so.split(":")
            acdebug("splitted in %s", so)
            if len(so) == 2 and so[0] == server_address:
                server_address = so[1]
                acinfo("override server %s with %s", so[0], so[1])
                break
        self.connection_retry_timestamps = []
        self.server_address = server_address
        self.server_port = server_port
        self.guid = guidhasher(guid)
        self.pendingServerData = False
        self.lock = RLock()
        self.server_data = Queue()
        self.lastKnownGoodPort = None
        self.reconnectInProgress = False
        self.lastSigninArgs = ('', self.guid, '', '', ptracker_lib.version, '', '')
        self.port = None
        self.proto = None
        self.thread = None
        self.ptsReplies = Queue()
        self.mapAnsIdsToUrls = {}
        self.url_cache = {}
        self.connectionInProgress = False
        self.initialConnectThread = Thread(target=self.connect, daemon=True)
        self.initialConnectThread.start()

    def connect_to_port(self, p):
        acinfo("trying port %s %d" % (self.server_address,p))
        self.sock = socket.socket()
        self.sock.settimeout(2.)
        self.sock.connect((self.server_address,p))
        self.proto = ProtocolHandler(self.sock, clientMode = True)
        self.proto.req_proto_start(port=self.server_port)
        ans = self.proto.unpack_item()
        if ans[0] == self.proto.REQ_ENABLE_SEND_COMPRESSION:
            ans = self.proto.unpack_item()
        myassert(ans[0] == self.proto.ANS_PROTO_START and ans[1]['trackerid'] == 'stracker server')
        self.signin(*self.lastSigninArgs)
        self.port = p
        self.lastKnownGoodPort = p
        acinfo("Connected to %s:%d" % (self.server_address,p))
        self.sock.settimeout(20.)
        self.url_cache = {}

    def connect(self):
        if self.isOnline():
            return "Already connected."
        if self.connectionInProgress:
            return "Connection already in progress."
        with self.lock:
            self.connectionInProgress = True
            try:
                self.port = None
                for p in [50042, 50043, 54242, 54243, 60023, 60024, 62323, 62324, 42423, 42424, 23232, 23233, self.server_port+42]:
                    try:
                        self.connect_to_port(p)
                        break
                    except socket.timeout:
                        acinfo("socket timeout")
                        if self.proto: self.proto.shutdown()
                        self.proto = None
                    except socket.error as e:
                        acinfo("socket error" + str(e))
                        if self.proto: self.proto.shutdown()
                        self.proto = None
                    except AssertionError:
                        acinfo("assert error")
                        if self.proto: self.proto.shutdown()
                        self.proto = None
                    except:
                        acwarning("unknown error:")
                        acwarning(traceback.format_exc())
                        if self.proto: self.proto.shutdown()
                        self.proto = None
                if self.port is None:
                    acinfo("No stracker connection for server %s:%d. Use standalone mode.", self.server_address, self.server_port)
                    self.thread = None
                else:
                    self._finished = False
                    self.thread = Thread(target=self.checkForServerData)
                    self.thread.setDaemon(True)
                    self.thread.start()
            finally:
                self.connectionInProgress = False
        if self.port is None:
            return "Connection failed."
        else:
            return "Connected."

    def reconnect(self):
        with self.lock:
            self.port = None
            if self.lastKnownGoodPort is None or self.reconnectInProgress or self._finished:
                return False
            try:
                self.reconnectInProgress = True
                t = time.time()
                t_m_30 = t-30
                if len(list(filter(lambda x: x > t_m_30, self.connection_retry_timestamps))) > 3:
                    # more than 3 reconnections in 30 seconds, better stop...
                    acwarning("More than 3 reconnections failed in 30 seconds. Giving up.")
                    return False
                self.connection_retry_timestamps.append(t)
                try:
                    self.sock.close()
                except:
                    pass
                try:
                    self.connect_to_port(self.lastKnownGoodPort)
                    return True
                except socket.timeout:
                    acinfo("socket timeout")
                    if self.proto: self.proto.shutdown()
                    self.proto = None
                except socket.error as e:
                    acinfo("socket error" + str(e))
                    if self.proto: self.proto.shutdown()
                    self.proto = None
                except AssertionError:
                    acinfo("assert error")
                    if self.proto: self.proto.shutdown()
                    self.proto = None
            finally:
                self.reconnectInProgress = False

    def shutdown(self):
        if not self.thread is None:
            self._finished = True
            self.thread.join()
            self.thread = None
        if self.proto: self.proto.shutdown()
        self.url_cache = {}
        acinfo("Client shut down ok")

    @reconnectOnError
    def checkForServerData(self):
        #sys.settrace(tracer)
        try:
            while not self._finished:
                with self.lock:
                    rlist, wlist, xlist = select.select([self.sock],[],[],0)
                    sd = None
                    if len(rlist) > 0:
                        ans, tmp = self.proto.unpack_item()
                        if ans == self.proto.REQ_SERVER_DATA_CHANGED:
                            self.pendingServerData = True
                        elif ans == self.proto.REQ_SERVER_DATA_CHANGED_WITH_PAYLOAD:
                            sd = tmp
                        elif ans == self.proto.REQ_POST_PTS_REPLY:
                            self.memoizePtsAnswer(tmp)
                    if self.pendingServerData:
                        self.pendingServerData = False
                        sd = self.get_server_data()
                if not sd is None:
                    self.server_data.put(sd)
                time.sleep(1)
        except:
            acerror("exception while checking for server data!")
            acerror(traceback.format_exc())
        with self.lock:
            self.port = None
            self.thread = None
        if not self._finished:
            raise RuntimeError("Reconnection needed")
        acinfo("Finishing checkForServerData thread")

    def getAnswer(self, expected_proto_ID):
        while 1:
            ans = self.proto.unpack_item()
            if ans[0] == expected_proto_ID:
                return ans[1]
            elif ans[0] == self.proto.REQ_SERVER_DATA_CHANGED:
                acdebug("pending server data is available")
                self.pendingServerData = True
            elif ans[0] == self.proto.REQ_SERVER_DATA_CHANGED_WITH_PAYLOAD:
                acdebug("server data with payload available")
                self.server_data.put(ans[1])
            elif ans[0] == self.proto.REQ_ENABLE_SEND_COMPRESSION:
                pass
            elif ans[0] == self.proto.REQ_POST_PTS_REPLY:
                self.memoizePtsAnswer(ans[1])
            else:
                acdebug("Unexpected protocol answer %d", ans[0])
                myassert(False)

    @reconnectOnError
    def signin(self, *args, **kw):
        self.lastSigninArgs = args
        with self.lock:
            self.proto.req_signin(*args, **kw)
            ans = self.getAnswer(self.proto.ANS_SIGNIN)
            myassert(ans)
            return ans

    @reconnectOnError
    def send_lap_info(self, *args, **kw):
        with self.lock:
            self.proto.req_send_lap_info(*args, **kw)
            if self.proto.prot_version < 8:
                return self.getAnswer(self.proto.ANS_SEND_LAP_INFO)
            return {'ok':1}

    @reconnectOnError
    def lap_stats(self, *args, **kw):
        with self.lock:
            self.proto.req_lap_stats(*args, **kw)
            return self.getAnswer(self.proto.ANS_GET_LAP_STATS)

    @reconnectOnError
    def session_stats(self, *args, **kw):
        with self.lock:
            self.proto.req_session_stats(*args, **kw)
            return self.getAnswer(self.proto.ANS_GET_SESSION_STATS)

    @reconnectOnError
    def lap_details(self, *args, **kw):
        with self.lock:
            self.proto.req_lap_details(*args, **kw)
            return self.getAnswer(self.proto.ANS_GET_LAP_DETAILS)

    @reconnectOnError
    def lap_details_with_history(self, *args, **kw):
        with self.lock:
            self.proto.req_lap_details_with_hi(*args, **kw)
            return self.getAnswer(self.proto.ANS_GET_LAP_DETAILS_WITH_HI)

    @reconnectOnError
    def get_server_data(self, *args, **kw):
        with self.lock:
            self.proto.req_get_server_data(guid=self.guid)
            return self.getAnswer(self.proto.ANS_GET_SERVER_DATA)

    @reconnectOnError
    def send_setup(self, *args, **kw):
        with self.lock:
            self.proto.req_send_setup(*args, **kw)
            if self.proto.prot_version < 8:
                return self.getAnswer(self.proto.ANS_SEND_SETUP)
            return {'ok':1}

    def isOnline(self):
        return not self.port is None

    def isConnecting(self):
        return self.connectionInProgress

    @reconnectOnError
    def capabilities(self):
        if not self.isOnline():
            return 0
        return self.proto.getCapabilities()

    @reconnectOnError
    def setup_deposit_get(self, *args, **kw):
        with self.lock:
            self.proto.req_deposit_get(*args, **kw)
            return self.getAnswer(self.proto.ANS_DEPOSIT_GET)

    @reconnectOnError
    def setup_deposit_save(self, *args, **kw):
        with self.lock:
            self.proto.req_deposit_save(*args, **kw)
            return self.getAnswer(self.proto.ANS_DEPOSIT_SAVE)

    @reconnectOnError
    def setup_deposit_remove(self, *args, **kw):
        with self.lock:
            self.proto.req_deposit_remove(*args, **kw)
            return self.getAnswer(self.proto.ANS_DEPOSIT_REMOVE)

    @reconnectOnError
    def getPtsResponse(self, url):
        with self.lock:
            if url in self.url_cache:
                res = self.url_cache[url]
                tmp = (res[0], res[1], res[2], time.time())
                self.memoizePtsAnswer(tmp, url)
                res = res[3]
                acinfo("PtsRequest[cache(%d/%d)]: %s", len(self.url_cache), len(self.mapAnsIdsToUrls), url)
            try:
                self.proto.req_post_pts_request(url = url)
                res = self.getAnswer(self.proto.ANS_POST_PTS_REQUEST)
                self.mapAnsIdsToUrls[res] = url
                acinfo("PtsRequest[protv=13]: %s", url)
            except NotImplementedError:
                self.proto.req_get_pts_response(url = url)
                res = self.getAnswer(self.proto.ANS_GET_PTS_RESPONSE)
                acinfo("PtsRequest[protv=12]: %s", url)
                tmp = (res[0], res[1], res[2], time.time())
                self.memoizePtsAnswer(tmp, url)
                res = tmp[3]
            return res

    def memoizePtsAnswer(self, ptsReply, url = None):
        if url is None:
            url = self.mapAnsIdsToUrls.get(ptsReply[3], None)
            if url is None:
                acwarning("Cannot find ptsReply ID in mapAnsIdsToUrls.")
            else:
                del self.mapAnsIdsToUrls[ptsReply[3]]
        if ptsReply[2] and not url is None:
            self.url_cache[url] = ptsReply
        self.ptsReplies.put(ptsReply)

class RemoteBackend:

    def __init__(self, lapHistoryFactory, ptrackerClient):
        self.lapHistoryFactory = lapHistoryFactory
        self.registered = False
        self.trackname = None
        self.client = ptrackerClient

    def getBestLap(self, **kw):
        pass # not yet implemented

    def getBestSectorTimes(self, **kw):
        pass # not yet implemented

    def newSession(self, trackname, **kw):
        self.trackname = trackname

    def finishSession(self, **kw):
        pass # not yet implemented, is there st. to do?

    def registerLap(self, trackChecksum, carChecksum, acVersion,
                    steamGuid, playerName, playerIsAI,
                    lapHistory, tyre, lapCount, sessionTime, fuelRatio, valid, carname, staticAssists, dynamicAssists,
                    maxSpeed, timeInPitLane, timeInPit, escKeyPressed, teamName,
                    gripLevel, collisionsCar, collisionsEnv, cuts, ballast):
        steamGuid = guidhasher(steamGuid)
        acdebug("remotedb::registerLap %s", steamGuid)
        if steamGuid is None:
            return
        if self.client is None or not self.client.isOnline():
            return
        if self.client.guid != steamGuid:
            # only register laps by the client owner
            return
        if not self.registered:
            acdebug("signin")
            ans = self.client.signin(self.trackname, steamGuid, carname,
                                     acVersion, ptracker_lib.version,
                                     trackChecksum, carChecksum)
            myassert(ans['ok'] == 1)
            self.registered = 1
        acdebug("send_lap_info")
        lhCompressed = dbgeneric.compress(lapHistory.sampleTimes, lapHistory.worldPositions, lapHistory.velocities, lapHistory.normSplinePositions, minDt=1.)
        ans = self.client.send_lap_info(lapHistory.lapTime, lapHistory.sectorTimes, lapHistory.sectorsAreSoftSplits,
                                        tyre, valid, lhCompressed, staticAssists, dynamicAssists, maxSpeed,
                                        timeInPitLane, timeInPit, escKeyPressed, ballast, fuelRatio)
        myassert(ans['ok'] == 1)

    def lapStats(self, mode, limit, track, artint, cars, ego_guid, valid, minSessionStartTime):
        ego_guid = guidhasher(ego_guid)
        if self.client is None or not self.client.isOnline():
            return
        return self.client.lap_stats(mode, limit, track, artint, cars, ego_guid, valid, minSessionStartTime)

    def sessionStats(self, limit, tracks, sessionTypes, ego_guid, minSessionStartTime, minNumPlayers, multiplayer):
        ego_guid = guidhasher(ego_guid)
        if self.client is None or not self.client.isOnline():
            return
        try:
            ans = self.client.session_stats(limit, tracks, sessionTypes, ego_guid, minSessionStartTime, minNumPlayers, multiplayer)
            return ans
        except NotImplementedError:
            return None

    def lapDetails(self, lapid, withHistoryInfo=False):
        if self.client is None or not self.client.isOnline():
            return
        try:
            if not withHistoryInfo:
                return self.client.lap_details(lapid)
            else:
                acinfo("querying lap details with history.")
                return self.client.lap_details_with_history(lapid)
        except NotImplementedError:
            return None

    def setupDepositGet(self, guid, car, track, setupid = None):
        if self.client is None or not self.client.isOnline():
            return
        try:
            return self.client.setup_deposit_get(car, track, setupid)
        except NotImplementedError:
            return None

    def setupDepositSave(self, guid, car, track, name, groupid, setup):
        if self.client is None or not self.client.isOnline():
            return
        try:
            return self.client.setup_deposit_save(car, track, name, groupid, setup)
        except NotImplementedError:
            return None

    def setupDepositRemove(self, guid, setupid):
        if self.client is None or not self.client.isOnline():
            return
        try:
            return self.client.setup_deposit_remove(setupid)
        except NotImplementedError:
            return None

    def getPtsResponse(self, url):
        if self.client is None or not self.client.isOnline():
            return ("Server is offline", "error/offline")
        if self.client.capabilities() & ProtocolHandler.CAP_PTS_PROTOCOL:
            return self.client.getPtsResponse(url)
        else:
            return ("Server is too old", "error/not-implemented")

    def reconnect(self):
        return self.client.connect()