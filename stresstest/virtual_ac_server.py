
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

from acplugins4python import ac_server_protocol
import random
import time
import functools
import threading
import socket
import math
import os, os.path
from ptracker_lib.client_server import ac_client_server
import ptracker_lib.helpers
import ptracker_lib.acsim

ptracker_lib.acsim.ac.log = print

ptracker_lib.helpers.restore_loggers(3)

class DictWrapper:
    def __init__(self, **kw):
        self.data = kw

    def __getattr__(self, a):
        if a in self.__dict__:
            return getattr(self, a)
        elif a in self.data:
            return self.data[a]
        else:
            return getattr(self.data, a)

vsConfig = DictWrapper(
     numPlayers=32, # number of server slots
     cars=["car0", "car1"], # different car names
     serverName="stresstest fake server",
     track="track0",
     udpPort=9600,
     playerStayTimeMinutes=(15,5), # mean/std of a player staying on server
     reconnectionTimeMinutes=(3,1), # mean/std of slot reconnection
     numberOfPtrackerVisitors=64, # number of visitors using ptracker
     numberOfNonPtrackerVisitors=64, # number of visitors not using ptracker
     practiceLength = 2, # in minutes
     qualyLength = 2, # in minutes
     raceLength = 4, # in laps
     lapLength = 1000, #  meters
     speed = (50, 1), # mean/std of a player's speed [m/s]
     playerBackToPitsProbability = 0.01,
     connectTimeMinutes = (0.5, 0.2), # mean/std for establishing a player's connection
     udp_plugin_address="127.0.0.1:12000",
     udp_plugin_local_port=11000)


class DriverPool:
    def __init__(self):
        self.free_drivers = ([str(7777*1000+i) for i in range(vsConfig.numberOfPtrackerVisitors)] +
                             [str(3333*1000+i) for i in range(vsConfig.numberOfNonPtrackerVisitors)])
        self.active_drivers = []

    def connect(self):
        i = random.choice(range(len(self.free_drivers)))
        self.active_drivers.append(self.free_drivers[i])
        self.free_drivers.remove(self.free_drivers[i])
        self.check()
        return self.active_drivers[-1]

    def disconnect(self, driver):
        i = self.active_drivers.index(driver)
        self.free_drivers.append(self.active_drivers[i])
        self.active_drivers.remove(self.active_drivers[i])
        self.check()

    def check(self):
        assert(len(self.active_drivers) + len(self.free_drivers) == vsConfig.numberOfPtrackerVisitors + vsConfig.numberOfNonPtrackerVisitors)
        assert(len(self.active_drivers) <= vsConfig.numPlayers)

class ActiveDriver:
    def __init__(self, guid, name, carId, t):
        self.guid = guid
        self.name = name
        self.carId = carId
        self.nsp = 0.2 # set on out lap.
        self.speed = random.gauss(*vsConfig.speed)
        self.worldPos = [0,0,0]
        self.velocity = [0,0,0]
        self.connectionCountdown = max(0,random.gauss(*vsConfig.connectTimeMinutes)*60)
        self.numLaps = 0
        self.lapTime = None
        self.bestLapTime = None
        self.lapStartT = t
        self.lastRTEvent = 0
        if self.guid[0] == '7':
            # ptracker visitor
            print("create ptracker")
            localp = os.path.split(__file__)[0]
            if localp == "": localp = "."
            ptracker_executable = ["C:/vpython33/Scripts/python.exe", "-m", "ptstarter", guid, localp + "/../ptracker-server.py" ]
            print(ptracker_executable)
            print(os.getcwd())
            self.ptracker = ac_client_server.create_ac_client_server(ptracker_executable)

    def tick(self, dt, t):
        if self.connectionCountdown >= 0:
            self.connectionCountdown -= dt
            if self.connectionCountdown < 0:
                vsInstance.clientLoaded(self)
        else:
            l = vsConfig.lapLength
            self.nsp += self.speed*dt / l
            if self.nsp > 1.:
                self.numLaps += 1
                self.nsp -= 1.
                lapEndT = t - self.nsp * l / self.speed
                self.lapTime = lapEndT - self.lapStartT
                self.lapStartT = lapEndT
                if self.bestLapTime is None or self.lapTime < self.bestLapTime:
                    self.bestLapTime = self.lapTime
                vsInstance.lapCompleted(self, self.lapTime)
                self.speed = random.gauss(*vsConfig.speed)
                alpha = self.nsp * math.pi
                r = vsConfig.lapLength/(2*math.pi)
                sa = math.sin(alpha)
                ca = math.cos(alpha)
                self.worldPos = [sa*r, 0, ca*r]
                self.velocity = [ca*self.speed, 0, -sa*self.speed]
                if vsInstance.rtInterval > 0:
                    self.lastRTEvent -= dt
                    if self.lastRTEvent <= 0:
                        self.lastRTEvent = vsInstance.rtInterval
                        vsInstance.rtEvent(self)

    def resetSession(self, t):
        self.numLaps = 0
        self.lapTime = None
        self.bestLapTime = None
        self.lapStartT = t
        self.nsp = 0.2

