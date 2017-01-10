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


import time
import sys
import socket
import select
import functools
import urllib
import traceback
import random
import copy
import os
import platform
import struct
import hashlib
from socketserver import ThreadingTCPServer,BaseRequestHandler
from threading import Thread, Timer
from stracker_lib import config
from stracker_lib import version
from stracker_lib.logger import *
from stracker_lib import http_server
from stracker_lib import http_server_base
from stracker_lib.banlist import BanListHandler
from stracker_lib import stracker_udp_plugin
from stracker_lib.stacktracer import ShortlyLockedRLock as RLock
from stracker_lib import livemap
from stracker_lib.ac_session_manager import SessionManager
from stracker_lib import chatfilter
from stracker_lib.mr_query import MRQuery
from ptracker_lib.ps_protocol import ProtocolHandler
from ptracker_lib import dbgeneric
from ptracker_lib.database import LapDatabase
from ptracker_lib.message_types import *
from ptracker_lib.helpers import *
from ptracker_lib.constants import *
from ptracker_lib.lap_collector import fromLapHistory

def acquire_lock(func):

    @functools.wraps(acquire_lock)
    def _decorator(self, *args, **kwargs):
        with self.lock:
            res = func(self, *args, **kwargs)
            return res

    return _decorator

connections = []

class InfoPageNotAvailable(Exception):
    pass

PTRACKER_LAP_TIMEOUT = 7

class SoftSplitCalculator:
    def __init__(self, database):
        self.database = database
        self.track = None
        self.update()

    def setTrack(self, track):
        if track != self.track:
            self.track = track
            self.update()

    def update(self):
        if not self.track is None:
            r = self.database.getBestLapWithSectors(__sync=True, trackname=self.track, carname=None, assertValidSectors=1, allowSoftSplits=True, assertHistoryInfo=True)
            self._calctsps(r)
        else:
            self.bestLapWithSectors = None
            self.softSectorsTsp = []

    @callbackDecorator
    def _calctsps(self, db_res):
        bestLapWithSectors = db_res()
        if not bestLapWithSectors is None:
            self.bestLapWithSectors = bestLapWithSectors
            st = 0
            s = 0
            self.softSectorsTsp = []
            while 1:
                if s >= len(self.bestLapWithSectors.sectorTimes) or self.bestLapWithSectors.sectorTimes[s] is None:
                    break
                st += self.bestLapWithSectors.sectorTimes[s]
                self.softSectorsTsp.append(self.bestLapWithSectors.tspAtT(st, False))
                s += 1
        acinfo("update soft split positions for %s %s", self.track, ["%.3f"%tsp for tsp in self.softSectorsTsp])

    def calculate_sectors(self, lapHistory):
        try:
            lh = lapHistory
            try:
                try:
                    lc = fromLapHistory(lh.lapTime, lh.sectorTimes, lh.sampleTimes, lh.worldPositions, lh.velocities, lh.normSplinePositions, a2b=False)
                except AssertionError:
                    lc = fromLapHistory(lh.lapTime, lh.sectorTimes, lh.sampleTimes, lh.worldPositions, lh.velocities, lh.normSplinePositions, a2b=True)
            except AssertionError:
                lc = None
            if lc is None or len(self.softSectorsTsp) <= 1:
                return []
            splits = [0]
            for s in self.softSectorsTsp[:-1]:
                splits.append(lc.tAtTsp(s, False)+0.5)
            splits.append(lapHistory.lapTime)
            splits = [int(s+0.5) for s in splits]
            sectors = []
            for i in range(1,len(splits)):
                sectors.append(splits[i]-splits[i-1])
            acinfo("Calculated splits: %s", sectors)
            return sectors
        except:
            acwarning("Error while calculating soft splits. Ignoring.")
            acwarning(traceback.format_exc())
            return []

class ACSession:
    __slots__ = [
        'penaltiesEnabled',
        'allowedTyresOut',
        'ptrackerTyresOut',
        'tyreWearFactor',
        'fuelRate',
        'damage',
        'tcAllowed',
        'absAllowed',
        'tyreBlanketsAllowed',
        'stabilityAllowed',
        'autoclutchAllowed',
        'cars',
        'carsUi',
        'car_shortener',
        'currSessionIndex',
        'track',
        'track_config',
        'trackname',
        'sessionType',
        'ambientTemp',
        'roadTemp',
        'sessionTime',
        'numLaps',
        'raceFinished',
        'apprSessionStartTime',
        ]

    def __init__(self):
        self.raceFinished = False
        self.updateServerInfo()

    def updateServerInfo(self):
        self.update(
            penaltiesEnabled= 0 <= config.acconfig.getint('SERVER', 'ALLOWED_TYRES_OUT') <= 3,
            allowedTyresOut=config.acconfig.getint('SERVER', 'ALLOWED_TYRES_OUT'),
            tyreWearFactor=config.acconfig.getint('SERVER', 'TYRE_WEAR_RATE')/100.,
            fuelRate=config.acconfig.getint('SERVER', 'FUEL_RATE')/100.,
            damage=config.acconfig.getint('SERVER', 'DAMAGE_MULTIPLIER')/100.,
            tcAllowed=config.acconfig.getint('SERVER', 'TC_ALLOWED'),
            absAllowed=config.acconfig.getint('SERVER', 'ABS_ALLOWED'),
            tyreBlanketsAllowed=config.acconfig.getint('SERVER', 'TYRE_BLANKETS_ALLOWED'),
            stabilityAllowed=config.acconfig.getint('SERVER', 'STABILITY_ALLOWED'),
            autoclutchAllowed=config.acconfig.getint('SERVER', 'AUTOCLUTCH_ALLOWED'),
            cars = set(map(lambda x: x.strip().lower() , config.acconfig['SERVER'].get('CARS').split(";"))),
            ptrackerTyresOut=config.config.LAP_VALID_CHECKS.ptrackerAllowedTyresOut,
        )
        if self.ptrackerTyresOut < 0:
            if self.allowedTyresOut < 0 or self.allowedTyresOut >= 4:
                self.ptrackerTyresOut = 2
            else:
                self.ptrackerTyresOut = self.allowedTyresOut
        self.carsUi ={}
        for c in self.cars: self.carsUi[c] = c
        self.car_shortener = lambda x: x

    def updateSessionInfo(self, sessionInfo):
        if sessionInfo.sessionIndex == sessionInfo.currSessionIndex:
            self.currSessionIndex = sessionInfo.currSessionIndex
            self.track = sessionInfo.track.lower()
            self.track_config = sessionInfo.track_config.lower()
            self.trackname = self.track + ("-"+self.track_config if not self.track_config == "" else "")
            self.sessionType = sessionInfo.sessionType
            self.sessionTime = sessionInfo.sessionTime
            self.numLaps = sessionInfo.laps
            self.ambientTemp = sessionInfo.ambientTemp
            self.roadTemp = sessionInfo.roadTemp
            self.apprSessionStartTime = sessionInfo.sessionStateRcvTime - sessionInfo.elapsedMS/1000.

    def updateTrackAndCarInfo(self, tac):
        try:
            ci = dict([(x['acname'], x['uiname']) for x in tac['cars']])
            for c in list(ci.keys()):
                if ci[c] is None:
                    del ci[c]
            carsUi = []
            self.carsUi = {}
            for c in self.cars:
                carsUi.append(ci.get(c, c))
                self.carsUi[c] = carsUi[-1]
            acdebug("carsUi=%s", carsUi)
            shortener = StringShortener(carsUi, 10)
            self.car_shortener = lambda x: shortener.apply(x)
            acdebug("carsUiShort=%s", [self.car_shortener(x) for x in carsUi])
        except KeyboardInterrupt:
            raise
        except:
            acwarning("error while performing car name compression. Continue anyways.")
            acwarning(traceback.format_exc())

    def update(self, **kw):
        for k in kw:
            setattr(self, k, kw[k])

    def getSessionState(self):
        return {
            'penaltiesEnabled': self.penaltiesEnabled,
            'allowedTyresOut': self.allowedTyresOut,
            'tyreWearFactor': self.tyreWearFactor,
            'fuelRate': self.fuelRate,
            'damage': self.damage,
            'tcAllowed': self.tcAllowed,
            'absAllowed': self.absAllowed,
            'tyreBlanketsAllowed': self.tyreBlanketsAllowed,
            'stabilityAllowed': self.stabilityAllowed,
            'autoclutchAllowed': self.autoclutchAllowed,
            'ptrackerTyresOut': self.ptrackerTyresOut,
        }

