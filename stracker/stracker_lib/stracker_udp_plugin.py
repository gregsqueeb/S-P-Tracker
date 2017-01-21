
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

import time
import math
import sys
import queue
import functools
import copy
import traceback
from collections import namedtuple

from acplugins4python.ac_server_plugin import  ACServerPlugin
from acplugins4python.ac_server_protocol import *

from stracker_lib import config
from ptracker_lib.helpers import *

NEW_LAP_TIMEOUT = 10.

class UdpAndACMonitorThreadSynchronizer:
    def __init__(self):
        self.callbacksFromUdp = queue.Queue()
        self.requestsToUdp = queue.Queue()

    def udpCallback(self, cb):
        return functools.partial(lambda *args, **kw: self.callbacksFromUdp.put((cb, copy.deepcopy(args), copy.deepcopy(kw))))

    def udpRequest(self, req):
        return functools.partial(lambda *args, **kw: self.requestsToUdp.put((req, copy.deepcopy(args), copy.deepcopy(kw))))

    def processUdpCallbacks(self, timeout = None):
        t0 = time.time()
        try:
            while 1:
                elapsed = time.time() - t0
                if (not timeout is None) and (elapsed < timeout):
                    ctimeout = timeout - elapsed
                else:
                    ctimeout = None
                cb, args, kw = self.callbacksFromUdp.get(block=not ctimeout is None, timeout=ctimeout)
                cb(*args, **kw)

        except queue.Empty:
            pass

    def processUdpRequests(self):
        try:
            while 1:
                req, args, kw = self.requestsToUdp.get_nowait()
                req(*args,**kw)
        except queue.Empty:
            pass

synchronizer = UdpAndACMonitorThreadSynchronizer()

class LapHistoryEntry:
    __slots__ = ('worldPos', 'velocity', 'gear', 'engineRPM', 'normalizedSplinePos', 'rcvTime')

    def __init__(self, **kw):
        for a in self.__slots__:
            setattr(self, a, kw.get(a, None))

class CarState:
    __slots__ = ('carId','isConnected','carModel','carSkin','driverName','driverTeam','driverGuid',
                 'lapTime', 'cuts', 'gripLevel',
                 'lapHistory', 'lapCount', 'sumLapTimes', 'lapTimeRcvTime',
                 'collCarCount', 'collEnvCount', 'maxSpeed', 'lastRealTimeRcvTime', 'lastHistoryEntry', 'inactiveSince', 'active',
                 'pitPosition', 'raceCompleted')

    def __init__(self, **kw):
        for a in self.__slots__:
            setattr(self, a, kw.get(a, None))
        if self.lapHistory is None:
            self.lapHistory = []
        if self.lapCount is None:
            self.lapCount = 0
        if self.sumLapTimes is None:
            self.sumLapTimes = 0
        if self.collCarCount is None:
            self.collCarCount = 0
        if self.collEnvCount is None:
            self.collEnvCount = 0
        if self.maxSpeed is None:
            self.maxSpeed = 0
        if self.lastRealTimeRcvTime is None:
            self.lastRealTimeRcvTime = time.time()
        if self.active is None:
            self.active = False
        if self.raceCompleted is None:
            self.raceCompleted = False

    def resetLap(self):
        self.lapHistory = []
        self.collCarCount = 0
        self.collEnvCount = 0
        self.maxSpeed = 0

class SessionState:
    __slots__ = [
        'version',
        'sessionIndex', # the index of the session this packet belongs to
        'currSessionIndex', # the index of the current session of the server
        'sessionCount',
        'serverName',
        'track',
        'track_config',
        'name',
        'sessionType',
        'sessionTime',
        'laps',
        'waittime',
        'ambientTemp',
        'roadTemp',
        'wheather',
        'elapsedMS',
        'sessionStateRcvTime',
        'raceFinishTimeStamp',
    ]
    def __init__(self, **kw):
        for a in self.__slots__:
            setattr(self, a, kw.get(a, None))
        self.sessionStateRcvTime = time.time()
        self.raceFinishTimeStamp = None

def _eventToNamedTuple(e, t):
    for f in t.__slots__:
        try:
            setattr(t, f, getattr(e, f))
        except AttributeError:
            pass
    return t

def printTuple(t):
    for f in t.__slots__:
        print(f, str(getattr(t, f, '<none>')))