class Slot:
    def __init__(self, carIdx):
        self.activeDriver = None
        self.carIdx = carIdx
        self.disconnectionCountdown = -1
        self.connectionCountdown = max(0,random.gauss(*vsConfig.reconnectionTimeMinutes))*60.

    def tick(self, dt, t):
        if self.activeDriver is None:
            self.connectionCountdown -= dt
            if self.connectionCountdown < 0:
                self.activeDriver = vsInstance.connectSlot(self)
                self.activeDriver.car = vsConfig.cars[self.carIdx]
                self.disconnectionCountdown = max(0.1, random.gauss(*vsConfig.playerStayTimeMinutes))*60.
        else:
            self.activeDriver.tick(dt, t)
            self.disconnectionCountdown -= dt
            if self.disconnectionCountdown < 0:
                vsInstance.disconnectSlot(self)
                self.connectionCountdown = max(0.1,random.gauss(*vsConfig.reconnectionTimeMinutes))*60.
                self.activeDriver = None

class Session:
    def __init__(self):
        self.currType = ac_server_protocol.SESST_PRACTICE
        self.countdown = vsConfig.practiceLength * 60.
        self.index = 0
        self.sessionTime = self.countdown
        self.numLaps = None

    def tick(self, dt, t):
        if not self.countdown is None:
            self.countdown -= dt
            if self.countdown < 0:
                self.newSession()
        else:
            if max([s.activeDriver.numLaps if not s.activeDriver is None else 0 for s in vsInstance.slots]) >= self.numLaps:
                self.countdown = 30.

    def newSession(self):
        vsInstance.finishSession()
        if self.currType == ac_server_protocol.SESST_PRACTICE:
            self.currType = ac_server_protocol.SESST_QUALIFY
            self.countdown = vsConfig.qualyLength * 60.
            self.numLaps = None
            self.index = 1
        elif self.currType == ac_server_protocol.SESST_QUALIFY:
            self.currType = ac_server_protocol.SESST_RACE
            self.countdown = None
            self.numLaps = vsConfig.raceLength
            self.index = 2
        else:
            self.currType = ac_server_protocol.SESST_PRACTICE
            self.countdown = vsConfig.practiceLength * 60.
            self.numLaps = None
            self.index = 0
        self.sessionTime = self.countdown
        vsInstance.newSession()