class ACLap:
    __slots__ = [
        "lapTime",
        "cuts",
        "gripLevel",
        "lapCount",
        "totalTime",
        "lapTimeRcvTime",
        "collCarCount",
        "collEnvCount",
        "lapHistory",
        "maxSpeed",
        "tyre",
        "pt_valid",
        "sectorTimes",
        "sectorsAreSoftSplits",
        "staticAssists",
        "dynamicAssists",
        "timeInPitLane",
        "timeInPit",
        "fuelRatio",
        "escKeyPressed",
        "timeoutTimestamp",
        "savedInDB",
        "valid",
        "ballast"
    ]
    def __init__(self, lapCompletedEvent = None, ptrackerLap = None):
        if not lapCompletedEvent is None:
            lc = lapCompletedEvent
            self.lapTime = lc.lapTime
            self.cuts = lc.cuts
            self.gripLevel = lc.gripLevel
            self.lapCount = lc.lapCount
            self.totalTime = lc.sumLapTimes
            self.lapTimeRcvTime = lc.lapTimeRcvTime
            self.collCarCount = lc.collCarCount
            self.collEnvCount = lc.collEnvCount
            self.lapHistory = lc.lapHistory
            self.maxSpeed = lc.maxSpeed
            self.tyre = None
            self.pt_valid = 2
            self.sectorTimes = [None]*10
            self.sectorsAreSoftSplits = None
            self.staticAssists = {}
            self.dynamicAssists = {}
            self.timeInPitLane = None
            self.timeInPit = None
            self.fuelRatio = -1.
            self.escKeyPressed = None
            self.ballast = None
        if not ptrackerLap is None:
            lpt = ptrackerLap
            self.lapTime = lpt['lapTime']
            self.cuts = None
            self.gripLevel = None
            self.lapCount = None
            self.totalTime = None
            self.lapTimeRcvTime = None
            self.collCarCount = None
            self.collEnvCount = None
            self.lapHistory = None
            self.maxSpeed = lpt.get('maxSpeed', None)
            self.tyre = lpt['tyre']
            self.pt_valid = lpt['valid']
            self.sectorTimes = list(map(lambda x: x or None, lpt['sectorTimes']))
            self.sectorsAreSoftSplits = lpt['sectorsAreSoftSplits']
            self.staticAssists =lpt.get('staticAssists',{}) #TODO:  self.correctStaticAssists(
            self.dynamicAssists = lpt.get('dynamicAssists',{}) #TODO: self.correctDynamicAssists(
            self.timeInPitLane = lpt.get('timeInPitLane', None)
            self.timeInPit = lpt.get('timeInPit', None)
            self.fuelRatio = lpt.get('fuelRatio', -1.)
            self.escKeyPressed = lpt.get('escKeyPressed', None)
            self.ballast = lpt.get('ballast', None)
        self.valid = None # computed in saveLap
        self.timeoutTimestamp = time.time()
        self.savedInDB = False

    def mergeWithPtracker(self, other):
        myassert(self.lapTime == other.lapTime)
        myassert(not self.cuts is None)
        self.maxSpeed = other.maxSpeed if not other.maxSpeed is None else self.maxSpeed
        self.tyre = other.tyre
        self.pt_valid = other.pt_valid
        self.sectorTimes = other.sectorTimes
        self.sectorsAreSoftSplits = other.sectorsAreSoftSplits
        self.staticAssists = other.staticAssists
        self.dynamicAssists = other.dynamicAssists
        self.timeInPitLane = other.timeInPitLane
        self.timeInPit = other.timeInPit
        self.ballast = other.ballast
        self.fuelRatio = other.fuelRatio

class ACDriver:
    __slots__ = [
        "guid",
        "name",
        "team",
        "car",
        "ac_version",
        "pt_version",
        "track_checksum",
        "car_checksum",
        "ptracker_conn",
        "ptracker_invalid_version",
        "pending_messages",
        "carId", # -1 if not connected to the game
        "laps",
        "raceFinished",
        "pt_lap",
        "cbNewLap",
        "active",
        "normalizedSplinePos",
        "p3d",
        "currLapInvalidated",
        "receivedBadWordWarnings",
        "minorating",
    ]

    def __init__(self, guid, newLapCallback):
        self.guid = guid
        self.name = "?GUID=%s" % guid
        self.team = None
        self.car = None
        self.ac_version = "unknown"
        self.pt_version = "unknown"
        self.track_checksum = "unknown"
        self.car_checksum = "unknown"
        self.ptracker_conn = None
        self.minorating = ''
        self.pending_messages = []
        self.carId = -1
        self.laps = []
        self.raceFinished = False
        self.ptracker_invalid_version= False
        self.pt_lap = None
        self.cbNewLap = newLapCallback
        self.active = False
        self.normalizedSplinePos = 0.0
        self.p3d = (0.0, 0.0, 0.0)
        self.currLapInvalidated = False
        self.receivedBadWordWarnings = 0

    def newConnectionEvent(self, carState):
        self.name = carState.driverName
        self.team = carState.driverTeam
        self.car = carState.carModel
        self.carId = carState.carId

    def updatePtrackerConn(self, connection, ac_version, pt_version, track_checksum, car_checksum):
        self.ptracker_conn = connection
        self.ac_version = ac_version
        self.pt_version = pt_version
        self.track_checksum = track_checksum
        self.car_checksum = car_checksum

    def lapCompletedEvent(self, carState, apprSessionStartTime):
        if self.raceFinished:
            acinfo("%s: Ignoring lapCompleted event because this driver has finished his race.", self.guid)
            return
        l = ACLap(lapCompletedEvent=carState)
        if len(self.laps) == 0: # first lap
            sessStartFromLapTime = (carState.lapTimeRcvTime - l.lapTime/1000.)
            if abs(sessStartFromLapTime - apprSessionStartTime) > 0.5:
                acinfo("Mid race joiner %s detected. Trying to handle this with limited knowledge :(", self.guid)
                l.totalTime = int((carState.lapTimeRcvTime - apprSessionStartTime)*1000.)
            else:
                l.totalTime = l.lapTime
        else:
            l.totalTime = self.laps[-1].totalTime + l.lapTime
        self.laps.append(l)
        self.merge_pt_lap()
        self.currLapInvalidated = False

    def invalidateCurrentLap(self):
        ret = not self.currLapInvalidated
        self.currLapInvalidated = True
        return ret

    def ptrackerLapInfo(self, ptl):
        self.pt_lap = ACLap(ptrackerLap=ptl)
        acdebug("ptrackerLapInfo received, laptime=%s", self.pt_lap.lapTime)
        self.merge_pt_lap()

    def merge_pt_lap(self, force=False):
        t = time.time()
        if len(self.laps) > 0:
            lastLap = self.laps[-1]
            if not lastLap.savedInDB:
                if not self.pt_lap is None and self.pt_lap.lapTime == lastLap.lapTime:
                    # match
                    lastLap.mergeWithPtracker(self.pt_lap)
                    self.pt_lap = None
                    acdebug("saving lap with ptracker info")
                    lastLap.savedInDB = True
                    self.cbNewLap(self, lastLap)
                elif self.ptracker_conn is None:
                    acdebug("saving lap without ptracker info (because of no connection)")
                    lastLap.savedInDB = True
                    self.cbNewLap(self, lastLap)
                elif t - lastLap.timeoutTimestamp > PTRACKER_LAP_TIMEOUT or force:
                    acwarning("%s: no ptracker lap info, though ptracker connection is there. Saving lap anyway.", self.guid)
                    if not self.pt_lap is None:
                        ltpt = self.pt_lap.lapTime
                    else:
                        ltpt = -1
                    acwarning("time elapsed: %f, force: %s, laptime(pt)=%s, laptime(st)=%s]", t-lastLap.timeoutTimestamp, force, ltpt, lastLap.lapTime)
                    lastLap.savedInDB = True
                    self.cbNewLap(self, lastLap)
        if not self.pt_lap is None and t - self.pt_lap.timeoutTimestamp > PTRACKER_LAP_TIMEOUT:
            acwarning("%s: did not find lap matching ptracker lap. Discarding.", self.guid)
            self.pt_lap = None

    def lapCount(self):
        if len(self.laps) == 0:
            return 0
        return self.laps[-1].lapCount

    def totalTime(self):
        if len(self.laps) == 0:
            return None
        return self.laps[-1].totalTime

    def bestTimeACValid(self):
        laps = list(filter(lambda l: l.cuts in [0,None], self.laps))
        if len(laps) == 0:
            return None
        return min([l.lapTime for l in laps])

    def bestTime(self):
        laps = self.laps
        if len(laps) == 0:
            return None
        return min([l.lapTime for l in laps])

    def lastTime(self):
        if len(self.laps) == 0:
            return None
        return self.laps[-1].lapTime

    def tyre(self):
        if len(self.laps) == 0:
            return ""
        res = self.laps[-1].tyre
        return res if not res is None else ""

    def prepareNewSession(self):
        self.laps = []
        self.pt_lap = None
        self.raceFinished = False

    def getPTACVersion(self):
        if self.pt_version is None:
            ptv = "unknown"
        else:
            ptv = self.pt_version
        if self.ac_version is None:
            acv = "unknown"
        else:
            acv = self.ac_version
        if acv == "unknown" and ptv == "unknown":
            return acv
        return ptv + " PT@AC " + acv

class AllDrivers:
    def __init__(self):
        self.drivers = []

    def addDriver(self, driver):
        myassert(driver.carId >= 0)
        for d in self.drivers:
            if d.carId == driver.carId:
                acwarning("same car id for drivers %s and %s. Making old driver inactive", d.guid, driver.guid)
                d.carId = -1
            if d.guid == driver.guid and d.car == driver.car:
                # reconnection of driver, just update the car id
                d.carId = driver.carId
                d.ptracker_conn = driver.ptracker_conn
                d.pending_messages = driver.pending_messages
                return d
        self.drivers.append(driver)
        return driver

    def byCarId(self, carId):
        for d in self.drivers:
            if d.carId == carId:
                return d

    def byGuidAll(self, guid):
        res = []
        for d in self.drivers:
            if d.guid == guid:
                res.append(d)
        res.sort(key=lambda d: -d.carId) # assert that active drivers are at the front
        return res

    def byGuidActive(self, guid):
        for d in self.drivers:
            if d.guid == guid and d.carId >= 0:
                return d

    def allDriversWithPtracker(self):
        res = []
        for d in self.drivers:
            if not d.ptracker_conn is None:
                res.append(d)
        return res

    def allActive(self):
        res = []
        for d in self.drivers:
            if d.carId >= 0:
                res.append(d)
        return res

    def cmpPlayerInSessionPrio(self, d1, d2):
        if d1.raceFinished and not d2.raceFinished:
            return -1
        if d2.raceFinished and not d1.raceFinished:
            return +1
        if d1.lapCount() > d2.lapCount():
            return -1
        if d2.lapCount() > d1.lapCount():
            return +1
        return 0

    def filterForClassification(self):
        driversByGuid = {}
        res = []
        for d in self.drivers:
            if not d.guid in driversByGuid:
                driversByGuid[d.guid] = []
            driversByGuid[d.guid].append(d)
        for guid in driversByGuid:
            p = sorted(driversByGuid[guid], key=functools.cmp_to_key(self.cmpPlayerInSessionPrio))
            res.append(p[0])
        return res

    def setupNewSession(self):
        newDrivers = []
        for d in self.drivers:
            if d.carId >= 0:
                d.prepareNewSession()
                newDrivers.append(d)
        self.drivers = newDrivers