class StrackerUDPPlugin:
    def __init__(self,
                 newSessionCallback, newConnectionCallback, connectionLostCallback, lapCompletedCallback,
                 carCollisionCallback, envCollisionCallback, welcomeCallback,
                 finishSessionCallback, serverRestartCallback, driverActiveCallback,
                 sessionInfoCallback, commandCallback, rtUpdateCallback, chatCallback):
        rcvPort = config.config.ACPLUGIN.rcvPort
        if rcvPort < 0:
            try:
                v = config.acconfig['SERVER']['UDP_PLUGIN_ADDRESS'].split(":")
                host = v[0]
                rcvPort = int(v[1])
            except:
                acerror("Cannot parse the UDP_PLUGIN_ADDRESS in your server_cfg.ini file. This is a fatal error!")
                acerror("In the [SERVER] section there must be a line UDP_PLUGIN_ADDRESS=127.0.0.1:<port>")
                acerror("with <port> being the first UDP port number used for the plugins.")
                raise RuntimeError("Cannot parse the value in UDP_PLUGIN_ADDRESS")
            if not host in ["127.0.0.1", "localhost",  "::1"]:
                acerror("Invalid host configured in UDP_PLUGIN_ADDRESS in your server_cfg.ini file.")
                acerror("The value must start with '127.0.0.1:'. This is a fatal error!")
                raise RuntimeError("UDP_PLUGIN_ADDRESS does not contain 127.0.0.1")
        sendPort = config.config.ACPLUGIN.sendPort
        if sendPort < 0:
            try:
                sendPort = int(config.acconfig['SERVER']['UDP_PLUGIN_LOCAL_PORT'])
            except:
                acerror("Cannot parse the UDP_PLUGIN_LOCAL_PORT in your server_cfg.ini file. This is a fatal error!")
                acerror("In the [SERVER] section there must be a line UDP_PLUGIN_LOCAL_PORT=<port>")
                acerror("with <port> being the second UDP port number used for the plugins.")
                raise RuntimeError("Cannot parse the value in UDP_PLUGIN_LOCAL_PORT")
        proxyPluginPort = config.config.ACPLUGIN.proxyPluginPort
        proxyPluginLocalPort = config.config.ACPLUGIN.proxyPluginLocalPort
        if proxyPluginPort < 0:
            proxyPluginPort = None
        if proxyPluginLocalPort < 0:
            proxyPluginLocalPort = None
        acinfo("Using plugin configuration rcvport=%d sendport=%d proxy=(%s/%s)", rcvPort, sendPort, proxyPluginPort, proxyPluginLocalPort)
        self.nspPositionsOfInterest = []
        self.threadExc = None
        self.inDownTime = False
        self.acPlugin = ACServerPlugin(rcvPort, sendPort, callbackDecorator(self.callback), proxyPluginPort, proxyPluginLocalPort, log_err_ = self.log_warning, log_info_ = acinfo, log_dbg_ = self.log_debug)
        self.rtReportMS = 200 # 5 Hz RT report
        self.acPlugin.enableRealtimeReport(self.rtReportMS)
        self.lastRealtimeEventTimestamp = time.time() - 5.
        self.currentSession = None
        self.cars = {}
        self.welcomePending = {}
        self.cbNewSession = synchronizer.udpCallback(newSessionCallback)
        self.cbNewConnection = synchronizer.udpCallback(newConnectionCallback)
        self.cbConnectionLost = synchronizer.udpCallback(connectionLostCallback)
        self.cbLapCompleted = synchronizer.udpCallback(lapCompletedCallback)
        self.cbCarCollision = synchronizer.udpCallback(carCollisionCallback)
        self.cbEnvCollision = synchronizer.udpCallback(envCollisionCallback)
        self.cbWelcome = synchronizer.udpCallback(welcomeCallback)
        self.cbFinishSession = synchronizer.udpCallback(finishSessionCallback)
        self.cbServerRestart = synchronizer.udpCallback(serverRestartCallback)
        self.cbDriverActive = synchronizer.udpCallback(driverActiveCallback)
        self.cbSessionInfo = synchronizer.udpCallback(sessionInfoCallback)
        self.cbCommand = synchronizer.udpCallback(commandCallback)
        self.cbRtUpdate = synchronizer.udpCallback(rtUpdateCallback)
        self.cbChat = synchronizer.udpCallback(chatCallback)
        self.eventReceived = False
        self.acPlugin.getSessionInfo()
        self.nspOffset = 0.0

    def log_warning(self, *args, **kw):
        if not self.inDownTime:
            acwarning(*args, **kw)

    def log_debug(self, *args, **kw):
        if not self.inDownTime:
            acdebug(*args, **kw)

    def getSessionInfo(self, *args, **kw):
        return self.acPlugin.getSessionInfo(*args, **kw)

    def setSessionInfo(self, *args, **kw):
        return self.acPlugin.setSessionInfo(*args, **kw)

    def nextSession(self, *args, **kw):
        return self.acPlugin.nextSession(*args, **kw)

    def setNspPositionsOfInterest(self, nspPositionsOfInterest):
        self.nspPositionsOfInterest = nspPositionsOfInterest

    def processServerPackets(self, *args, **kw):
        kw['timeout'] = 1. # 1 second pulse time
        noEventsSince = time.time()
        self.inDownTime = False
        while 1:
            try:
                self.eventReceived = False
                self.acPlugin.getSessionInfo()
                self.acPlugin.processServerPackets(*args, **kw)
                synchronizer.processUdpRequests()
                t = time.time()
                if not self.eventReceived:
                    if t - noEventsSince > 15.:
                        if not self.inDownTime:
                            self.inDownTime = True
                            self.cbFinishSession()
                            acwarning("Server seems to be down (no events received). Continue anyways.")
                else:
                    if self.inDownTime:
                        self.inDownTime = False
                        acinfo("Server seems to be up again.")
                    noEventsSince = t
                self.checkDanglingCars()
                self.sendDriverActive()
            except ProtocolVersionMismatch as e:
                if self.threadExc is None:
                    acerror("Server protocol unknown: %s", str(e))
                    self.threadExc = e
            except:
                acerror("Exception in udp_plugin::processServerPackets. This should not happen.")
                acerror(traceback.format_exc())

    def checkDanglingCars(self):
        # there has been issues with
        ct = time.time()
        for carId in self.cars:
            c = self.cars[carId]
            if ct - c.lastRealTimeRcvTime > 5.:
                acwarning("There seems to be a dangling car %d (name=%s guid=%s); trying to repair by pinging server state",
                          carId, getattr(c, "driverName", "?"), getattr(c, "driverGuid", "?"))
                self.acPlugin.getCarInfo(carId)

    def sendDriverActive(self):
        for carId in self.cars:
            self.cbDriverActive(carId, self.cars[carId].active)

    def empty(self):
        return time.time()-self.lastRealtimeEventTimestamp > 300.0

    def callback(self, event):
        #acdebug("UDP Event: %s", event)
        t = time.time()
        self.eventReceived = True
        if t - self.lastRealtimeEventTimestamp > 5. and len(self.cars) > 0:
            acdebug("Enabled realtime events")
            self.acPlugin.enableRealtimeReport(self.rtReportMS) # 3 Hz realtime report request
            self.lastRealtimeEventTimestamp = t
        if type(event) in [NewSession, SessionInfo]:
            if event.currSessionIndex == event.sessionIndex:
                if type(event) == NewSession or self.currentSession is None:
                    self.newSession(event)
                event.raceFinishTimeStamp = self.currentSession.raceFinishTimeStamp
            else:
                event.raceFinishTimeStamp = None
            self.cbSessionInfo(event)
        elif type(event) == CarInfo:
            self.carEvent(event)
        elif type(event) == CarUpdate:
            self.lastRealtimeEventTimestamp = t
            self.realtimeEvent(event)
        elif type(event) == NewConnection:
            self.carEvent(event)
        elif type(event) == ConnectionClosed:
            event.isConnected = False
            self.carEvent(event)
        elif type(event) == LapCompleted:
            self.carEvent(event)
        elif type(event) in [CollisionCar, CollisionEnv]:
            self.collisionEvent(event)
        elif type(event) == ClientLoaded:
            # request another car info packet for this car -> this should finally
            # add the car to the car dict
            self.acPlugin.getCarInfo(event.carId)
            self.welcomePending[event.carId] = True
        elif type(event) == ProtocolVersion:
            self.cbFinishSession()
            self.acPlugin.enableRealtimeReport(self.rtReportMS)
            self.cbServerRestart()
        elif type(event) == EndSession:
            self.cbFinishSession()
        elif type(event) == ChatEvent:
            if event.message.lower().startswith("/st") and event.carId in self.cars:
                cmd = event.message[len("/st"):].strip()
                self.cbCommand(self.cars[event.carId].driverGuid, cmd)
            elif event.message.lower().startswith("/help") and event.carId in self.cars:
                self.cbCommand(self.cars[event.carId].driverGuid, "")
            elif len(event.message) > 0 and event.message[0] != "/"  and event.carId in self.cars:
                self.cbChat(self.cars[event.carId].driverGuid, event.message)

    def newSession(self, event):
        self.currentSession = SessionState(**event.__dict__)
        for c in self.cars:
            self.cars[c].lapTime = None
            self.cars[c].cuts = None
            self.cars[c].gripLevel = None
            self.cars[c].lastHistoryEntry = None
            self.cars[c].lapCount = 0
            self.cars[c].sumLapTimes = 0
            self.cars[c].resetLap()
            self.cars[c].active = False
            self.cars[c].pitPosition = None
            self.cars[c].raceCompleted = False
        trackname = self.currentSession.track
        if not self.currentSession.track_config in [None, '']:
            trackname += "-" + self.currentSession.track_config
        if trackname == "ks_nordschleife-touristenfahrten":
            acinfo("Applying nordschleife-tourist hardcoded nsp offset")
            self.nspOffset = -0.953
        else:
            self.nspOffset = 0.0
        self.cbNewSession(self.currentSession)

    def carEvent(self, event):
        if 'isConnected' in event.__dict__:
            isConnected = event.isConnected
        else:
            try:
                cs = self.cars[event.carId]
                isConnected = cs.isConnected
            except AttributeError:
                self.acPlugin.getCarInfo(event.carId)
                isConnected = False
            except KeyError:
                self.acPlugin.getCarInfo(event.carId)
                isConnected = False
        if not isConnected:
            if event.carId in self.cars:
                self.cbConnectionLost(self.cars[event.carId])
                acdebug("removing carId=%d from cars", event.carId)
                del self.cars[event.carId]
            else:
                acdebug("ignoring event, because isConnected is false: %s", str(event))
            return
        newConnection = False
        if not event.carId in self.cars:
            if not 'driverGuid' in event.__dict__:
                # request the carinfo package before adding this car to the car state
                self.acPlugin.getCarInfo(event.carId)
                return
            acdebug("adding carId=%d to cars", event.carId)
            self.cars[event.carId] = CarState()
            newConnection = True
        _eventToNamedTuple(event, self.cars[event.carId])
        if newConnection:
            acdebug("UDP: new connection")
            self.cbNewConnection(self.cars[event.carId])
        if type(event) == LapCompleted:
            acdebug("UDP: lap completed")
            t = time.time()
            if self.currentSession is None or t - self.currentSession.sessionStateRcvTime < NEW_LAP_TIMEOUT:
                try:
                    driver = self.cars[event.carId].driverName
                except:
                    driver = "<unknown>"
                acinfo("Ignore UDP lap probably belonging to last session from driver %s",  driver)
            else:
                self.cars[event.carId].lapTimeRcvTime = t
                self.cars[event.carId].lapCount += 1
                # fix lap count in case of mid-race stracker start
                for lbe in event.leaderboard:
                    if lbe.carId == event.carId:
                        if lbe.laps > self.cars[event.carId].lapCount:
                            self.cars[event.carId].lapCount = lbe.laps
                        if lbe.completed:
                            self.cars[event.carId].raceCompleted = True
                        break
                self.cars[event.carId].sumLapTimes += event.lapTime

                if self.currentSession.sessionType == SESST_RACE:

                    if ((self.currentSession.laps > 0 and
                         self.cars[event.carId].lapCount == self.currentSession.laps) or
                        (self.currentSession.laps == 0 and
                         self.cars[event.carId].raceCompleted)):

                        if self.currentSession.raceFinishTimeStamp is None:
                            self.currentSession.raceFinishTimeStamp = self.cars[event.carId].lapTimeRcvTime
                            acdebug("recorded race finish timestamp")
                            self.cbSessionInfo(self.currentSession)
                            # notify about raceFinishTimeStamp...

                self.cbLapCompleted(self.cars[event.carId])
                self.cars[event.carId].resetLap()
        if self.welcomePending.get(event.carId, False) and not getattr(event, 'driverGuid', None) is None:
            del self.welcomePending[event.carId]
            self.cbWelcome(event.driverGuid)

    def realtimeEvent(self, event):
        if event.carId in self.cars:
            entry = _eventToNamedTuple(event, LapHistoryEntry())
            entry.normalizedSplinePos = (entry.normalizedSplinePos + self.nspOffset) % 1.0
            entry.rcvTime = time.time()
            car = self.cars[event.carId]
            car.lastRealTimeRcvTime = entry.rcvTime
            l = len(car.lapHistory)
            speed = math.sqrt(sum([v*v for v in entry.velocity]))
            car.maxSpeed = max(speed, car.maxSpeed)
            # driver active heuristics
            if speed < 0.1 and car.inactiveSince is None:
                car.inactiveSince = entry.rcvTime
            if speed > 3 and not car.inactiveSince is None:
                car.inactiveSince = None
            if car.active:
                if not car.inactiveSince is None and entry.rcvTime - car.inactiveSince > 5.:
                    car.active = False
            elif not car.active:
                if car.inactiveSince is None:
                    car.active = True
            if car.pitPosition is None and speed < 1.0:
                car.pitPosition = entry.worldPos
                acdebug("Recording pit position %s for car id %d", car.pitPosition, event.carId)
            itemToBeIgnored = False
            if l > 0:
                lastItem = self.cars[event.carId].lapHistory[-1]
                wpOld = lastItem.worldPos
                wpNew = entry.worldPos
                def sdist3d(a, b):
                    return (a[0]-b[0])**2 + (a[1] - b[1])**2 + (a[2]-b[2])**2
                dSqr = sdist3d(wpOld, wpNew)
                if dSqr < 1.**2:
                    # min resolution is 1 meter
                    itemToBeIgnored = True
                if entry.rcvTime - lastItem.rcvTime < 1.0:
                    # min resolution is 1 second
                    itemToBeIgnored = True
                if entry.normalizedSplinePos < lastItem.normalizedSplinePos:
                    # we want the normalized spline pos to increase
                    itemToBeIgnored = True
                if not car.lastHistoryEntry is None and not car.pitPosition is None:
                    # heuristics to detect "back to pits" for A/B tracks
                    dt = entry.rcvTime - car.lastHistoryEntry.rcvTime
                    def a_plus_b_times_c(a, b, c):
                        return [a[i] + b*c[i] for i in range(len(a))]
                    pLastToNow = a_plus_b_times_c(car.lastHistoryEntry.worldPos, dt, car.lastHistoryEntry.velocity)
                    pNowToLast = a_plus_b_times_c(entry.worldPos, -dt, entry.velocity)
                    if (sdist3d(pLastToNow, entry.worldPos) > 20.**2
                        and sdist3d(pNowToLast, car.lastHistoryEntry.worldPos) > 20.**2
                        and sdist3d(entry.worldPos, car.pitPosition) < 1.**2):
                            # wipe the lapHistory and start again
                            acdebug("CarID=%d back to pits heuristics", event.carId)
                            itemToBeIgnored = True
                            self.cars[event.carId].resetLap()
                for nsp in self.nspPositionsOfInterest:
                    if entry.normalizedSplinePos >= nsp and lastItem.normalizedSplinePos < nsp:
                        #acdebug("Got soft split nsp for soft split at %.3f: [%.3f - %.3f]", nsp, lastItem.normalizedSplinePos, entry.normalizedSplinePos)
                        itemToBeIgnored = False
            else: # len(lapHistory) == 0
                if entry.normalizedSplinePos > 0.5:
                    # we don't want to start a lap history right before the finish line
                    itemToBeIgnored = True
            self.cars[event.carId].lastHistoryEntry = entry
            self.cbRtUpdate(event.carId, entry)
            if l > 10000:
                # limit maximum number of items in the lists
                return
            if not itemToBeIgnored:
                if len(self.cars[event.carId].lapHistory) == 0:
                    # first item -> might be an A/B track like NS-tourist
                    self.cars[event.carId].resetLap()
                self.cars[event.carId].lapHistory.append(entry)
        else:
            self.acPlugin.getCarInfo(event.carId)

    def collisionEvent(self, event):
        if type(event) == CollisionCar:
            c1 = None
            c2 = None
            if event.car1_id in self.cars:
                c1 = self.cars[event.car1_id]
                self.cars[event.car1_id].collCarCount += 1
            if event.car2_id in self.cars:
                c2 = self.cars[event.car2_id]
                self.cars[event.car2_id].collCarCount += 1
            self.cbCarCollision(event, c1, c2)
        elif type(event) == CollisionEnv:
            c = None
            if event.carId in self.cars:
                c = self.cars[event.carId]
                self.cars[event.carId].collEnvCount += 1
            self.cbEnvCollision(event, c)

    def sendChatMessageToGuid(self, guid, message):
        for cid in self.cars:
            acdump("%d -> %s", cid, self.cars[cid].driverGuid)
            if self.cars[cid].driverGuid == guid:
                self.acPlugin.sendChat(cid, message)
                return
        acinfo("Unable to send message %s to guid=%s (guid not found)", message, guid)

    def broadcastChatMessage(self, message):
        self.acPlugin.broadcastChat(message)

    def adminCommand(self, command):
        self.acPlugin.adminCommand(command)