vsInstance = None
class VirtualServer(threading.Thread):
    def __init__(self, **cfg):
        threading.Thread.__init__(self)
        global vsInstance
        vsConfig.update(cfg)
        vsInstance = self
        self.host = vsConfig.udp_plugin_address.split(":")[0]
        self.sendPort = int(vsConfig.udp_plugin_address.split(":")[1])
        self.rcvPort = vsConfig.udp_plugin_local_port
        self.socket = self.openSocket(
            self.host,
            self.rcvPort,
            self.sendPort,
            None)
        self.slots = [Slot(int(i*len(vsConfig.cars)/vsConfig.numPlayers)) for i in range(vsConfig.numPlayers)]
        self.driverPool = DriverPool()
        self.session = Session()
        self.lastT = time.time()
        self.stopped = True
        self.daemon = True
        self.rtInterval = 0

    def getFakeConfig(self):
        vsc = vsConfig.copy()
        vsc['cars'] = ";".join(vsConfig.cars)
        return """\
[SERVER]
NAME=%(serverName)s
CARS=%(cars)s
TRACK=%(track)s
UDP_PORT=%(udpPort)d
FUEL_RATE=100
DAMAGE_MULTIPLIER=100
TYRE_WEAR_RATE=100
ALLOWED_TYRES_OUT=2
ABS_ALLOWED=1
TC_ALLOWED=1
STABILITY_ALLOWED=0
AUTOCLUTCH_ALLOWED=0
TYRE_BLANKETS_ALLOWED=1
MAX_CLIENTS=%(numPlayers)d
UDP_PLUGIN_LOCAL_PORT=%(udp_plugin_local_port)d
UDP_PLUGIN_ADDRESS=%(udp_plugin_address)s
RACE_OVER_TIME=60
""" % vsc

    def run(self):
        self.stopped = False
        sp = ac_server_protocol.ProtocolVersion(version=ac_server_protocol.PROTOCOL_VERSION)
        self.sendPacket(sp)
        self.newSession()
        while not self.stopped:
            t = time.time()
            self.tick()
            while 1:
                try:
                    data, addr = self.socket.recvfrom(4096)
                    r = ac_server_protocol.parse(data)
                    if type(r) == ac_server_protocol.GetSessionInfo:
                        self.sessionInfo(r.sessionIndex)
                    elif type(r) == ac_server_protocol.GetCarInfo:
                        self.carInfo(r.carId)
                    elif type(r) == ac_server_protocol.EnableRealtimeReport:
                        self.rtInterval = r.intervalMS/1000.
                except socket.timeout:
                    break
                except ConnectionResetError:
                    pass
                    #self.socket = self.openSocket(
                    #    self.host,
                    #    self.rcvPort,
                    #    self.sendPort,
                    #    self.socket)
            wt = 0.1-(time.time()-t)
            time.sleep(max(0,wt))

    def openSocket(self, host, rcvp, sendp, s):
        if not s is None: s.close()
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.bind( (host, rcvp) )
        # set up a 0.05s pulse, need this to be able to Ctrl-C the python apps
        s.settimeout(0.05)
        return s

    def connectSlot(self, slot):
        driverGuid = self.driverPool.connect()
        carId = self.slots.index(slot)
        carModel = vsConfig.cars[slot.carIdx]
        carSkin = 'skin0'
        driverIdx = sorted(self.driverPool.active_drivers + self.driverPool.free_drivers).index(driverGuid)
        driverName = "Driver %s" % (driverGuid)
        sp = ac_server_protocol.NewConnection(driverName=driverName, driverGuid=driverGuid, carId=carId, carModel=carModel, carSkin=carSkin)
        self.sendPacket(sp)
        return ActiveDriver(driverGuid, driverName, carId, self.lastT)

    def disconnectSlot(self, slot):
        driverGuid = slot.activeDriver.guid
        driverName = slot.activeDriver.name
        carId = self.slots.index(slot)
        carModel = vsConfig.cars[slot.carIdx]
        carSkin = 'skin0'
        sp = ac_server_protocol.ConnectionClosed(driverName=driverName, driverGuid=driverGuid, carId=carId, carModel=carModel, carSkin=carSkin)
        self.driverPool.disconnect(driverGuid)
        self.sendPacket(sp)

    def clientLoaded(self, activeDriver):
        sp = ac_server_protocol.ClientLoaded(carId = activeDriver.carId)
        self.sendPacket(sp)

    def lapCompleted(self, activeDriver, lapTime):
        carId = activeDriver.carId
        cuts = 0 if random.uniform(0,1) < 0.9 else random.randint(1, 5)
        gripLevel = 0.99
        leaderboard = list(filter(lambda s: not s is None, [s.activeDriver for s in self.slots]))
        if self.session.currType == ac_server_protocol.SESST_RACE:
            def raceCmpDrivers(a, b):
                if a.numLaps > b.numLaps:
                    return -1
                if b.numLaps > a.numLaps:
                    return 1
                if a.lapStartT < b.lapStartT:
                    return -1
                if b.lapStartT < a.lapStartT:
                    return 1
                return 0
            leaderboard.sort(key = functools.cmp_to_key(raceCmpDrivers))
        else:
            leaderboard.sort(key = lambda x: x.bestLapTime if not x.bestLapTime is None else 1000000.)
        leaderboard = [ac_server_protocol.LeaderboardEntry(carId=x.carId, lapTime=int(x.lapTime*1000) if not x.lapTime is None else 0, laps=x.numLaps) for x in leaderboard]
        sp = ac_server_protocol.LapCompleted(carId = carId, lapTime = int(lapTime*1000), cuts=cuts, gripLevel=gripLevel, leaderboard=leaderboard)
        self.sendPacket(sp)

    def carInfo(self, carId):
        slot = self.slots[carId]
        driver = slot.activeDriver
        carModel = vsConfig.cars[slot.carIdx]
        self.sendPacket(ac_server_protocol.CarInfo(carId=carId, isConnected=not driver is None, carModel=carModel, carSkin='skin0',
                                                   driverName=driver.name if not driver is None else '',
                                                   driverTeam='',
                                                   driverGuid=driver.guid if not driver is None else ''))

    def rtEvent(self, driver):
        rtEvent = ac_server_protocol.CarUpdate(
            carId = driver.carId,
            worldPos = (driver.worldPos),
            velocity = (driver.velocity),
            gear = 0,
            engineRPM = 0,
            normalizedSplinePos = driver.nsp)
        self.sendPacket(rtEvent)

    def finishSession(self):
        sp = ac_server_protocol.EndSession(filename="fake")
        self.sendPacket(sp)
        for s in self.slots:
            if not s.activeDriver is None:
                s.activeDriver.resetSession(self.lastT)

    def newSession(self):
        return self.sessionInfo(-1, ac_server_protocol.NewSession)

    def sessionInfo(self, index, ptype = ac_server_protocol.SessionInfo):
        names = {ac_server_protocol.SESST_PRACTICE : "Practice", ac_server_protocol.SESST_QUALIFY : "Qualify", ac_server_protocol.SESST_RACE : "Race", }
        indices = {0:ac_server_protocol.SESST_PRACTICE, 1:ac_server_protocol.SESST_QUALIFY, 2:ac_server_protocol.SESST_RACE, }
        time = {0: vsConfig.practiceLength * 60., 1: vsConfig.qualyLength * 60., 2: 0}
        laps = {0: 0, 1: 0, 2: vsConfig.raceLength}

        if index == -1: index = self.session.index
        stype = indices[index]

        sp = ptype(
            version = ac_server_protocol.PROTOCOL_VERSION,
            sessionIndex = index,
            currSessionIndex = self.session.index,
            sessionCount = 3,
            serverName = vsConfig.serverName,
            track = vsConfig.track,
            track_config = "",
            name = names[stype],
            sessionType = stype,
            sessionTime = int(self.session.sessionTime if not self.session.sessionTime is None else 0),
            laps = self.session.numLaps if not self.session.numLaps is None else 0,
            waittime = 30,
            ambientTemp = 26,
            roadTemp = 32,
            elapsedMS = 0,
            wheather = 'wheather',
        )
        self.sendPacket(sp)

    def tick(self):
        t = time.time()
        dt = t - self.lastT
        for s in self.slots:
            s.tick(dt, t)
        self.session.tick(dt, t)
        self.lastT = t

    def sendPacket(self, p):
        #print(str(p)[:120])
        try:
            self.socket.sendto(p.to_buffer(), (self.host, self.sendPort))
        except ConnectionResetError:
            self.socket = self.openSocket(self.host, self.rcvPort, self.sendPort, self.socket)