class SetupDescription:
    def __init__(self, car, setup, source_guid):
        self.car = car
        self.setup = setup
        self.source_guid = source_guid

class ACMonitor:

    def __init__(self, database):
        self.lock = RLock()
        self.database = database
        self.database.setOnline(__sync=True, server_name=config.config.STRACKER_CONFIG.server_name, guids_online=[])()
        self.admin_guids = set()
        self.udp_port = config.acconfig['SERVER'].getint('UDP_PORT')
        self.adminpwd = config.acconfig['SERVER'].get('ADMIN_PASSWORD', None)
        self.currentSession = None
        self.mr_query = MRQuery(database, self.new_mr_rating)
        self.sessionStartTime = time.time()
        self.allDrivers = AllDrivers()
        self.setups = {}
        self.newServerDataAvailable = set() # contains guids which need an update
        self.chat_msg_types = set(config.config.MESSAGES.message_types_to_send_over_chat.split("+"))
        self.sendChatMessageToPlayer = lambda *args, **kw: None
        self.nspPositionsChanged = lambda newNspPositions: None
        self.raceFinished = lambda *args, **kw: None
        self.softSplitCalculator = SoftSplitCalculator(self.database)
        self.lastRTPositionUpdate = time.time()

    # --------------------------------------------------------------------------------------------------
    # --------------------------------------------------------------------------------------------------
    # Ptracker requests
    # --------------------------------------------------------------------------------------------------
    # --------------------------------------------------------------------------------------------------

    @acquire_lock
    def signin(self, trackname, guid, car, ac_version, pt_version, track_checksum, car_checksum):
        if trackname == '':
            # initial signin
            myassert( car == '' and ac_version == '' and track_checksum == '' and car_checksum == '' )
            car = None
            trackname = None
            ac_version = None
            track_checksum = None
            car_checksum = None
        for c in connections:
            if c.guid == guid:
                break
        d = self.allDrivers.byGuidActive(guid)
        if c.guid == guid:
            ptcm = config.config.STRACKER_CONFIG.ptracker_connection_mode
            if ptcm == config.config.PTC_NEWER and c.proto.prot_version < c.proto.PROT_VERSION and c.proto.prot_version >= 8:
                d.ptracker_invalid_version = True
                return 0
        else:
            acerror("This is unexpected...")
            return
        c.signin_info = {'car':car, 'ac_version':ac_version, 'pt_version':pt_version, 'track_checksum':track_checksum, 'car_checksum':car_checksum}
        if not d is None:
            self.check_for_ptracker_connection(d)
        else:
            acdebug('driver not (yet) connected. delaying welcome stuff.')
        self.ptClientsNewServerData()
        return 1

    @acquire_lock
    def check_for_ptracker_connection(self, driver):
        if len(connections) == 0: return
        for c in connections:
            if c.guid == driver.guid:
                break
        if c.guid == driver.guid and hasattr(c, 'signin_info'):
            acdebug('found pending ptracker connection')
            si = c.signin_info
            driver.ptracker_invalid_version = False
            if not si['car'] is None and si['car'] != driver.car:
                acwarning("driver %s has a different ptracker car than reported in udp?", driver.guid)
            else:
                driver.updatePtrackerConn(c, si['ac_version'], si['pt_version'], si['track_checksum'], si['car_checksum'])
            if not driver.track_checksum is None and not driver.car_checksum is None:
                self.compare_checksums(driver.guid)
            self.ptClientsNewServerData()
            return 1

    @acquire_lock
    def ptClientsNewServerData(self):
        ptrackerClients = set([d.guid for d in self.allDrivers.allDriversWithPtracker()])
        self.newServerDataAvailable = self.newServerDataAvailable.union(ptrackerClients)
        self.send_server_data()

    @acquire_lock
    def get_player_name(self, guid):
        d = self.allDrivers.byGuidAll(guid)
        if len(d) > 0:
            return d[0].name
        return "?GUID=%s" % guid

    @acquire_lock
    def get_team_name(self, guid):
        d = self.allDrivers.byGuidAll(guid)
        if len(d) > 0:
            return d[0].team
        return None

    @acquire_lock
    def compare_checksums(self, guid_of_interest = None):
        if not config.config.STRACKER_CONFIG.perform_checksum_comparisons:
            return

        cars = {}
        tracks = {}
        ptDrivers = self.allDrivers.allDriversWithPtracker()
        for d in ptDrivers:
            tcs = d.track_checksum
            ccs = d.car_checksum
            car = d.car
            if not tcs in tracks:
                tracks[tcs] = []
            if not tcs is None:
                tracks[tcs].append(d.guid)
            if not car is None and not ccs is None:
                if not car in cars:
                    cars[car] = {}
                if not ccs in cars[car]:
                    cars[car][ccs] = []
                cars[car][ccs].append(d.guid)

        def perform_check(self, obj, objname, req):
            checksums = []
            for cs in list(obj.keys()):
                if cs is None:
                    del obj[cs]
                else:
                    checksums.append((cs, len(obj[cs])))
            if req is None:
                if len(obj) > 1:
                    # check, if a majority checksum is available
                    checksums.sort(key=lambda x: x[1], reverse=True)
                    majority = checksums[0][1]
                    minorityGuids = []
                    for cs in checksums[1:]:
                        minorityGuids.extend(obj[cs[0]])
                    if guid_of_interest is None or guid_of_interest in minorityGuids:
                        if len(minorityGuids) < majority:
                            if len(minorityGuids) <= 3:
                                npr = 3
                                addMsg = ""
                            else:
                                npr = 2
                                addMsg = " and %d other players" % (len(minorityGuids)-npr)
                            minorityPlayers = sorted(list(map(lambda x: self.get_player_name(x), minorityGuids)))[:npr]
                            msg = ", ".join(minorityPlayers) + addMsg + " are using different %s checksums." % objname
                        else:
                            msg = "%d different %s checksums detected. Check server log for details." % (len(obj), objname)
                        self.sendBroadcastMessage(text = msg,
                                                  color = (1.0,0.0,0.0,1.0),
                                                  mtype = MTYPE_CHECKSUM_ERRORS)
                        acinfo("Different %s checksums detected:", objname)
                        for cs in obj:
                            acinfo("  Checksum %s used by players", cs)
                            for p in obj[cs]:
                                acinfo("    %s(%s)", self.get_player_name(p), p)
            else:
                wrong_guids = []
                found_guid_of_interest = (guid_of_interest is None)
                for cs in obj:
                    if cs != req:
                        wrong_guids.extend(list(map(lambda x: (x,cs), obj[cs])))
                        if guid_of_interest in obj[cs]:
                            found_guid_of_interest = True
                if len(wrong_guids) > 0 and found_guid_of_interest:
                    acinfo("Wrong %s checksums detected:", objname)
                    wrong_players = sorted(list(map(lambda x: self.get_player_name(x[0]), wrong_guids)))
                    for idx in range(len(wrong_guids)):
                        acinfo("  Checksum %s used by player %s(%s)", wrong_guids[idx][1], wrong_players[idx], wrong_guids[idx][0])
                    if len(wrong_guids) > 3:
                        msg = ", ".join(wrong_players[:2]) + ("and %d other players" % (len(wrong_players)-2))
                    elif len(wrong_guids) > 0:
                        msg = ", ".join(wrong_players)
                    self.sendBroadcastMessage(text="Wrong checksums detected: " + msg,
                                              color=(1.0,0.0,0.0,1.0),
                                              mtype=MTYPE_CHECKSUM_ERRORS)

        trackname = self.currentSession.trackname if not self.currentSession is None else None
        req_checksums = self.database.getRequiredChecksums(__sync=True)()
        if not trackname is None:
            perform_check(self, tracks, "track", req_checksums['tracks'].get(trackname, None))
        for car in cars:
            perform_check(self, cars[car], "car(%s)" % car, req_checksums['cars'].get(car, None))


    @acquire_lock
    def logout(self, guid):
        dd = self.allDrivers.byGuidAll(guid)
        for d in dd:
            d.ptracker_conn = None

    @acquire_lock
    def getGuid(self, driver):
        for d in self.allDrivers.drivers:
            if d.name == driver:
                return d.guid

    @acquire_lock
    def completeLapInfo(self, **lpt):
        d = self.allDrivers.byGuidActive(lpt['guid'])
        if d is None:
            acwarning("Cannot find guid %s in active drivers. Ignoring.")
        else:
            lpt['staticAssists'] = self.correctStaticAssists(lpt.get('staticAssists', {}))
            d.ptrackerLapInfo(lpt)
        return 1

    def lapStats(self, **kw):
        ref = self.database.lapStats(__sync=True, **kw)
        return ref()

    def sessionStats(self, **kw):
        ref = self.database.sessionStats(__sync=True, **kw)
        return {'sessions':ref()['sessions']}

    def lapDetails(self, **kw):
        ref = self.database.lapDetails(__sync=True, **kw)
        return {'lap_details':ref()}

    def setupDepositGet(self, **kw):
        kw["guid"] = dbGuidMapper.guid_new(kw["guid"])
        ref = self.database.setupDepositGet(__sync=True, **kw)
        return ref()

    def setupDepositSave(self, **kw):
        kw["guid"] = dbGuidMapper.guid_new(kw["guid"])
        self.database.setupDepositSave(__sync=True, **kw)()
        return {'ok': 1}

    def setupDepositRemove(self, **kw):
        kw["guid"] = dbGuidMapper.guid_new(kw["guid"])
        self.database.setupDepositRemove(__sync=True, **kw)()
        return {'ok': 1}

    @acquire_lock
    def getServerData(self, for_guid):
        d = self.allDrivers.byGuidActive(for_guid)
        ptrackerInstances = []
        messages = []
        if not d is None:
            messages = d.pending_messages
            d.pending_messages = []
        allguids = set()
        for pl in self.allDrivers.drivers:
            allguids.add(pl.guid)
        for guid in allguids:
            pl = self.allDrivers.byGuidAll(guid)[0]
            # get name from the players table, if it exists
            name = self.get_player_name(guid)
            team = self.get_team_name(guid)
            if team is None: team = ""
            if self.currentSession is None or self.currentSession.sessionType == stracker_udp_plugin.SESST_RACE:
                bestTime = pl.bestTime()
            else:
                bestTime = pl.bestTimeACValid()
            lapCount = pl.lapCount()
            lastTime = pl.lastTime()
            tyre = pl.tyre()
            r = {'guid':guid,'ptracker_conn':0,'name':name,'team':team,'tyre':tyre}
            r['best_time'] = bestTime
            r['lap_count'] = lapCount
            r['last_time'] = lastTime
            r['currLapInvalidated'] = pl.currLapInvalidated
            r['connected'] = pl.carId >= 0
            r['mr_rating'] = pl.minorating
            # check for connection
            if not pl.ptracker_conn is None:
                conn = pl.ptracker_conn
                r['ptracker_conn'] = conn.proto.getCapabilities()
                if for_guid in self.setups:
                    setup = self.setups[for_guid]
                    if setup.source_guid == guid:
                        r['setup'] = setup.setup
                        r['setup_car'] = setup.car
                        del self.setups[for_guid]
            ptrackerInstances.append(r)
        if not self.currentSession is None:
            session_state = self.currentSession.getSessionState()
        else:
            session_state = ACSession().getSessionState()
        if dbGuidMapper.guid_new(for_guid) in self.admin_guids and not self.adminpwd is None:
            session_state['adminpwd'] = self.adminpwd
        return {'ptracker_instances':ptrackerInstances, 'session_state': session_state, 'messages':messages}

    @acquire_lock
    def send_server_data(self, target_guid = None):
        acdebug("send_server_data(%s)", str(target_guid))
        for c in connections:
            if c.guid in self.newServerDataAvailable:
                c.serverDataChanged(immediate=(c.guid == target_guid))
        self.newServerDataAvailable = set()

    @acquire_lock
    def sendSetup(self, source_guid, target_guid, setup, setup_car):
        self.setups[target_guid] = SetupDescription(setup_car, setup, source_guid)
        d = self.allDrivers.byGuidActive(target_guid)
        if not d is None and d.ptracker_conn:
            self.newServerDataAvailable.add(target_guid)
            self.send_server_data(target_guid)
            return {'ok':1}
        return {'ok':0}

    @acquire_lock
    def sendBroadcastMessage(self, text, color, mtype):
        acinfo("Broadcast message: %s", text)
        for d in self.allDrivers.drivers:
            if d.carId >= 0:
                self.sendMessageToPlayer(d.guid, text, color, mtype, addToLog=False)

    @acquire_lock
    def sendMessageToPlayer(self, guid, text, color, mtype, addToLog=True):
        ptracker_guids = [d.guid for d in self.allDrivers.allDriversWithPtracker()]
        d = self.allDrivers.byGuidActive(guid)
        if guid in ptracker_guids:
            d.pending_messages.append({'text':text, 'color':color, 'type':mtype})
            self.newServerDataAvailable.add(guid)
            if addToLog:
                acinfo("Ptracker message to %s: %s", guid, text)
            self.send_server_data(guid)
        else:
            disabled = self.database.messagesDisabled(__sync=True, guid=dbGuidMapper.guid_new(guid), name=d.name)()
            if messageToString(mtype) in self.chat_msg_types and (not disabled or mtype == MTYPE_WELCOME):
                self.sendChatMessageToPlayer(guid, text)
                if addToLog:
                    acinfo("Chat message to %s: %s", guid, text)

    # --------------------------------------------------------------------------------
    # --------------------------------------------------------------------------------
    # Race classification
    # --------------------------------------------------------------------------------
    # --------------------------------------------------------------------------------

    def cmp_ply_final_position(self, d1, d2, isRace):
        """comparison of two players regarding race finish position"""
        # raceFinished may be different, player with raceFinished=True is before the other one
        # note that the other one may finish the race, and the positions might change (overlap)
        if isRace:
            if d1.raceFinished == d2.raceFinished:
                # if number of laps are different, then use lap count as criterium
                if d1.lapCount() > d2.lapCount():
                    return -1
                elif d2.lapCount() > d1.lapCount():
                    return 1
                # lap count is equal
                if not d1.raceFinished:
                    # if not raceFinished, compare the normalizedSplinePos
                    if d1.normalizedSplinePos > d2.normalizedSplinePos:
                        return -1
                    elif d2.normalizedSplinePos > d1.normalizedSplinePos:
                        return 1
                # if raceFinished, compare the total times
                if not d1.totalTime() in [0, None] and d2.totalTime() in [0, None]:
                    return -1
                if not d2.totalTime() in [0, None] and d1.totalTime() in [0, None]:
                    return 1
                if not d1.totalTime() is None and not d2.totalTime() is None:
                    if d1.totalTime() < d2.totalTime():
                        return -1
                    elif d2.totalTime() < d1.totalTime():
                        return 1
            elif d1.raceFinished and not d2.raceFinished:
                return -1
            elif d2.raceFinished and not d1.raceFinished:
                return 1
        else: # qualify or practice
            if not d1.bestTimeACValid() in [0, None] and d2.bestTimeACValid() in [0, None]:
                return -1
            elif not d2.bestTimeACValid() in [0, None] and d1.bestTimeACValid() in [0, None]:
                return 1
            elif not d1.bestTimeACValid() in [0, None] and not d2.bestTimeACValid() in [0, None]:
                if d1.bestTimeACValid() < d2.bestTimeACValid():
                    return -1
                elif d2.bestTimeACValid() < d1.bestTimeACValid():
                    return 1
        return 0

    @acquire_lock
    def calc_positions(self, quiet=False):
        players = self.allDrivers.filterForClassification()
        ply_sorted = sorted(players,
                            key=functools.cmp_to_key(functools.partial(self.cmp_ply_final_position,
                                                     isRace=self.currentSession.sessionType == stracker_udp_plugin.SESST_RACE)))
        if not quiet and len(players) > 0:
            acinfo("session positions:")
        positions = []
        for p in ply_sorted:
            raceFinished = p.raceFinished
            if raceFinished and self.currentSession.sessionType == stracker_udp_plugin.SESST_RACE:
                finishTime = p.totalTime()
            else:
                finishTime = None
            if self.currentSession.sessionType != stracker_udp_plugin.SESST_RACE:
                raceFinished = not p.bestTimeACValid() is None
            if not quiet: acinfo("  Player %s (raceFinished=%s, finishTime=%s)", p.name, raceFinished, finishTime)
            positions.append({
                'steamGuid':dbGuidMapper.guid_new(p.guid),
                'playerName':p.name,
                'playerIsAI':0,
                'raceFinished':raceFinished,
                'finishTime':finishTime,
            })
        return positions

    # -----------------------------------------------------------------------------
    # -----------------------------------------------------------------------------
    # UDP callbacks
    # -----------------------------------------------------------------------------
    # -----------------------------------------------------------------------------

    @acquire_lock
    def finishSession(self):
        if not self.currentSession is None:
            self.savePendingLaps(True)
            positions = self.calc_positions()
            if not len(positions) == 0:
                acinfo("finishing session")
            else:
                acdebug("finishing session")
            self.database.finishSession(__sync=True, positions=positions)()
            self.currentSession = None
            self.allDrivers.setupNewSession()
        else:
            acdebug("currentSession is None, no session to finish!")

    @acquire_lock
    def shutdown(self):
        try:
            self.finishSession()
        except:
            acerror("Traceback while finishing session in shutdown:")
            acerror(traceback.format_exc())

    @acquire_lock
    def feedUdpLap(self, carInfo):
        d = self.allDrivers.byCarId(carInfo.carId)
        if d is None:
            acwarning("LapCompleted event, but cannot find the car!")
            return
        self.check_for_ptracker_connection(d)
        d.lapCompletedEvent(carInfo, self.currentSession.apprSessionStartTime)
        if self.currentSession.numLaps > 0 and d.lapCount() == self.currentSession.numLaps or self.currentSession.raceFinished:
            d.raceFinished = True
            self.currentSession.raceFinished = True
            lapsBehind = self.currentSession.numLaps - d.lapCount()
            positions = self.calc_positions(quiet=True)
            for i,p in enumerate(positions):
                if p['steamGuid'] != dbGuidMapper.guid_new(d.guid):
                    continue
                if i < 3 and lapsBehind == 0:
                    i2msg = {0:"has won the race!", 1:"has finished second!", 2:"has finished third!"}
                    self.sendBroadcastMessage("%s %s" % (p['playerName'], i2msg[i]),
                                              (1.0,1.0,1.0,1.0),
                                              MTYPE_RACE_FINISHED)
                else:
                    if lapsBehind == 0:
                        self.sendMessageToPlayer(d.guid,
                                                 "You have finished the race at position %d." % (i+1),
                                                 (1.0,1.0,1.0,1.0),
                                                 MTYPE_RACE_FINISHED)
                    else:
                        self.sendMessageToPlayer(d.guid,
                                                 "You have finished the race %d laps behind." % lapsBehind,
                                                 (1.0,1.0,1.0,1.0),
                                                 MTYPE_RACE_FINISHED)
            self.performSessionManagement()

    @acquire_lock
    def feedUdpSession(self, sessionInfo):
        acdebug("new session")
        self.finishSession()
        self.currentSession = ACSession()
        self.currentSession.updateSessionInfo(sessionInfo)
        self.currentSession.updateTrackAndCarInfo(self.database.trackAndCarDetails(__sync=True)())
        self.sessionStartTime = time.time()
        session_types = {
            stracker_udp_plugin.SESST_PRACTICE:'Practice',
            stracker_udp_plugin.SESST_QUALIFY:'Qualify',
            stracker_udp_plugin.SESST_RACE:'Race',
            stracker_udp_plugin.SESST_DRAG:'Drag',
            stracker_udp_plugin.SESST_DRIFT:'Drift',
        }
        self.database.newSession(
            __sync=True,
            trackname=self.currentSession.trackname,
            carnames=self.currentSession.cars,
            sessionType=session_types.get(self.currentSession.sessionType, 'unknown'),
            multiplayer=True,
            numberOfLaps=(self.currentSession.numLaps or 0),
            duration=self.currentSession.sessionTime,
            server=config.config.STRACKER_CONFIG.server_name,
            sessionState=self.currentSession.getSessionState(),
        )()
        self.compare_checksums()
        self.ptClientsNewServerData()
        self.softSplitCalculator.setTrack(self.currentSession.trackname)
        self.nspPositionsChanged(self.softSplitCalculator.softSectorsTsp)
        livemap.resetSession(sessionInfo)
        groups = self.database.allgroups(__sync=True)()
        adminid = list(filter(lambda x: x['name'] == 'admins', groups))
        if len(adminid) > 0:
            adminid = adminid[0]['groupid']
            adminplayers = self.database.getPlayers(__sync=True, limit=None, group_id=adminid)()['players']
        else:
            adminplayers = []
        self.admin_guids = set([p['guid'] for p in adminplayers])

    @acquire_lock
    def feedUdpCarCollision(self, carCollision, c1, c2):
        if c1 is None or c2 is None:
            acwarning("collisions but none")
            return
        if config.config.MESSAGES.car_to_car_collision_msg:
            self.sendMessageToPlayer(
                c1.driverGuid,
                'Collision with %s [%.1f km/h]' % (c2.driverName, carCollision.impactSpeed),
                (0.5,1.0,0.5,1.0),
                MTYPE_COLLISION)
            self.sendMessageToPlayer(
                c2.driverGuid,
                'Collision with %s [%.1f km/h]' % (c1.driverName, carCollision.impactSpeed),
                (0.5,1.0,0.5,1.0),
                MTYPE_COLLISION)
        if config.config.LAP_VALID_CHECKS.invalidateOnCarCollisions:
            d1 = self.allDrivers.byGuidActive(c1.driverGuid)
            d2 = self.allDrivers.byGuidActive(c2.driverGuid)
            if d1 and d1.invalidateCurrentLap():
                self.newServerDataAvailable.add(c1.driverGuid)
                self.send_server_data(c1.driverGuid)
                acdebug("sent invalidate event")
            if d2 and d2.invalidateCurrentLap():
                self.newServerDataAvailable.add(c2.driverGuid)
                self.send_server_data(c2.driverGuid)
                acdebug("sent invalidate event")

    @acquire_lock
    def feedUdpEnvCollision(self, envCollision, c1):
        if c1 is None: return
        if config.config.LAP_VALID_CHECKS.invalidateOnEnvCollisions:
            d1 = self.allDrivers.byGuidActive(c1.driverGuid)
            if d1 and d1.invalidateCurrentLap():
                self.newServerDataAvailable.add(c1.driverGuid)
                self.send_server_data(c1.driverGuid)
                acdebug("sent invalidate event")

    @acquire_lock
    def newConnection(self, event):
        if config.config.STRACKER_CONFIG.guids_based_on_driver_names:
            dbGuidMapper.register_guid_mapping(event.driverGuid, event.driverName)
        d = ACDriver(event.driverGuid, self.saveLap)
        d.newConnectionEvent(event)
        d = self.allDrivers.addDriver(d)
        car_display = ""
        if len(self.currentSession.cars) > 1:
            uiname = self.currentSession.carsUi.get(d.car, d.car)
            car_display = "(" + uiname + ")"
        self.sendBroadcastMessage(text='Player %s entered the server %s.' % (d.name, car_display),
                                  color=(1.0,1.0,1.0,1.0),
                                  mtype=MTYPE_ENTER_LEAVE)
        self.check_for_ptracker_connection(d)
        self.updateOnline()
        if config.minorating_enabled():
            if not config.config.STRACKER_CONFIG.guids_based_on_driver_names:
                self.mr_query.query(guid=event.driverGuid)

    @acquire_lock
    def connectionLost(self, event):
        d = self.allDrivers.byCarId(event.carId)
        if not d is None:
            d.carId = -1
        else:
            acwarning("%s connectionLost callback, but cannot find the car?", event.driverGuid)
        self.sendBroadcastMessage(text='Player %s left the server.' % event.driverName,
                                  color=(1.0,1.0,1.0,1.0),
                                  mtype=MTYPE_ENTER_LEAVE)
        self.updateOnline()

    @acquire_lock
    def updateOnline(self):
        ad = self.allDrivers.allActive()
        self.database.setOnline(__sync=True, server_name=config.config.STRACKER_CONFIG.server_name, guids_online=[dbGuidMapper.guid_new(d.guid) for d in ad])()

    @acquire_lock
    def sendWelcomeMsg(self, guid):
        for i in range(3):
            line = getattr(config.config.WELCOME_MSG, "line%d"%(i+1))
            if line != '':
                self.sendMessageToPlayer(guid=guid,
                                         text=line % {'version':version},
                                         color=(1.0,1.0,1.0,1.0),
                                         mtype=MTYPE_WELCOME)
        d = self.allDrivers.byGuidActive(guid)
        if not d is None and d.ptracker_invalid_version:
            self.sendMessageToPlayer(guid=guid,
                                     text="Ptracker/stracker connection not available, because your ptracker version is too old.",
                                     color=(1.0,0.5,0.5,1.0),
                                     mtype=MTYPE_WELCOME)
        if not d is None and d.ptracker_conn is None:
            disabled = self.database.messagesDisabled(__sync=True, guid=dbGuidMapper.guid_new(guid), name=d.name)()
            msgEnabled = "disabled" if disabled else "enabled"
            self.sendMessageToPlayer(guid=guid, text="Messages are %s. Use the commands '/st messages off' or '/st messages on' to change the behaviour." % msgEnabled,
                                     color=(1.0,1.0,1.0,1.0), mtype=MTYPE_WELCOME)
        self.send_server_data(guid)

    @acquire_lock
    def serverRestarted(self):
        acinfo("Server seems to be restarted. Reloading server config file.")
        try:
            self.finishSession()
            # remove all drivers, they must reconnect now...
            self.allDrivers = AllDrivers()
            config.reread_acconfig([
                ('SERVER', 'UDP_PLUGIN_ADDRESS'),
                ('SERVER', 'UDP_PLUGIN_LOCAL_PORT'),
            ])
        except AssertionError:
            acerror("server has been restarted and UDP_PLUGIN_ADDRESS or UDP_PLUGIN_LOCAL_PORT have been changed")
            acerror("stracker needs to be restarted also.")
            self.database.shutdown()
            os._exit(1)

    @acquire_lock
    def udpDriverActive(self, carId, active):
        d = self.allDrivers.byCarId(carId)
        if not d is None:
            #if active != d.active:
            #    acdebug("Driver %s active flag has changed: %d", d.name, active)
            d.active = active

    @acquire_lock
    def udpRtUpdate(self, carId, carInfo):
        d = self.allDrivers.byCarId(carId)
        if not d is None:
            d.normalizedSplinePos = carInfo.normalizedSplinePos
            d.p3d = tuple(carInfo.worldPos)
            t = time.time()
            if t - self.lastRTPositionUpdate > 3 and not self.currentSession is None:
                self.lastRTPositionUpdate = t
                positions = self.calc_positions(quiet=True)
                np = []
                for i, p in enumerate(positions):
                    cd = self.allDrivers.byGuidActive(dbGuidMapper.guid_orig(p['steamGuid']))
                    if not cd is None:
                        np.append(cd)
                livemap.update_ranking(np)

    @acquire_lock
    def new_mr_rating(self, guid, rating):
        d = self.allDrivers.byGuidActive(guid)
        if not d is None and d.minorating != rating:
            d.minorating = rating
            for pd in self.allDrivers.allDriversWithPtracker():
                self.newServerDataAvailable.add(pd.guid)
            self.send_server_data()

    # -----------------------------------------------------------------------------
    # -----------------------------------------------------------------------------
    # other things
    # -----------------------------------------------------------------------------
    # -----------------------------------------------------------------------------

    @acquire_lock
    def performSessionManagement(self):
        if (config.config.SESSION_MANAGEMENT.race_over_strategy != config.config.ROS_NONE
                 and self.currentSession.sessionType == stracker_udp_plugin.SESST_RACE):
            drivers = self.allDrivers.allActive()
            allFinished = True
            oneFinished = False
            for d in drivers:
                if d.raceFinished or not d.active or d.lapCount() < self.currentSession.numLaps/2.-1:
                    pass
                else:
                    allFinished = False
                if d.raceFinished:
                    oneFinished = True
            if oneFinished and allFinished:
                self.raceFinished()

    @acquire_lock
    def correctStaticAssists(self, sa):
        if not self.currentSession is None:
            session_state = self.currentSession.getSessionState()
        else:
            session_state = ACSession().getSessionState()
        if 'tractionControl' in sa and not sa['tractionControl'] is None:
            if sa['tractionControl'] > session_state['tcAllowed']-1:
                sa['tractionControl'] = session_state['tcAllowed']-1
        if 'ABS' in sa and not sa['ABS'] is None:
            if sa['ABS'] > session_state['absAllowed']-1:
                sa['ABS'] = session_state['absAllowed']-1
        if 'stabilityControl' in sa and not sa['stabilityControl'] is None:
            if sa['stabilityControl'] > session_state['stabilityAllowed']:
                sa['stabilityControl'] = session_state['stabilityAllowed']
        if 'autoClutch' in sa and not sa['autoClutch'] is None:
            if sa['autoClutch'] > session_state['autoclutchAllowed']:
                sa['autoClutch'] = session_state['autoclutchAllowed']
        # tc, abs and tyre blankets override the settings of the static assists
        sa['tractionControl'] = session_state['tcAllowed']-1
        sa['ABS'] = session_state['absAllowed']-1
        sa['tyreBlankets'] = session_state['tyreBlanketsAllowed']
        sa['slipStream'] = 1 # no option in MP, I guess it is always 1
        return sa

    @acquire_lock
    def savePendingLaps(self, forceSaving):
        for d in self.allDrivers.drivers:
            d.merge_pt_lap(forceSaving)

    @acquire_lock
    def saveLap(self, driver, lap):
        class LH:
            pass
        lh = LH()
        lh.lapTime = lap.lapTime
        lh.sectorTimes = lap.sectorTimes
        lh.sampleTimes = [round((item.rcvTime - lap.lapTimeRcvTime)*1000 + lap.lapTime) for item in lap.lapHistory]
        lh.worldPositions = [item.worldPos for item in lap.lapHistory]
        lh.velocities = [item.velocity for item in lap.lapHistory]
        lh.normSplinePositions = [item.normalizedSplinePos for item in lap.lapHistory]
        lh.sectorsAreSoftSplits = True
        valid = lap.pt_valid
        acinfo("Saving lap from player with guid %s", driver.guid)
        try:
            if lh.sectorTimes[0] is None:
                softSectors = self.softSplitCalculator.calculate_sectors(lh)
                if len(softSectors) > 0:
                    lh.sectorTimes[:len(softSectors)] = softSectors
        except:
            acdebug("exception in calculate sectors (probably OK):")
            acdebug(traceback.format_exc())
        try:
            try:
                lc = fromLapHistory(lh.lapTime, lh.sectorTimes, lh.sampleTimes, lh.worldPositions, lh.velocities, lh.normSplinePositions, a2b=False)
            except AssertionError:
                lc = fromLapHistory(lh.lapTime, lh.sectorTimes, lh.sampleTimes, lh.worldPositions, lh.velocities, lh.normSplinePositions, a2b=True)
        except AssertionError:
            # something's wrong with the supplied data, we better delete it
            lh.sampleTimes = None
            lh.worldPositions = None
            lh.velocities = None
            lh.normSplinePositions = None
            if valid != 0: valid = 2
            acinfo('Setting lap to unknown bcause of suspicious lap binary blob')
            acdebug(traceback.format_exc())
        if not lap.cuts is None and lap.cuts > 0:
            acinfo("Setting lap to invalid because cuts > 0")
            valid = 0
        if valid == 2 and self.currentSession.penaltiesEnabled and not lap.cuts is None and lap.cuts == 0:
            acinfo('Setting lap to valid bcause of cuts = 0 and penaltiesEnabled')
            valid = 1
        if config.config.LAP_VALID_CHECKS.invalidateOnCarCollisions and lap.collCarCount > 0:
            valid = 0
            acinfo('Setting lap to invalid because of a car collision')
        if config.config.LAP_VALID_CHECKS.invalidateOnEnvCollisions and lap.collEnvCount > 0:
            valid = 0
            acinfo('Setting lap to invalid because of an env collision')
        if lap.lapCount == 1 and valid == 2:
            valid = 0
            acinfo("Setting first lap to invalid because it is probably an out-lap.")
        lap.valid = valid

        # fix temperatures as received by udp session
        dynamicAssists = copy.copy(lap.dynamicAssists)
        dynamicAssists['ambientTemp'] = self.currentSession.ambientTemp
        dynamicAssists['trackTemp'] = self.currentSession.roadTemp

        self.database.registerLap(__sync=True, trackChecksum=driver.track_checksum, carChecksum=driver.car_checksum, acVersion=driver.getPTACVersion(),
            steamGuid=dbGuidMapper.guid_new(driver.guid), playerName=driver.name, playerIsAI=0,
            lapHistory=lh, tyre=lap.tyre, lapCount=lap.lapCount, sessionTime=driver.totalTime(),
            fuelRatio=lap.fuelRatio, valid=valid, carname=driver.car, staticAssists=lap.staticAssists,
            dynamicAssists=dynamicAssists, maxSpeed=lap.maxSpeed,
            timeInPitLane=lap.timeInPitLane, timeInPit=lap.timeInPit,
            escKeyPressed=lap.escKeyPressed, teamName=driver.team,
            gripLevel=lap.gripLevel,
            collisionsCar=lap.collCarCount,
            collisionsEnv=lap.collEnvCount,
            cuts=lap.cuts,
            ballast=lap.ballast)()
        dbRes_percar = self.database.lapStats(
            __sync=True,
            mode='top',
            limit=[None,1],
            track=self.currentSession.trackname,
            artint=0,
            cars=[driver.car],
            ego_guid=dbGuidMapper.guid_new(driver.guid),
            valid=[1,2],
            minSessionStartTime=0)()
        dbRes_combo = self.database.lapStats(
            __sync=True,
            mode='top',
            limit=[None,1],
            track=self.currentSession.trackname,
            artint=0,
            cars=self.currentSession.cars,
            ego_guid=dbGuidMapper.guid_new(driver.guid),
            valid=[1,2],
            minSessionStartTime=0,
            group_by_guid=True)()
        self.check_pb_sb_callback(dbRes_percar, dbRes_combo, lapTime=lh.lapTime, guid=dbGuidMapper.guid_new(driver.guid), playerName=driver.name)
        self.ptClientsNewServerData()

    @acquire_lock
    def check_pb_sb_callback(self, r, r_combo, lapTime, guid, playerName):
        if not r is None and len(r['laps']) > 0:
            totalNumLaps = r['totalNumLaps']
            rank = r['laps'][0]['pos']
            lt = r['laps'][0]['lapTime']
            car = r['laps'][0]['uicar']
            acdebug("pb_sb_lt=%s, rank=%s, lapTime=%s, guid=%s, playerName=%s", lt, rank, lapTime, guid, playerName)
            if r['laps'][0]['guid'] != guid:
                acdebug("Unexpected guid in check_pb_sb_callback. Expected %s but got %s. This is due to the player does not yet have a lap for this query.", guid, r['laps'][0]['guid'])
                return
            comboTotalNumLaps = r_combo['totalNumLaps']
            comboLT = r_combo['laps'][0]['lapTime']
            comboRank = r_combo['laps'][0]['pos']

            if lt == lapTime:
                if self.currentSession is None:
                    car_display = car + " "
                    multi_car_combo = True
                elif len(self.currentSession.cars) > 1:
                    car_display = self.currentSession.car_shortener(car) + " "
                    multi_car_combo = True
                else:
                    car_display = ""
                    multi_car_combo = False
                if rank == 1:
                    bestLapMessage="SB %s by %s. %s(%s/%s)" % (format_time_ms(lapTime, False), playerName, car_display, rank, totalNumLaps)
                    bestLapColor = (1.0, 0.5, 1.0, 1.0)
                    self.softSplitCalculator.update()
                    self.nspPositionsChanged(self.softSplitCalculator.softSectorsTsp)
                else:
                    bestLapMessage="PB %s by %s. %s(%s/%s)" % (format_time_ms(lapTime, False), playerName, car_display, rank, totalNumLaps)
                    bestLapColor = (0.0, 1.0, 0.0, 1.0)
                if multi_car_combo and comboLT == lapTime:
                    bestLapMessage += " all [%s/%s]" % (comboRank, comboTotalNumLaps)
                bestLap = lapTime - r['laps'][0]['gapToBest']
                if bestLap == 0 or lapTime < config.config.MESSAGES.best_lap_time_broadcast_threshold/100.*bestLap:
                    self.sendBroadcastMessage(bestLapMessage, bestLapColor, MTYPE_BEST_LAP)
                else:
                    self.sendMessageToPlayer(guid, bestLapMessage, bestLapColor, MTYPE_BEST_LAP)

class STrackerServerHandler(BaseRequestHandler):
    def handle(self):
        if config.config.STRACKER_CONFIG.keep_alive_ptracker_conns:
            sock = self.request
            if 'windows' in platform.platform().lower():
                # enable keep alive, 30 seconds to start the keep alive stuff, 3 seconds interval
                # 10 probes are default for vista and later
                sock.ioctl(socket.SIO_KEEPALIVE_VALS, (1, 30000, 3000))
                acinfo("Enabled keep alive (30 seconds/3 seconds) for the connection (windows).")
            else:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPIDLE, 30)
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPINTVL, 3)
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPCNT, 10)
                acinfo("Enabled keep alive (30 seconds/3 seconds/10 tries) for the connection (linux).")
        p = ProtocolHandler(self.request)
        acdebug("new connection received.")
        self.guid = None
        self.lock = self.server.acmonitor.lock
        self.sdc_timer = None
        acdebug("adding connection")
        with self.lock:
            connections.append(self)
        self.proto = p
        self.ptsThreads = []
        ptsId = 0
        acdebug("starting server loop")
        while 1:
            try:
                rlist, wlist, xlist = select.select([self.request], [], [])
                with self.lock:
                    request = p.unpack_item()
                    if request[0] == ProtocolHandler.REQ_PROTO_START:
                        if request[1]['trackerid'] != 'ptracker client':
                            acinfo("connection try of a non-ptracker client. Ignoring.")
                            break
                        if request[1]['port'] != int(config.acconfig['SERVER']['TCP_PORT']):
                            acinfo("connection try of a ptracker client connected to different port (%d). Ignoring.", request[1]['port'])
                            break
                        ptcm = config.config.STRACKER_CONFIG.ptracker_connection_mode
                        if (ptcm == config.config.PTC_NONE or
                            (ptcm == config.config.PTC_NEWER and p.prot_version < p.PROT_VERSION and p.prot_version < 8)):
                                acinfo("connection try of a ptracker client not allowed to this server. Ignoring.")
                                break
                        p.ans_proto_start()
                    elif request[0] == ProtocolHandler.REQ_SIGNIN:
                        acinfo("signin %s", str(request[1]))
                        self.guid = request[1]['guid']
                        res = self.server.acmonitor.signin(**request[1])
                        p.ans_signin(ok=res)
                    elif request[0] == ProtocolHandler.REQ_SEND_LAP_INFO:
                        acinfo("send_lap_info guid %s", self.guid)
                        res = self.server.acmonitor.completeLapInfo(guid=self.guid, **request[1])
                        p.ans_send_lap_info(ok=res)
                    elif request[0] == ProtocolHandler.REQ_GET_GUID:
                        guid = self.server.acmonitor.getGuid(**request[1])
                        if guid is None:
                            guid = ''
                        p.ans_get_guid(guid=guid)
                    elif request[0] == ProtocolHandler.REQ_GET_LAP_STATS:
                        res = self.server.acmonitor.lapStats(**request[1])
                        p.ans_lap_stats(**res)
                    elif request[0] == ProtocolHandler.REQ_GET_SESSION_STATS:
                        res = self.server.acmonitor.sessionStats(**request[1])
                        p.ans_session_stats(**res)
                    elif request[0] == ProtocolHandler.REQ_GET_SERVER_DATA:
                        res = self.server.acmonitor.getServerData(self.guid)
                        p.ans_get_server_data(**res)
                    elif request[0] == ProtocolHandler.REQ_SEND_SETUP:
                        res = self.server.acmonitor.sendSetup(source_guid=self.guid,**request[1])
                        p.ans_send_setup(**res)
                    elif request[0] == ProtocolHandler.REQ_GET_LAP_DETAILS:
                        res = self.server.acmonitor.lapDetails(**request[1])
                        p.ans_lap_details(**res)
                    elif request[0] == ProtocolHandler.REQ_GET_LAP_DETAILS_WITH_HI:
                        res = self.server.acmonitor.lapDetails(withHistoryInfo=True, **request[1])
                        p.ans_lap_details_with_hi(**res)
                    elif request[0] == ProtocolHandler.REQ_DEPOSIT_GET:
                        res = self.server.acmonitor.setupDepositGet(guid=self.guid, **request[1])
                        p.ans_deposit_get(**res)
                    elif request[0] == ProtocolHandler.REQ_DEPOSIT_SAVE:
                        res = self.server.acmonitor.setupDepositSave(guid=self.guid, **request[1])
                        p.ans_deposit_save(**res)
                    elif request[0] == ProtocolHandler.REQ_DEPOSIT_REMOVE:
                        res = self.server.acmonitor.setupDepositRemove(guid=self.guid, **request[1])
                        p.ans_deposit_remove(**res)
                    elif request[0] == ProtocolHandler.REQ_ENABLE_SEND_COMPRESSION:
                        pass
                    elif request[0] == ProtocolHandler.REQ_GET_PTS_RESPONSE:
                        res = self.server.pts_server.serve_pts(**request[1])
                        p.ans_get_pts_response(content = res[0], ctype=res[1], cacheable=res[2])
                    elif request[0] == ProtocolHandler.REQ_POST_PTS_REQUEST:
                        ptsId = (ptsId + 1)%1073741824
                        p.ans_post_pts_request(ansId = ptsId)
                        t = Thread(target = self.handle_pts_response, args = (ptsId, request[1]))
                        t.start()
                        # don't know if we need to join, but let's assume no
                    else:
                        acerror("Unknown request %d. Ignoring.", request[0])
            except (KeyboardInterrupt, SystemExit):
                raise
            except socket.error as e:
                acinfo("Error with connection socket, finishing connection: %s", str(e))
                break
            except:
                acerror("Unexpected error, finishing connection of guid %s", self.guid)
                acerror("Traceback:")
                acerror(traceback.format_exc())
                break
        acdebug("Shutting down connection of guid %s ...", self.guid)
        self.proto.shutdown()

    def handle_pts_response(self, ptsId, kwargs):
        with self.lock:
            try:
                res = self.server.pts_server.serve_pts(**kwargs)
                self.proto.req_post_pts_reply(content=res[0], ctype=res[1], cacheable=res[2], ansId=ptsId)
            except (KeyboardInterrupt, SystemExit):
                raise
            except ConnectionError as e:
                acwarning("Connection error while notify that server data has changed (guid=%s); ignoring.", self.guid)
                acwarning("Message: %s", str(e))
            except:
                acerror("Unexpected error in handle_pts_response (ignoring):")
                acerror(traceback.format_exc())

    @acquire_lock
    def finish(self):
        self.cancel_timer()
        guid = getattr(self, 'guid', None)
        if not guid is None:
            acinfo("Driver with guid %s left the server", guid)
            self.server.acmonitor.logout(guid)
        try:
            connections.remove(self)
        except ValueError:
            # already removed (probably by server restart heuristics)
            pass

    @acquire_lock
    def serverDataChanged(self, immediate = False):
        if immediate:
            self.cancel_timer()
            self.serverDataChangedDelayed()
        elif self.sdc_timer is None:
            delay = random.randrange(300, 500)/100.
            self.sdc_timer = Timer(delay, self.serverDataChangedDelayed)
            self.sdc_timer.setDaemon(True)
            self.sdc_timer.start()

    @acquire_lock
    def cancel_timer(self):
        if not self.sdc_timer is None:
            self.sdc_timer.cancel()
            self.sdc_timer = None

    @acquire_lock
    def serverDataChangedDelayed(self):
        try:
            self.sdc_timer = None
            payload = self.server.acmonitor.getServerData(self.guid)
            self.proto.req_server_data_changed_with_payload(**payload)
        except (KeyboardInterrupt, SystemExit):
            raise
        except ConnectionError as e:
            acwarning("Connection error while notify that server data has changed (guid=%s); ignoring.", self.guid)
            acwarning("Message: %s", str(e))
        except:
            acerror("Unexpected error in serverDataChanged (ignoring):")
            acerror(traceback.format_exc())


def maintain_forever(dbBackend, udp_plugin):
    try:
        database = LapDatabase(lambda *args, **kw: None, LapDatabase.DB_MODE_NORMAL, dbBackend)
        lastCompressTime = time.time() - config.config.DB_COMPRESSION.interval*60 - 1
        while 1:
            t = time.time()
            work_performed = 0
            method = config.config.DB_COMPRESSION.mode
            if method != config.config.DBCOMPRESSION_HI_SAVE_ALL and t > lastCompressTime + config.config.DB_COMPRESSION.interval*60:
                if not config.config.DB_COMPRESSION.needs_empty_server or udp_plugin.empty():
                    acinfo("Compressing database ...")
                    work_performed += 1
                    lastCompressTime = t
                    if method == config.config.DBCOMPRESSION_HI_SAVE_FAST:
                        database.compressDB(COMPRESS_NULL_SLOW_BINARY_BLOBS, __sync=True)()
                    elif method == config.config.DBCOMPRESSION_HI_SAVE_NONE:
                        database.compressDB(COMPRESS_NULL_ALL_BINARY_BLOBS, __sync=True)()
                    acinfo("Compressing database done")
            if work_performed:
                time.sleep(1)
            else:
                time.sleep(300)
    except (KeyboardInterrupt, SystemExit):
        raise
    except:
        acerror("Unexpected exception from maintain_forever.")
        acerror(traceback.format_exc())

def onServerRestart(acmonitor):
    global connections
    for c in connections:
        try:
            c.request.close()
        except:
            pass
    connections = []
    acmonitor.serverRestarted()
    sessionManager.serverRestarted()

sessionManager = None
banlist = None
def onSessionInfo(session):
    if not sessionManager is None:
        sessionManager.sessionInfo(session)
    if session.currSessionIndex == session.sessionIndex:
        livemap.updateSession(session)

def onCommand(acmonitor, database, guid, command):
    if not guid is None:
        groups = database.getPlayers(__sync=True, limit=[1,1], include_groups=True)()['groups']
        adminids = set()
        for g in groups:
            if g['name'] == 'admins':
                adminids.add(g['groupid'])
        plyDetails = database.playerDetails(__sync=True, guid=dbGuidMapper.guid_new(guid))()
        check = len(adminids.intersection(set(plyDetails['memberOfGroup']))) > 0
    else:
        check = 1
    send_help = 1
    help_commands = []
    if check:
        if command.lower().startswith('session'):
            command = command[len('session'):].strip()
            if sessionManager.onCommand(command):
                acmonitor.sendChatMessageToPlayer(guid, "ok")
                send_help = 0
            else:
                acmonitor.sendChatMessageToPlayer(guid, "no")
        elif command.startswith("kickban"):
            command = command[len('kickban'):].strip()
            res = banlist.onCommand(command)
            if res:
                acmonitor.sendChatMessageToPlayer(guid, res)
                send_help = 0
            else:
                acmonitor.sendChatMessageToPlayer(guid, "no")
        elif command.startswith("whisper"):
            command = command[len("whisper"):].strip()
            ctype = command[:command.find(" ")]
            command = command[command.find(" "):].strip()
            to_guid = command[:command.find(" ")]
            if ctype == "id":
                pid = int(to_guid)
                d = acmonitor.allDrivers.byCarId(pid)
                to_guid = d.guid
                send_help = 0
            elif ctype == "guid":
                send_help = 0
            else:
                acmonitor.sendChatMessageToPlayer(guid, "no, malformed command")
            if send_help == 0:
                message = command[command.find(" "):].strip()
                acmonitor.sendChatMessageToPlayer(to_guid, message)
                acmonitor.sendChatMessageToPlayer(guid, "ok")
        elif command.startswith("broadcast"):
            send_help = 0
            message = command[len("broadcast"):].strip()
            acmonitor.sendChatMessageToPlayer(None, message, broadcast=True)
        elif command.startswith("servercmd"):
            send_help = 0
            command = command[len("servercmd"):].strip()
            acmonitor.sendChatMessageToPlayer(None, command, adminCmd=True)
        elif command == "":
            send_help = 1
        else:
            acmonitor.sendChatMessageToPlayer(guid, "unknown command")
            send_help = 1

        help_commands = ["/st session " + x for x in sessionManager.helpCommands()]
        help_commands.extend(["/st kickban " + x for x in banlist.helpCommands()])
        help_commands.extend(["/st whisper guid <guid> <message>"])
        help_commands.extend(["/st whisper id <carid> <message>"])
        help_commands.extend(["/st broadcast <message>"])
    else:
        acmonitor.sendChatMessageToPlayer(guid, "not in admins group")
        help_commands.extend(["add yourself to group 'admins' to get more commands"])
    if not guid is None:
        d = acmonitor.allDrivers.byGuidActive(guid)
        if not d is None and d.ptracker_conn is None:
            if command.startswith("messages"):
                command = command[len("messages"):].strip()
                if command == "on":
                    disabled = database.messagesDisabled(__sync=True, guid=dbGuidMapper.guid_new(guid), name=d.name, newVal=0)()
                    send_help = 0
                elif command == "off":
                    disabled = database.messagesDisabled(__sync=True, guid=dbGuidMapper.guid_new(guid), name=d.name, newVal=0x7fffffff)()
                    send_help = 0
                elif command == "status":
                    disabled = database.messagesDisabled(__sync=True, guid=dbGuidMapper.guid_new(guid), name=d.name)()
                    send_help = 0
            help_commands.extend(["/st messages [on|off|status]"])
            if send_help == 0:
                acdebug("%s", disabled)
                if disabled == 0:
                    acmonitor.sendChatMessageToPlayer(guid, "Messages are enabled")
                else:
                    acmonitor.sendChatMessageToPlayer(guid, "Messages are disabled")
    if send_help:
        acmonitor.sendChatMessageToPlayer(guid, "stracker command help:")
        for hc in help_commands:
            acmonitor.sendChatMessageToPlayer(guid, "  - " + hc)

def onChat(acmonitor, database, guid, message):
    d = acmonitor.allDrivers.byGuidActive(guid)
    if not d is None:
        name = d.name
    else:
        name = "<unknown>"
    database.recordChat(__sync=True, name=name, guid=dbGuidMapper.guid_new(guid), message=message, server=config.config.STRACKER_CONFIG.server_name)()
    livemap.update_chat(name, message)
    if config.config.SWEAR_FILTER.action != config.config.SF_NONE:
        if chatfilter.isbad(message):
            d.receivedBadWordWarnings += 1
            if d.receivedBadWordWarnings > config.config.SWEAR_FILTER.num_warnings:
                numDays = config.config.SWEAR_FILTER.ban_duration if config.config.SWEAR_FILTER.action == config.config.SF_BAN else 0
                banlist.onCommand("guid %s %d" % (d.guid, numDays))
            else:
                if config.config.SWEAR_FILTER.action == config.config.SF_BAN:
                    swear_action = "banned"
                else:
                    swear_action = "kicked"
                num_warnings_left = config.config.SWEAR_FILTER.num_warnings - d.receivedBadWordWarnings
                message = config.config.SWEAR_FILTER.warning % locals()
                acmonitor.sendChatMessageToPlayer(d.guid, message)

class DBGuidMapper:
    def __init__(self):
        self.map_orig_to_new = {}
        self.map_new_to_orig = {}

    def register_guid_mapping(self, guid_orig, guid_new):
        d = hashlib.md5(guid_new.encode('utf8')).digest() # 16 bytes
        d = struct.unpack('qq', d)
        d = abs(d[0] ^ d[1])
        guid_new = str(d)
        self.map_orig_to_new[guid_orig] = guid_new
        self.map_new_to_orig[guid_new] = guid_orig

    def guid_orig(self, guid_new):
        return self.map_new_to_orig.get(guid_new, guid_new)

    def guid_new(self, guid_orig):
        return self.map_orig_to_new.get(guid_orig, guid_orig)

dbGuidMapper = DBGuidMapper()

def run(dbBackend):
    acmonitor = None
    server = None
    serverIsActive = False
    try:
        database = LapDatabase(fromLapHistory, LapDatabase.DB_MODE_NORMAL, dbBackend)
        # get config items needed
        port = int(config.acconfig['SERVER']['UDP_PORT'])
        server_ip = config.config.STRACKER_CONFIG.ac_server_address
        # create the ACMonitor instance
        acmonitor = ACMonitor(database)
        # create the server for communicating with ptracker instances
        listening_port = config.config.STRACKER_CONFIG.listening_port
        server = ThreadingTCPServer(('0.0.0.0', listening_port), STrackerServerHandler, False)
        if platform.system().lower() != "windows":
            server.allow_reuse_address = True
        server.server_bind()
        server.server_activate()
        serverIsActive = True
        server.acmonitor = acmonitor
        http_server_base.db = database
        server.pts_server = http_server_base.StrackerPublicBase()
        server_thread = Thread(target=server.serve_forever)
        server_thread.daemon = True
        server_thread.start()

        # create the thread for the UDP communication
        udp_plugin = stracker_udp_plugin.StrackerUDPPlugin(callbackDecorator(lambda *args, **kw: [time.sleep(2), acmonitor.feedUdpSession(*args, **kw)]),
                                                           callbackDecorator(acmonitor.newConnection),
                                                           callbackDecorator(acmonitor.connectionLost),
                                                           callbackDecorator(acmonitor.feedUdpLap),
                                                           callbackDecorator(acmonitor.feedUdpCarCollision),
                                                           callbackDecorator(acmonitor.feedUdpEnvCollision),
                                                           callbackDecorator(acmonitor.sendWelcomeMsg),
                                                           callbackDecorator(lambda *args, **kw: [time.sleep(2), acmonitor.finishSession(*args, **kw)]),
                                                           callbackDecorator(lambda: onServerRestart(acmonitor)),
                                                           callbackDecorator(acmonitor.udpDriverActive),
                                                           callbackDecorator(onSessionInfo),
                                                           callbackDecorator(lambda *args, **kw: onCommand(acmonitor, database, *args, **kw)),
                                                           callbackDecorator(acmonitor.udpRtUpdate),
                                                           callbackDecorator(lambda *args, **kw: onChat(acmonitor, database, *args, **kw)),
                                                           )
        global sessionManager
        sessionManager = SessionManager(
            stracker_udp_plugin.synchronizer.udpRequest(udp_plugin.getSessionInfo),
            stracker_udp_plugin.synchronizer.udpRequest(udp_plugin.setSessionInfo),
            stracker_udp_plugin.synchronizer.udpRequest(udp_plugin.nextSession),
        )
        livemap.setCommandHandler(callbackDecorator(lambda *args, **kw: onCommand(acmonitor, database, None, *args, **kw)))
        # create the banlist handler
        global banlist
        banlist = BanListHandler(database, acmonitor, udp_plugin)
        # other stuff
        udp_plugin.acPlugin.broadcastChat("stracker has been restarted.")

        def sendChatMessageToPlayer(guid, message, broadcast=False, adminCmd=False):
            if broadcast:
                stracker_udp_plugin.synchronizer.udpRequest(udp_plugin.broadcastChatMessage)(message)
                livemap.update_chat('SERVER', message)
            elif adminCmd:
                stracker_udp_plugin.synchronizer.udpRequest(udp_plugin.adminCommand)(message)
            else:
                acdebug("sendChatMessageToPlayer %s %s", guid, message)
                if not guid is None:
                    stracker_udp_plugin.synchronizer.udpRequest(udp_plugin.sendChatMessageToGuid)(guid, message)
                else:
                    livemap.update_chat('SERVER', message)
        acmonitor.sendChatMessageToPlayer = sendChatMessageToPlayer

        acmonitor.nspPositionsChanged = udp_plugin.setNspPositionsOfInterest
        acmonitor.raceFinished = sessionManager.raceFinished
        udp_thread = Thread(target=udp_plugin.processServerPackets)
        udp_thread.daemon = True
        udp_thread.start()
        # create the compression thread
        comp_thread = Thread(target=functools.partial(maintain_forever, dbBackend=dbBackend, udp_plugin=udp_plugin))
        comp_thread.daemon = True
        comp_thread.start()
        # create the http server
        if config.config.HTTP_CONFIG.enabled:
            time.sleep(3) # seems like there is a race condition somewhere...
            acdebug("Starting http server")
            http_server.start(database, config.config.HTTP_CONFIG.listen_addr, config.config.HTTP_CONFIG.listen_port, banlist, udp_plugin)
        while 1:
            stracker_udp_plugin.synchronizer.processUdpCallbacks(1.0)
            acmonitor.savePendingLaps(False)
            if not udp_plugin.threadExc is None:
                raise udp_plugin.threadExc
    except (KeyboardInterrupt, SystemExit):
        acinfo("Keyboard interrupt")
    except RuntimeError:
        print("Runtime error. Check stracker.log and check your configuration files.")
        acerror(traceback.format_exc())
    except:
        acerror("Caught exception in server loop:")
        acerror(traceback.format_exc())
    else:
        acerror("Too many failed requests. Giving up.")
    finally:
        # make sure that the process is killed after half a minute to avoid endless loop in shutdown
        killme = Thread(target=lambda x: [time.sleep(30), os._exit(1)], daemon=True)
        if not acmonitor is None:
            acinfo("Shutting down acmonitor.")
            acmonitor.shutdown()
        if not server is None and serverIsActive:
            acinfo("Shutting down the server.")
            server.shutdown()
        if config.config.HTTP_CONFIG.enabled:
            acinfo("Shutting down http.")
            http_server.stop()
        acinfo("Shutting down pending ptracker connections.")
        for c in connections:
            try:
                c.request.close()
            except:
                pass
