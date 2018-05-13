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

import bisect
import collections
import hashlib
from math import sqrt, floor
import glob
import os
import os.path
import pickle
import traceback
import sys
import functools
import acsys
import struct
import re
import time
import ptracker_lib
from ptracker_lib import acsim
if not acsim.offline() and acsim.ac.getACPid() == os.getpid():
    import sys
    import os
    import os.path
    import platform
    if platform.architecture()[0] == "64bit":
        sysdir=os.path.dirname(__file__)+'/stdlib64'
    else:
        sysdir=os.path.dirname(__file__)+'/stdlib'
    sys.path.insert(0, sysdir)
    os.environ['PATH'] = os.environ['PATH'] + ";."

from ptracker_lib.helpers import *
from ptracker_lib import helpers
acinfo("------------------ sys path adapted from here!")
from ptracker_lib.database import LapDatabase,LapDatabaseProxy
from ptracker_lib.dbapsw import SqliteBackend
from ptracker_lib.dbgeneric import decompress
from ptracker_lib.dbremote import RemoteBackend, PtrackerClient
from ptracker_lib.lap_collector import LapCollector, fromLapHistory, jump_delta, compare_lc_items_race, compare_lc_items_quali
from ptracker_lib.config import config
from ptracker_lib.async_worker import Worker, threadCallDecorator
from ptracker_lib.expand_ac import expand_ac
from ptracker_lib import gui_helpers
from ptracker_lib.Gui import Gui
from ptracker_lib.ac_logparser import ACLogParser
from ptracker_lib.ac_ini_files import RaceIniFile, ControlsIniFile
from ptracker_lib.OptionTracker import SessionStateTracker, AssistanceTracker
from ptracker_lib.ps_protocol import ProtocolHandler
from ptracker_lib.message_types import *
from ptracker_lib import sound
from ptracker_lib.st_actions import *
from ptracker_lib import read_ui_data

# create dummy stracker environment
sys.path.append("apps/python/ptracker/stracker")
sys.path.append("apps/python/ptracker/stracker/externals")
import stracker_lib
import stracker_lib.logger
#ptracker_lib.helpers.LOG_LEVEL_INFO = stracker_lib.logger.LOG_LEVEL_INFO
#ptracker_lib.helpers.LOG_LEVEL_DEBUG = stracker_lib.logger.LOG_LEVEL_DEBUG
#ptracker_lib.helpers.LOG_LEVEL_DUMP = stracker_lib.logger.LOG_LEVEL_DUMP
stracker_lib.logger.acinfo = ptracker_lib.helpers.acinfo
stracker_lib.logger.acdebug = ptracker_lib.helpers.acdebug
stracker_lib.logger.acerror = ptracker_lib.helpers.acerror
stracker_lib.logger.acwarning = ptracker_lib.helpers.acwarning

from stracker_lib import config as stracker_config
stracker_config.create_default_config(stracker_lib.logger)
from stracker_lib import http_server_base

sim_info = acsim.add_watched_module("ptracker_lib.sim_info")

PRACTICE = 0
QUALIFY = 1
RACE = 2
HOTLAP = 3

session_strings = {
    0 : 'Practice',
    1 : 'Qualify',
    2 : 'Race',
    3 : 'Hotlap',
    4 : 'TimeAttack',
    5 : 'Drift',
    6 : 'Drag',
}

# class managing all the work
class PersonalHotlaps:

    def __init__(self, appWindow):
        helpers.restore_loggers(config.GLOBAL.log_verbosity)
        self.race_ini_file = RaceIniFile()
        self.controls_ini_file = ControlsIniFile()
        self.acLogParser = ACLogParser()
        self.lapCollectors = [LapCollector(self, 0, self.guid(), False)]
        self.init()
        self.track_keys = {}
        self.car_keys = {}
        self.comparison = None
        self.compareLap = None
        self.messages = []
        #self.history = []
        # load the database
        if acsim.offline():
            useMemoryDB = LapDatabase.DB_MODE_MEMORY
            #useMemoryDB = LapDatabase.DB_MODE_READONLY
        else:
            useMemoryDB = LapDatabase.DB_MODE_NORMAL
        dbdir = expand_ac('Assetto Corsa/plugins/ptracker')
        os.makedirs(dbdir, exist_ok=True)
        dbname = os.path.join(dbdir, 'ptracker.db3')
        if useMemoryDB == LapDatabase.DB_MODE_MEMORY:
            dbname = __file__ + ".db3"
            if os.path.exists(dbname):
                os.unlink(dbname)
        self.sqliteDB = LapDatabase(fromLapHistory, useMemoryDB, functools.partial(SqliteBackend, dbname=dbname, perform_backups=True))
        http_server_base.db = self.sqliteDB
        http_server_base.ptracker = self
        dbs = [self.sqliteDB]
        if acsim.ac.getServerIP() != '':
            self.ptClient = PtrackerClient(acsim.ac.getServerIP(), self.race_ini_file.serverPort(), self.guid())
            self.ptClientNumReconnectsReported = 0
            self.remoteDB = LapDatabase(fromLapHistory, useMemoryDB, functools.partial(RemoteBackend,
                                                                                       ptrackerClient=self.ptClient))
            dbs.append(self.remoteDB)
        else:
            self.ptClient = None
        self.dataBase = LapDatabaseProxy(dbs)
        self.bestLap = None
        self.deltaLap = None
        self.lapStats = None
        self.sesStats = None
        self.lapInfo = None
        self.setupDeposit = None
        self.setupDepositID = 0
        self.curr_set = (None, None)
        # actions
        self.stAdmin = False
        self.actKickBan = StActKickBanDriver(self)
        self.actSendSet = StActSendSetup(self)
        # deferred call results
        self.bestLapRef = lambda: None
        self.deltaLapRef = lambda: None
        self.bestSectorTimesRef = lambda: None
        self.bestLapWithSectorsRef = lambda: None
        self.lapStatRef = lambda: None
        self.sesStatRef = lambda: None
        self.lapInfoRef = lambda: None
        self.lapInfoForLcRef = lambda: None
        self.fuelConsumptionRef = lambda: None
        self.setupDepositGetRes = lambda: None
        self.connectionResult = lambda: None
        # initialize gui
        self.appWindow = appWindow
        self.gui = Gui(appWindow, self)
        self.time_elapsed_since_start = 0.0
        self.worker = Worker(True)
        self.mpDetection = None
        self.sessionStateTracker = SessionStateTracker()
        self.assistanceTracker = AssistanceTracker()
        self.serverData = {}
        self.fpsMode = config.GLOBAL.fps_mode
        self.numberOfTyresOutAllowed = 2
        self.syncUpdateCountdown = 0
        self.raceFinished = False
        self.specRaceFinished = False
        self.specBeforeLeader = False
        self.isLive = False

    def connectToStracker(self, *args):
        if acsim.ac.getServerIP() != '':
            self.connectionResult = self.remoteDB.reconnect()
            self.addMessage(text="Trying to connect to stracker ...",
                            color=(1.0,0.3,0.3,1.0),
                            mtype=MTYPE_LOCAL_FEEDBACK)
        else:
            self.addMessage(text="No stracker connection possible in single player.",
                            color=(1.0,0.3,0.3,1.0),
                            mtype=MTYPE_LOCAL_FEEDBACK)

    def guid(self):
        guid = self.acLogParser.guid()
        if guid is None:
            guid = self.race_ini_file.guid()
        if guid is None:
            acerror("Cannot get your steam guid. This is needed for some parts of ptracker. Will continue with a dummy guid, but some functionalities are broken.")
            guid = "<unknown>"
        return guid

    def init(self, reason = "first call"):
        if hasattr(self, 'results'):
            positions = []
            if self.lastSessionType[0] in [QUALIFY, PRACTICE, HOTLAP]:
                for ir in self.opponents_order:
                    k = list(self.results.keys())[ir]
                    guid,playerName,isAI=k
                    rf = not self.results[k][0] in [0, None]
                    positions.append({'steamGuid':guidhasher(guid), 'playerName':playerName, 'playerIsAI':isAI, 'raceFinished':rf, 'finishTime':None})
            else: # race
                for k in self.results:
                    guid,playerName,isAI=k
                    positions.append({'steamGuid':guidhasher(guid), 'playerName':playerName, 'playerIsAI':isAI, 'raceFinished':1, 'finishTime':self.results[k]})
                for i in self.opponents_order:
                    lc = self.lapCollectors[i]
                    guid,playerName,isAI = lc.playerId()
                    if not (guid,playerName,isAI) in self.results:
                        positions.append({'steamGuid':guidhasher(guid), 'playerName':playerName, 'playerIsAI':isAI, 'raceFinished':0, 'finishTime':None})
            acdebug("Finishing last session with final positions:")
            for i,p in enumerate(positions):
                s = ""
                try:
                    r = self.results[(p['steamGuid'], p['playerName'], p['playerIsAI'])]
                    s = ": " + str(r[0])
                except IndexError:
                    pass
                except KeyError:
                    pass
                except TypeError:
                    pass
                acdebug("  %d. %s%s [finished=%d]", i, p['playerName'], s, p['raceFinished'])
            if self.isLive:
                self.dataBase.finishSession(positions=positions)
        # init state variables
        acdump("reset lap, reason (%s)", reason)
        self.lapValid = 0
        self.invalidReason = reason
        self.escPressed = False
        self.lastSessionType = (-2, None, None)
        self.lastSessionTimeLeft = None
        self.lastNumLaps = None
        self.lastCarPosition = None
        self.lastCarVelocity = None
        self.splitComparison = (None, None, None, "Split")
        self.sectorComparison = (None, None, None, "Sector")
        self.pitLaneTime = None
        self.pitLaneTimeShowCountdown = 0.0
        self.bestSectors = []
        self.labelSetup = None
        for lc in self.lapCollectors:
            lc.init()
        self.order_consistent = True
        self.countdown_before_start = 1.
        self.lapTimeShowCountdown = 0.
        self.tspCheckpoint = None
        self.softSectorsTsp = None
        self.opponents_order = []
        self.trackPositions = {}
        # race results.
        #   The key is a tuple of (guid, playerName, isAI)
        #   The value is a list of [bestLapTime, comparison, lapCollectorIdx] in qualify or finishTime in race
        self.results = collections.OrderedDict()
        self.comparisonSector = (0,0)
        self.comparisonSectorCountdown = 0.0
        self.sessionBestTime = None
        self.sessionBestDriver = None
        self.lastSessionStart = time.time()
        self.currentFuelConsumption = None
        self.fuelPrediction = None
        self.additionalFuelNeeded = None
        self.fuelLeft = None
        trackname = self.getTrackName()
        self.a2b = False
        self.a2bOffset = 0
        try:
            jsf, mpng, mini = read_ui_data.track_files(trackname, ".")
            trackui = read_ui_data.read_ui_file(jsf, open(jsf, "rb"), {})
            self.a2b = "A2B" in trackui['tracks'][trackname]["tags"]
            if trackname == "ks_nordschleife-touristenfahrten":
                self.a2bOffset = -0.953
        except:
            acwarning("exception reading ui data of track %s:\n%s",trackname, traceback.format_exc())
        acinfo("Track information: a2b = %s, a2bOffset = %f", self.a2b, self.a2bOffset)

    def shutdown(self):
        acdebug("main.py: Shutting down.")
        self.init("shutdown")
        self.gui.shutdown()
        self.dataBase.shutdown()
        self.worker.shutdown()
        self.acLogParser.shutdown()
        if not self.ptClient is None:
            self.ptClient.shutdown()
        sound.shutdown()
        config.save()

    def invalidateCurrentLap(self, reason):
        if self.lapValid:
            acdebug("Invalidate current lap (reason %s)", reason)
            self.lapValid = 0
            self.invalidReason = reason

    def calcIDFinished(self, res):
        if not res[0] is None:
            acerror(res[0])
            myassert(0)
        res = res[1]
        name, idtype, checksum = res
        if idtype == 'TRACK':
            d = self.track_keys
        elif idtype == 'CAR':
            d = self.car_keys
        else:
            acerror("unknown idtype from calc checksum")
        d[name] = checksum
        acdebug("Checksum received for %s: %s", name, d[name])

    def getTrackName(self):
        res = acsim.ac.getTrackName(0)
        config = acsim.ac.getTrackConfiguration(0)
        if not config is None and not config == "" and len(config) > 0:
            res = res + "-" + config
        return res

    def checkSessionTypeChange(self):
        trackname = self.getTrackName()
        carname = acsim.ac.getCarName(0)
        stype = self.sim_info_obj.graphics.session
        currSessionType = (stype, trackname, carname)
        currSessionTimeLeft = self.sim_info_obj.graphics.sessionTimeLeft
        currNumLaps = acsim.ac.getCarState(0, acsys.CS.LapCount)
        needsInit = False
        if self.lastSessionType is None or self.lastSessionType != currSessionType:
            # re-initialize
            acdebug("Session type changed (%s)", session_strings[currSessionType[0]])
            needsInit = True
        elif not self.lastSessionTimeLeft is None and currSessionTimeLeft > self.lastSessionTimeLeft + 1000.:
            # re-initialize, sessionTimeLeft is decreasing
            acdebug("Session restarted (%s)", session_strings[currSessionType[0]])
            needsInit = True
        if needsInit:
            self.init("new session")
            self.sessionStateTracker.update_from_sim_info(self.sim_info_obj)
            self.lastSessionType = currSessionType
            acdebug("setting session type to %s", currSessionType)
            self.bestLap = None
            self.bestSectors = []
            self.queryBestTimes(trackname, carname)
            if not trackname in self.track_keys:
                self.track_keys[trackname] = "unknown"
                self.worker.apply_async(self.calculateID, ('content/tracks/%s' % trackname, trackname, 'TRACK'), {}, self.calcIDFinished)
            if not carname in self.car_keys:
                self.car_keys[carname] = "unknown"
                self.worker.apply_async(self.calculateID, ('content/cars/%s' % carname, carname, 'CAR'), {}, self.calcIDFinished)
            carnames = set([acsim.ac.getCarName(i) for i in range(acsim.ac.getCarsCount())])
            if self.isLive:
                self.dataBase.newSession(trackname=trackname,
                                         carnames=carnames,
                                         sessionType=session_strings.get(currSessionType[0], "unknown"),
                                         multiplayer=acsim.ac.getServerIP() != '',
                                         numberOfLaps=self.sim_info_obj.graphics.numberOfLaps,
                                         duration=currSessionTimeLeft,
                                         server=acsim.ac.getServerName(),
                                         sessionState=self.sessionStateTracker.staticSessionState())
            self.fuelConsumptionRef = self.sqliteDB.queryFuelConsumption(trackname=trackname, carname=acsim.ac.getCarName(0))
        self.lastSessionTimeLeft = currSessionTimeLeft
        self.lastNumLaps = currNumLaps

    @threadCallDecorator
    def calculateID(self, directory, name, id_type):
        fileList = []
        if id_type == "TRACK":
            ignore_file_list =  [
                "map.png",
                "map.ini",
                "audio_sources.ini",
                re.compile(r"cameras.*\.ini").match,
                "crew.ini",
                "lighting.ini",
                "outline.png",
                "preview.png",
            ]
            ignore_dir_list = [
                "ai",
                "sfx",
                "ui"
            ]
        else: # CAR
            ignore_file_list = []
            ignore_dir_list = [
                "sfx",
                "skins",
                "ui",
            ]
        def filter_by(flist, names):
            res = []
            for n in names:
                include = True
                for f in flist:
                    if f == n or (callable(f) and f(n)):
                        include = False
                        acinfo("excluding %s (by %s)", n, str(f))
                        break
                if include:
                    res.append(n)
            return res
        for root,subdirs,files in os.walk(directory, topdown=True):
            subdirs[:] = filter_by(ignore_dir_list, subdirs)
            for f in filter_by(ignore_file_list, files):
                fileList.append(os.path.join(root,f))
        checksum = hashlib.sha1()
        blocksize = 1024*1024
        bytesRead = {}
        fileList.sort()
        for f in fileList:
            sizeInBytes = os.path.getsize(f)
            stream = open(f, 'rb')
            # limit ourself to read 10 Megabytes from each file
            maxBytes = 10*blocksize
            if sizeInBytes < maxBytes:
                buf = stream.read(maxBytes)
                if not len(buf) == sizeInBytes:
                    acwarning("while reading file %s, unexpected data length %d",f,len(buf))
                checksum.update(buf)
                bytesRead[f] = len(buf)
            else:
                bytesPart = 5*blocksize
                buf = stream.read(bytesPart)
                checksum.update(buf)
                if not len(buf) == bytesPart:
                    acwarning("while reading beginning of file %s, unexpected data length %d",f,len(buf))
                bytesRead[f] = len(buf)
                stream.seek(-bytesPart, 2) # from end of file
                buf = stream.read(bytesPart)
                if not len(buf) == bytesPart:
                    acwarning("while reading end of file %s, unexpected data length %d",f,len(buf))
                buf += struct.pack("I", sizeInBytes)
                checksum.update(buf)
                bytesRead[f] += len(buf)
        info= []
        for f in fileList:
            info.append(f + "(%db)"%bytesRead[f])
        acinfo("Used following files for checksumming [%s]: %s", id_type, " ".join(info))
        res = (name, id_type, checksum.hexdigest())
        return res

    def queryBestTimes(self, trackname, carname):
        self.bestLapRef = self.dataBase.getBestLap(trackname=trackname, carname=carname, playerGuid=guidhasher(self.guid()))
        self.deltaLapRef = self.dataBase.getBestLap(trackname=trackname, carname=carname, playerGuid=guidhasher(self.guid()), assertHistoryInfo=True)
        self.bestSectorTimesRef = self.dataBase.getBestSectorTimes(trackname=trackname, carname=carname, playerGuid=guidhasher(self.guid()))
        self.bestLapWithSectorsRef = self.dataBase.getBestLapWithSectors(trackname=trackname, carname=None, assertValidSectors=self.sim_info_obj.static.sectorCount)

    def updateBestTimes(self):
        bestLap = self.bestLapRef()
        if not bestLap is None:
            self.bestLap = bestLap
            acdebug("Loaded best lap laptime=%d with n=%d samples.", self.bestLap.lastLapTime, len(self.bestLap.samples))
        deltaLap = self.deltaLapRef()
        if not deltaLap is None:
            self.deltaLap = deltaLap
            acdebug("Loaded delta lap laptime=%d with n=%d samples.", self.bestLap.lastLapTime, len(self.bestLap.samples))
        bestSectors = self.bestSectorTimesRef()
        if not bestSectors is None:
            self.bestSectors = bestSectors
            sectors = bestSectors[:min(len(bestSectors),self.sim_info_obj.static.sectorCount)]
            acdebug("Loaded best sectors: %s", sectors)
        bestLapWithSectors = self.bestLapWithSectorsRef()
        if not bestLapWithSectors is None:
            st = 0
            self.softSectorsTsp = []
            for s in range(self.sim_info_obj.static.sectorCount):
                st += bestLapWithSectors.sectorTimes[s]
                self.softSectorsTsp.append(bestLapWithSectors.tspAtT(st, True))
            acdump("calculated soft split spline positions: %s", self.softSectorsTsp)
            acdebug("Using softsplits when appropriate (in multiplayer and for opponents)")
        lapStats = self.lapStatRef()
        if not lapStats is None:
            self.lapStats = lapStats
            acdebug("got %d lap stat entries", len(self.lapStats['laps']))
        sesStats = self.sesStatRef()
        if not sesStats is None:
            self.sesStats = sesStats['sessions']
            acdebug("got %d ses stat entried", len(self.sesStats))
        lapInfo = self.lapInfoRef()
        if not lapInfo is None:
            self.lapInfo = lapInfo
            acdebug("got lap info entry")
        lapInfoForLcRef = self.lapInfoForLcRef()
        if not lapInfoForLcRef is None:
            self.lapInfo = lapInfoForLcRef
            self.setCompareLap(self.lapInfo)
        setupDeposit = self.setupDepositGetRes()
        if not setupDeposit is None:
            acinfo("Got result from setupDepositGet")
            self.setupDepositID += 1
            self.setupDeposit = setupDeposit
            setup = setupDeposit['selectedSet']['set']
            if not setup is None:
                # find base file name
                filename = None
                for s in setupDeposit['setups']:
                    if s['setupid'] == setupDeposit['selectedSet']['id']:
                        filename = "%s_%s" % (s['sender'], s['name'])
                        break
                if not filename is None:
                    self.worker.apply_async(self.saveSetup, args=(filename, setup), kw = {}, callback=lambda x: None)
        connResult = self.connectionResult()
        if not connResult is None:
            self.addMessage(text=connResult, color=(1.0,0.3,0.3,1.0), mtype=MTYPE_LOCAL_FEEDBACK)

    def queryLapStats(self, limit, remote, valid, minSessionStartTime, cars):
        if cars == "Cars of this session":
            cars = list(set(filter(lambda x: not x is None and type(x) == type("") and x != "", map(lambda x: x.carName, self.lapCollectors))))
        elif cars == "Ego car only":
            cars = [self.lapCollectors[0].carName]
        else:
            cars = [self.lapCollectors[0].carName]
        if remote and hasattr(self, 'remoteDB'):
            db = self.remoteDB
        else:
            db = self.sqliteDB
        self.lapStatRef = db.lapStats(mode='top',
                                        limit=limit,
                                        track=self.getTrackName(),
                                        artint=0,
                                        cars=cars,
                                        ego_guid=guidhasher(self.guid()),
                                        valid=valid,
                                        minSessionStartTime=minSessionStartTime)
        acdebug("queried %d lap stat entries", limit[1])

    def querySessionStats(self, remote, limit, tracks, sessionTypes, minSessionStartTime, minNumPlayers, multiplayer):
        if remote and hasattr(self, 'remoteDB'):
            db = self.remoteDB
        else:
            db = self.sqliteDB
        self.sesStatRef = db.sessionStats(limit=limit,
                                            tracks=tracks,
                                            sessionTypes=sessionTypes,
                                            minSessionStartTime=minSessionStartTime,
                                            minNumPlayers=minNumPlayers,
                                            multiplayer=multiplayer,
                                            ego_guid=guidhasher(self.guid()))
        acdebug("queried %d lap stat entries", limit[1])

    def queryLapInfo(self, remote, lapId):
        if remote and hasattr(self, 'remoteDB'):
            db = self.remoteDB
            if self.ptClient.capabilities() & ProtocolHandler.CAP_LAP_DETAILS == 0:
                db = None
        else:
            db = self.sqliteDB
        if not db is None:
            self.lapInfoRef = db.lapDetails(lapId)
            acdebug("queried details of lap %d", lapId)

    def queryLapInfoForLapComparison(self, lapId, remote=True):
        if remote:
            db = getattr(self, 'remoteDB', None)
        else:
            db = self.sqliteDB
        if not db is None:
            self.lapInfoForLcRef = db.lapDetails(lapId, withHistoryInfo=True)

    def querySetups(self, get_setupid = None, del_setupid = None, save_group_id = None):
        db = None
        if hasattr(self, 'remoteDB'):
            db = self.remoteDB
            if self.ptClient.capabilities() & ProtocolHandler.CAP_SETUP_DEPOSIT == 0:
                db = None
        if not db is None:
            car = self.lapCollectors[0].carName
            track = self.getTrackName()
            if not del_setupid is None:
                self.addMessage(text="Removing setup from deposit",
                                color=(1.0,1.0,1.0,1.0),
                                mtype=MTYPE_LOCAL_FEEDBACK)
                db.setupDepositRemove(self.guid, del_setupid)
            if not save_group_id is None:
                setup, name = self.acLogParser.getCurrentSetup(with_name = True)
                if not setup is None:
                    groupname = '?'
                    if not self.setupDeposit is None:
                        for g in self.setupDeposit['memberOfGroup']:
                            if g['group_id'] == save_group_id:
                                groupname = g['group_name']
                    self.addMessage(text="Storing setup %s in %s's deposit" % (name, groupname),
                                    color=(1.0,1.0,1.0,1.0),
                                    mtype=MTYPE_LOCAL_FEEDBACK)
                    db.setupDepositSave(self.guid, car, track, name, save_group_id, setup)
                else:
                    self.addMessage(text="No setup to store (you have to load/save a setup before)",
                                    color=(1.0,1.0,1.0,1.0),
                                    mtype=MTYPE_LOCAL_FEEDBACK)
            acinfo("setupDepositGet called")
            self.setupDepositGetRes = db.setupDepositGet(self.guid, car, track, get_setupid)

    def setCompareLap(self, lapInfo):
        if lapInfo is None:
            acinfo("resetting compare lap")
            self.compareLap = None
            self.addMessage(text="Comparison lap resetted",
                            color=(1.0,1.0,1.0,1.0),
                            mtype=MTYPE_LOCAL_FEEDBACK)
        else:
            try:
                sampleTimes, worldPositions, velocities, normSplinePositions = decompress(lapInfo['historyinfo'])
                sectorTimes = list(map(lambda x, li=lapInfo: li['sectortime%d'%x], range(10)))
                self.compareLap = fromLapHistory(lapInfo['laptime'], sectorTimes, sampleTimes, worldPositions, velocities, normSplinePositions, self.a2b)
                self.addMessage(text="Comparison lap set (%s)" % format_time(lapInfo['laptime'], False),
                                color=(1.0,1.0,1.0,1.0),
                                mtype=MTYPE_LOCAL_FEEDBACK)
                acinfo("compare lap set to id=%d" % lapInfo['lapid'])
            except:
                self.addMessage(text="Comparison lap not set (error)",
                                color=(1.0,0.3,0.3,1.0),
                                mtype=MTYPE_LOCAL_FEEDBACK)
                acwarning("compare lap not set (error)")
                acwarning(traceback.format_exc())
                self.compareLap = None

    def hasRemoteConnection(self):
        return hasattr(self, 'ptClient') and not self.ptClient is None and self.ptClient.isOnline()

    def isConnecting(self):
        return hasattr(self, 'ptClient') and not self.ptClient is None and self.ptClient.isConnecting()

    def hasStrackerLaptimes(self):
        return (self.hasRemoteConnection() and
                (self.ptClient.capabilities() & self.ptClient.proto.CAP_LAPCNT_BESTTIMES_AND_LASTTIMES) != 0)

    def addMessage(self, text, color, mtype = None):
        if mtype is None:
            acdebug("message %s has no type information, assuming unknown", str(m))
            mtype = MTYPE_UNKNOWN
        mkey = "enable_msg_" + messageToString(mtype)
        enabled = getattr(config.CONFIG_MESSAGE_BOARD, mkey, None)
        skey = "sound_file_" + messageToString(mtype)
        sound_file = getattr(config.CONFIG_MESSAGE_BOARD, skey, config.SOUND_FILE_NONE)
        if enabled is None:
            enabled = config.MSG_ENABLED_NO_SOUND
            acdebug("message %s has no configuration (config.CONFIG_MESSAGE_BOARD.%s), enabling by default.", str(m), mkey)
        if not enabled == config.MSG_DISABLED:
            current_time = time.time()
            newM = {
                'text' : text,
                'color' : color,
                'type' : mtype,
                'timestamp' : current_time,
            }
            self.messages.append(newM)
            # we keep no more than 500 messages in memory
            if len(self.messages) > 500:
                self.messages = self.messages[-500:]

            if sound_file != config.SOUND_FILE_NONE:
                sound.playsound(sound_file, config.CONFIG_MESSAGE_BOARD.sound_volume)
        else:
            acdebug("message %s is currently disabled", messageToString(mtype))
        acinfo("message (type=%20s): %s", messageToString(mtype), text)

    def checkCarJumps(self, dt):
        x,y,z = acsim.ac.getCarState(0, acsys.CS.WorldPosition)
        p = (x,y,z)
        vx,vy,vz = acsim.ac.getCarState(0, acsys.CS.Velocity)
        v = (vx,vy,vz)
        jump_detected = False
        max_delta = 0.
        if not self.lastCarPosition is None:
            lp = self.lastCarPosition
            lv = self.lastCarVelocity
            for i in range(3):
                d1 = abs( p[i] -  v[i]*dt - lp[i])
                d2 = abs(lp[i] + lv[i]*dt -  p[i])
                max_delta = max(max_delta, d1, d2)
                jump_detected = jump_detected or (
                     d1 > jump_delta and
                     d2 > jump_delta)
        if jump_detected:
            acdump("Jump (%.2f) detected p=(%.2f, %.2f, %.2f) v=(%.2f, %.2f, %.2f) lp=(%.2f, %.2f, %.2f) lv=(%.2f, %.2f, %.2f)", *((max_delta, ) +p + v + lp + lv))
            self.invalidateCurrentLap("jerky motion")
        self.lastCarPosition = p
        self.lastCarVelocity = v

    def updateRacePositions(self, dt):
        for lc in self.lapCollectors:
            sd = self.serverData.get(lc.server_guid, {})
            #acdebug("sd[update %s %s] = %s", lc.name, lc.server_guid, sd)
            lc.update(self.sim_info_obj, self.lapCollectors[0], self.softSectorsTsp, dt, sd)
        if self.lastSessionType[0] == RACE: # race
            self.raceFinished = any([lc.raceFinished for lc in self.lapCollectors])
            # compare to other cars
            validIndices = list(filter(lambda x, seq=self.lapCollectors: seq[x].active(), range(len(self.lapCollectors))))
            argsort = lambda seq: sorted(validIndices,
                                         key = functools.cmp_to_key(lambda x,y: compare_lc_items_race(seq[x], seq[y])))
            old_order = self.opponents_order[:]
            self.opponents_order = argsort(self.lapCollectors)
            for idx,i in enumerate(self.opponents_order):
                lc = self.lapCollectors[i]
                lc.leaderboardIndex = idx+1
                guid,name,isAI = lc.playerId()
                if lc.raceFinished:
                    if not (guid,name,isAI) in self.results:
                        finishTime = 0
                        if len(lc.samples) > 0:
                            finishTime = lc.samples[-1].totalTime
                        self.results[(guid,name,isAI)] = finishTime
            newComparisonSector = self.comparisonSector
            newComparisonSectorCountdown = self.comparisonSectorCountdown - dt
            newTspCheckpoint = self.tspCheckpoint
            for lc in self.lapCollectors:
                lc.showCountdown = max(0, lc.showCountdown - dt)
            self.syncUpdateCountdown = max(0, self.syncUpdateCountdown - dt)
            show_deltas = config.CONFIG_RACE.show_deltas
            if config.CONFIG_RACE.sync_live and self.syncUpdateCountdown > 0:
                show_deltas = 0
            if show_deltas:
                if config.CONFIG_RACE.delta_reference == config.DR_EGO:
                    delta_ref = acsim.ac.getFocusedCar()
                else:
                    delta_ref = self.opponents_order[0]
                cself = self.lapCollectors[delta_ref]
                cself.delta_self = 0
                tsp_self = cself.samples[-1].totalSplinePosition if len(cself.samples) > 0 else 0
                for i in validIndices:
                    if i == delta_ref:
                        self.lapCollectors[i].delta_self = 0.0
                        continue
                    cother = self.lapCollectors[i]
                    oTsp2 = 0.0
                    if len(cother.samples) > 1:
                        oTsp2 = cother.samples[-1].totalSplinePosition
                    oTsp1 = oTsp2
                    if len(cother.samples) > 2:
                        oTsp1 = cother.samples[-2].totalSplinePosition
                    lap_delta = tsp_self - oTsp2
                    lap_delta = floor(abs(lap_delta))*(-1 if lap_delta < 0 else +1)
                    if config.CONFIG_RACE.sync_live:
                        # update deltas live
                        self.syncUpdateCountdown = config.CONFIG_RACE.sync_interval
                        cother.showCountdown = config.CONFIG_RACE.sync_interval+1
                        mode = cother.LIVE if config.CONFIG_RACE.sync_interval <= 0 else cother.TRIGGERED
                        d = -cself.delta(cother)
                        cother.setDelta(d, mode, lap_delta)
                    else:
                        # update deltas on sector crossing
                        if (cself.sectorsUpdated or cself.lapsUpdated) and cself.currentSector() != self.comparisonSector:
                            # ego car crossed a sector, reset the show countdown and remember the "sector of interest"
                            newComparisonSector = cself.currentSector()
                            newComparisonSectorCountdown = config.CONFIG_RACE.show_splits_seconds
                            newTspCheckpoint = cself.samples[-1].totalSplinePosition
                            if cother.leaderboardIndex < cself.leaderboardIndex:
                                # other car is in front of us, show the delta
                                delta_t = -cself.delta(cother)
                                cother.setDelta(delta_t, cother.TRIGGERED, lap_delta)
                                cother.showCountdown = newComparisonSectorCountdown
                            else:
                                # other car is behind us, do not show delta until it crosses our sector
                                cother.showCountdown = 0.0
                        elif (not newTspCheckpoint is None and
                              oTsp1 < newTspCheckpoint <= oTsp2 and
                              cother.showCountdown <= 0.0 and
                              self.comparisonSectorCountdown > 0.0):
                            delta_t = -cself.delta(cother)
                            cother.setDelta(delta_t, cother.TRIGGERED, lap_delta)
                            cother.showCountdown = self.comparisonSectorCountdown
            self.comparisonSector = newComparisonSector
            self.comparisonSectorCountdown = newComparisonSectorCountdown
            self.tspCheckpoint = newTspCheckpoint
        elif self.lastSessionType[0] in [QUALIFY, PRACTICE, HOTLAP]: # qualify
            sguid,sname,sisAI = self.lapCollectors[0].playerId()
            if len(self.results) == 0:
                # assert that ego car has index 0
                self.results[(sguid,sname,sisAI)] = [None, None, 0] # (bestLapTime, comparison, lapCollectorIdx)
            cself = self.lapCollectors[acsim.ac.getFocusedCar()]
            cself.delta_self = 0
            validIndices = list(filter(lambda x, seq=self.lapCollectors: seq[x].active(), range(len(self.lapCollectors))))
            for ilc in validIndices:
                lc = self.lapCollectors[ilc]
                # caclulate the comparison and remember the best laps so far
                guid,name,isAI = lc.playerId()
                if not (guid,name,isAI) in self.results:
                    self.results[(guid,name,isAI)] = [None, None, ilc]
                else:
                    self.results[(guid,name,isAI)][2] = ilc # rejoins...
                if not lc.bestLapTime is None:
                    if self.results[(guid,name,isAI)][0] is None:
                        self.results[(guid,name,isAI)][0] = lc.bestLapTime
                    self.results[(guid,name,isAI)][0] = min(self.results[(guid,name,isAI)][0], lc.bestLapTime)
            ownResults = self.results[(sguid,sname,sisAI)]
            for k in self.results:
                self.results[k][1] = calc_comparison(self.results[k][0], ownResults[0], "Quali")
            idx = range(len(self.results))
            argsort = lambda seq: sorted(idx,
                                         key = lambda x: seq[list(seq.keys())[x]][0] or 1000000 )
            self.opponents_order = argsort(self.results)

    def updateTrackPositions(self):
        # map carId -> position on track with trackPositions[specId] ~ len(trackPositions)/2
        self.trackPositions = {}
        specId = acsim.ac.getFocusedCar()
        nsp = []
        for lc in self.lapCollectors:
            if lc.carId == specId:
                self.specRaceFinished = lc.raceFinished
            if lc.connected:
                nsp.append((lc.carId, acsim.ac.getCarState(lc.carId, acsys.CS.NormalizedSplinePosition)))
        nsp = sorted(nsp, key=lambda x: x[1])
        # find focused car
        idxFocused = 0
        for idx,c in enumerate(nsp):
            if c[0] == specId:
                idxFocused = idx
                break
        for idx,c in enumerate(nsp):
            self.trackPositions[c[0]] = (idx - idxFocused + len(nsp) + len(nsp)//2) % len(nsp)
        if len(self.opponents_order) > 0:
            nspSpec = acsim.ac.getCarState(specId, acsys.CS.NormalizedSplinePosition)
            nspLeader = acsim.ac.getCarState(self.opponents_order[0], acsys.CS.NormalizedSplinePosition)
            self.specBeforeLeader = nspSpec > nspLeader
        else:
            self.specBeforeLeader = False

    def checkNewLapsForSaving(self):
        track = self.getTrackName()
        acVersion = self.sim_info_obj.static.acVersion
        for lc in self.lapCollectors:
            if not lc.bestLapTime is None and (self.sessionBestTime is None or lc.bestLapTime < self.sessionBestTime):
                self.sessionBestTime = lc.bestLapTime
            if lc.abEntryDetected and lc.carId == 0:
                acdump("reset lap information")
                self.escPressed = False
                self.lapValid = 1
                self.invalidReason = ""
                self.assistanceTracker.resetDynamicAssists()
            if lc.newLapDetected and not lc.lastNewLapDetected:
                fuelRatio = -1
                lastTime = lc.lastLapTime
                timeOkToSave = True
                sectorTimes = lc.sectorTimes[:min(len(lc.sectorTimes), self.sim_info_obj.static.sectorCount)]
                lapstr = ("%s: Lap completed. Time %s. Sectors %s" % (lc.name, str(lastTime), str(sectorTimes)))
                guid,playerName,isAI = lc.playerId()
                car = lc.carName
                maxSpeed = lc.maxLapSpeed
                lc.maxLapSpeed = 0.0
                lapCount = lc.samples[-1].lapCount
                sessionTime = lc.samples[-1].totalTime
                if lc.carId == 0:
                    guid = self.guid()
                    tyre = self.sim_info_obj.graphics.tyreCompound
                    if self.sim_info_obj.static.maxFuel > 0:
                        fuelRatio = self.sim_info_obj.physics.fuel / self.sim_info_obj.static.maxFuel
                    valid = self.lapValid
                    if lastTime is None or lastTime <= 0:
                        self.lapValid = False
                    carid = self.car_keys[car]
                    trackid = self.track_keys[track]
                    if (not self.bestLap is None and not lastTime is None and lastTime > 0 and lastTime < self.bestLap.lastLapTime):
                        # pb achieved
                        if config.GLOBAL.auto_save_pb_setups:
                            setup = self.acLogParser.getCurrentSetup()
                            if not setup is None and valid:
                                filename = "%02d_%02d_%03d" % time_to_min_sec_msec_tuple(lastTime)
                                tc = acsim.ac.getTrackConfiguration(0)
                                if not tc is None and not tc == '':
                                    filename = "pt_a_" + tc + "_" + filename # prefix with track config name
                                else:
                                    filename = "pt_autosave_" + filename
                                self.worker.apply_async(self.saveSetup, args=(filename, setup), kw = {}, callback=lambda x: None)
                        if valid:
                            self.addMessage(text="Local PB: %s" % self.gui.format_time(lastTime, False),
                                            color=(1.0,1.0,1.0,1.0),
                                            mtype=MTYPE_LOCAL_PB)
                    staticAssists = self.assistanceTracker.staticAssists()
                    dynamicAssists = self.assistanceTracker.dynamicAssists()
                else:
                    tyre = "unknown"
                    valid = 2
                    carid = "unknown"
                    trackid = "unknown"
                    staticAssists = {}
                    dynamicAssists = {}
                try:
                    lapHistory = lc.toLapHistory()
                    timeOkToSave = lc.lastLapValid
                except AssertionError:
                    acdebug("%s Lap is invalid and will not be saved.", lc.name)
                    acdebug(traceback.format_exc())
                    valid = 2
                    lapHistory = lc.toLapHistory(withoutSamples=True)
                    timeOkToSave = False

                ballast = acsim.ac.getCarBallast(lc.carId)

                if timeOkToSave:
                    acdump("Saving last lap for driver %s with laptime=%d sectors=%s and n=%d samples", lc.name, lc.lastLapTime, str(lc.sectorTimes), len(lc.samples))
                    try:
                        if self.isLive:
                            self.dataBase.registerLap(trackChecksum=trackid,
                                                      carChecksum=carid,
                                                      acVersion=acVersion,
                                                      steamGuid=guidhasher(guid),
                                                      playerName=playerName,
                                                      playerIsAI=isAI,
                                                      lapHistory=lapHistory,
                                                      tyre=tyre,
                                                      lapCount=lapCount,
                                                      sessionTime=sessionTime,
                                                      fuelRatio=fuelRatio,
                                                      valid=valid,
                                                      carname=car,
                                                      staticAssists=staticAssists,
                                                      dynamicAssists=dynamicAssists,
                                                      maxSpeed=maxSpeed,
                                                      timeInPitLane=lc.lastTimeInPitLane,
                                                      timeInPit=lc.lastTimeInPit,
                                                      escKeyPressed=self.escPressed,
                                                      teamName=None,
                                                      gripLevel=self.sim_info_obj.graphics.surfaceGrip,
                                                      ballast=ballast,
                                                      collisionsCar=None,
                                                      collisionsEnv=None,
                                                      cuts=None)
                        lc.lastTimeInPitLane = 0
                        lc.lastTimeInPit = 0
                        acdebug("%s; Lap saved (%s).", lapstr, lc.name)
                    except:
                        acwarning("Could not save the lap. Continuing anyway. Python traceback:")
                        acerror(traceback.format_exc())
                else:
                    acdebug("%s; Lap not saved (plausibility check failed).", lapstr)
                    remoteDB = getattr(self, "remoteDB", None)
                    if lc.carId == 0 and not remoteDB is None and not lapHistory.lapTime in [None,0]:
                        acinfo("Notifying server about unknown ego lap")
                        if self.isLive:
                            remoteDB.registerLap(trackChecksum=trackid,
                                                 carChecksum=carid,
                                                 acVersion=acVersion,
                                                 steamGuid=guidhasher(guid),
                                                 playerName=playerName,
                                                 playerIsAI=isAI,
                                                 lapHistory=lapHistory,
                                                 tyre=tyre,
                                                 lapCount=lapCount,
                                                 sessionTime=sessionTime,
                                                 fuelRatio=fuelRatio,
                                                 valid=valid,
                                                 carname=car,
                                                 staticAssists=staticAssists,
                                                 dynamicAssists=dynamicAssists,
                                                 maxSpeed=maxSpeed,
                                                 timeInPitLane=lc.lastTimeInPitLane,
                                                 timeInPit=lc.lastTimeInPit,
                                                 escKeyPressed=self.escPressed,
                                                 teamName=None,
                                                 gripLevel=self.sim_info_obj.graphics.surfaceGrip,
                                                 ballast=ballast,
                                                 collisionsCar=None,
                                                 collisionsEnv=None,
                                                 cuts=None)
                        lc.lastTimeInPitLane = 0
                        lc.lastTimeInPit = 0
                if lc.carId == 0:
                    self.queryBestTimes(track,car)
                    self.fuelConsumptionRef = self.sqliteDB.queryFuelConsumption(trackname=track, carname=acsim.ac.getCarName(0))
                    acdump("reset lap information")
                    self.escPressed = False
                    self.lapValid = 1
                    self.invalidReason = ""
                    self.assistanceTracker.resetDynamicAssists()

    def updateSplitAndSectorDeltas(self):
        lc = self.lapCollectors[acsim.ac.getFocusedCar()]
        # display update
        if lc.newLapDetected:
            # for split display, we need the following two values
            bestSplit = None
            if not self.compareLap is None:
                bestSplit = self.compareLap.lastLapTime
            elif not self.bestLap is None:
                bestSplit = self.bestLap.lastLapTime
            self.splitComparison = calc_comparison(lc.lastLapTime,bestSplit, "Lap")
            if not lc.lastLapTime is None and lc.lastLapTime > 0:
                self.lapTimeShowCountdown = config.CONFIG_HOTLAP_LINE.show_laptime_duration
        if lc.sectorsUpdated:
            sectorCount = self.sim_info_obj.static.sectorCount
            sectorIndex = len(lc.sectorTimes)-1
            currSector = None
            bestSector = None
            if sectorIndex >= 0:
                currSector = lc.sectorTimes[-1]
                if not self.bestSectors is None and len(self.bestSectors) > sectorIndex:
                    bestSector = self.bestSectors[sectorIndex]
            self.sectorComparison = calc_comparison(currSector, bestSector, "Sector %d" % (sectorIndex+1))
            if sectorIndex != sectorCount - 1:
                currSplits = [None]*sectorCount
                s = lc.splitTimes(sectorCount)
                l = max(len(s),sectorCount)
                currSplits[:l] = s[:l]
                bestSplits = [None]*sectorCount
                if not self.compareLap is None:
                    s = self.compareLap.splitTimes(sectorCount)
                    l = max(len(s),sectorCount)
                    bestSplits[:l] = s[:l]
                elif not self.bestLap is None:
                    s = self.bestLap.splitTimes(sectorCount)
                    l = max(len(s),sectorCount)
                    bestSplits[:l] = s[:l]
                curr = None
                best = None
                if sectorIndex >= 0:
                    if len(bestSplits) > sectorIndex:
                        best = bestSplits[sectorIndex]
                    if len(currSplits) > sectorIndex:
                        curr = currSplits[sectorIndex]
                self.splitComparison = calc_comparison(curr, best, "Split %d" % (sectorIndex+1))

    def getLocalIdFromServerId(self, serverid):
        if serverid is None or serverid < 0:
            return None
        guid = self.guid()
        egoServerCarId = self.serverData.get(guid, {}).get('carid', None)
        if not egoServerCarId is None:
            if serverid == egoServerCarId:
                return 0
            if serverid < egoServerCarId:
                return serverid + 1
            return serverid
        return None

    def updateServerData(self):
        if self.ptClient is None:
            return
        if len(self.ptClient.connection_retry_timestamps) > self.ptClientNumReconnectsReported:
            self.ptClientNumReconnectsReported = len(self.ptClient.connection_retry_timestamps)
            self.addMessage(text="stracker reconnection occurred (%d)" % self.ptClientNumReconnectsReported,
                            color=(1.0,0.3,0.3,1.0),
                            mtype=MTYPE_LOCAL_FEEDBACK)
        while not self.ptClient.server_data.empty():
            sd = self.ptClient.server_data.get()
            activeGuids = set()
            for r in sd['ptracker_instances']:
                guid = r['guid']
                if type(guid) != str:
                    guid = str(guid)
                acdebug("guid: %s", guid)
                activeGuids.add(guid)
                if not guid in self.serverData:
                    self.serverData[guid] = {}
                self.serverData[guid]['name'] = r['name']
                self.serverData[guid]['team'] = r.get('team', "")
                self.serverData[guid]['tyre'] = r.get('tyre', "")
                self.serverData[guid]['ptracker_conn'] = r['ptracker_conn']
                self.serverData[guid]['mr_rating'] = r.get('mr_rating', None)
                self.serverData[guid]['server_carid'] = r.get('carid', None)
                if 'connected' in r:
                    self.serverData[guid]['connected'] = r['connected']
                local_carid = self.getLocalIdFromServerId(self.serverData[guid].get('server_carid', None))
                if local_carid is None:
                    found = False
                    #acdebug("SD[GUID %s] = %s", guid, self.serverData[guid])
                    for lc in self.lapCollectors:
                        if lc.name == r['name'] and lc.connected:
                            acdebug("found lap collector matching server guid (%s : %s)", lc.name, guid)
                            found = True
                            local_carid = lc.carId
                        elif lc.server_guid == guid and lc.name != r['name']:
                            lc.server_guid = None
                    if not found: acdebug("could not find matching lap collector for name %s, guid %s", r['name'], guid)
                self.serverData[guid]['local_carid'] = local_carid
                if not local_carid is None:
                    lc = self.lapCollectors[local_carid]
                    if lc.name != self.serverData[guid]['name']:
                        acwarning("name mismatch for localid=%d (serverid=%d): %s != %s", local_carid, serverData[guid]['server_carid'], lc.name, self.serverData[guid]['name'])
                    lc.server_guid = guid
                if 'setup' in r:
                    if not 'setup' in self.serverData[guid]:
                        self.addMessage(text="%s has sent you his setup" % r['name'],
                                        color=(1.0,1.0,1.0,1.0),
                                        mtype=MTYPE_SETUP_RECEIVED)
                    self.serverData[guid]['setup'] = r['setup']
                    self.serverData[guid]['setup_car'] = r['setup_car']
                tnow = time.time()
                if self.hasStrackerLaptimes() and tnow - self.lastSessionStart > 2.0:
                    bestLapTime = r['best_time']
                    lastLapTime = r['last_time']
                    lapCount = r['lap_count']
                    lapInvalidated = r.get('currLapInvalidated', False)
                    r['currLapInvalidated'] = False
                    acdebug("got lap times, searching for lc (%s %s %s)", bestLapTime, lastLapTime, lapCount)
                    found = False
                    for lc in self.lapCollectors:
                        if lc.server_guid == guid:
                            lc.bestLapTime = bestLapTime
                            lc.strackerLapCount = lapCount
                            if lapInvalidated:
                                if lc.carId == 0:
                                    self.invalidateCurrentLap("collision")
                            found = True
                    if not found:
                        acwarning("could not find matching lap collector for name %s", r['name'])
                else:
                    acdebug("ignoring lap times: reason %s %f", self.hasStrackerLaptimes(), tnow - self.lastSessionStart)
            for m in sd.get('messages'):
                self.addMessage(text=m['text'], color=m['color'], mtype=m['type'])
            allGuids = set(self.serverData.keys())
            for guid in allGuids.difference(activeGuids):
                del self.serverData[guid]
                acdebug("removing inactive guid %s from server data", guid)
            ptrackerTyresOut = sd.get('session_state', {}).get('ptrackerTyresOut', self.numberOfTyresOutAllowed)
            if ptrackerTyresOut != self.numberOfTyresOutAllowed:
                self.numberOfTyresOutAllowed = ptrackerTyresOut
                self.addMessage(text='Allowed tyres out is set to %d' % ptrackerTyresOut, color=(1.0,1.0,1.0,1.0), mtype=MTYPE_LOCAL_FEEDBACK)
            stAdmin = sd.get('session_state', {}).get('adminpwd', None)
            if not stAdmin is None:
                if self.stAdmin != stAdmin:
                    acdebug("player is server admin")
                    self.stAdmin = stAdmin
                    if type(stAdmin) == str and stAdmin != '':
                        acsim.ac.sendChatMessage("/admin %s" % stAdmin)
                        acdebug("logged in as admin")
            self.sessionStateTracker.update(sd)

    def localIdToGuid(self, carId):
        try:
            return self.lapCollectors[carId].server_guid
        except:
            acdebug(traceback.format_exc())
            return None

    def isStrackerAdmin(self):
        return not self.stAdmin in [None, False]

    def updatePitLaneTime(self):
        lc = self.lapCollectors[0]
        if lc.pitLaneEnterTimestamp is None:
            self.pitLaneTime = lc.lastTimeInPitLane
        else:
            self.pitLaneTime = lc.getTotalTime() - lc.pitLaneEnterTimestamp
            self.pitLaneTimeShowCountdown = config.CONFIG_HOTLAP_LINE.show_pitlanetime_duration

    def updateSetups(self):
        csetup, cname = self.acLogParser.getCurrentSetup(with_name=True)
        if not csetup is None and not cname is None and csetup != self.curr_set[0] or cname != self.curr_set[1]:
            self.curr_set = (csetup, cname)
            self.addMessage(text="Current set changed: %s" % cname, color=(1.0,1.0,1.0,1.0), mtype=MTYPE_LOCAL_FEEDBACK)

    def updateFuelConsumption(self):
        fcRes = self.fuelConsumptionRef()
        if not fcRes is None:
            self.fuelConsumptionRef = lambda: None
            if not fcRes is None:
                self.currentFuelConsumption = fcRes
        fuelLeft = self.sim_info_obj.physics.fuel / self.sim_info_obj.static.maxFuel
        if not self.currentFuelConsumption is None:
            self.fuelPrediction = fuelLeft / self.currentFuelConsumption
            if not self.sim_info_obj.graphics.numberOfLaps == 0:
                lapsToGo = self.sim_info_obj.graphics.numberOfLaps - self.lapCollectors[0].getTotalSplinePosition()
                self.additionalFuelNeeded = max(0, (lapsToGo - self.fuelPrediction)*self.currentFuelConsumption*self.sim_info_obj.static.maxFuel)
            else:
                self.additionalFuelNeeded = None
        else:
            self.fuelPrediction = None
            self.additionalFuelNeeded = None
        self.fuelLeft = self.sim_info_obj.physics.fuel


    def update(self, dt):
        # make sure we call all API functions relevant for the logic, so we have them logged, if enabled
        self.sim_info_obj = sim_info.SimInfo()
        self.fpsMode = config.GLOBAL.fps_mode
        if acsim.ac.isRecording():
            acsim.ac.getTrackName(0)
            acsim.ac.getTrackConfiguration(0)
            for carId in range(acsim.ac.getCarsCount()):
                acsim.ac.getDriverName(carId)
                acsim.ac.getCarLeaderboardPosition(carId)
                acsim.ac.getCarRealTimeLeaderboardPosition(carId)
                acsim.ac.getCarName(carId)
                acsim.ac.getCarState(carId, acsys.CS.Velocity)
                acsim.ac.getCarState(carId, acsys.CS.WorldPosition)
                acsim.ac.getCarState(carId, acsys.CS.NormalizedSplinePosition)
                acsim.ac.getCarState(carId, acsys.CS.LapTime)
                acsim.ac.getCarState(carId, acsys.CS.LapCount)
                acsim.ac.getCarState(carId, acsys.CS.LastLap)
                acsim.ac.getCurrentSplits(carId)
        #acdebug("current splits returned: car 0: %s; car 1: %s", acsim.ac.getCurrentSplits(0), acsim.ac.getCurrentSplits(1))
        # now start with update
        # status 0: off, status 1: replay, status 2: live, status 3: pause
        self.isLive = (self.sim_info_obj.graphics.status != 1)
        if self.sim_info_obj.graphics.status == 3: # esc is pressed, pause; ignore these frames...
            if not self.escPressed:
                acdebug("ESC key press detected")
            self.escPressed = True
            return
        if self.sim_info_obj.graphics.status == 1: # replay
            # adapt sim_info stuff for replay
            if (self.sim_info_obj.graphics.session == 0
              and self.sim_info_obj.graphics.numberOfLaps == 0
              and self.sim_info_obj.graphics.sessionTimeLeft == -1):
                # "fix" values not recorded in replay
                self.sim_info_obj.graphics.session = 2
                self.sim_info_obj.graphics.numberOfLaps = 100
        if acsim.ac.getCarsCount() < len(self.lapCollectors):
            self.lapCollectors = self.lapCollectors[:acsim.ac.getCarsCount()]
        while acsim.ac.getCarsCount() > len(self.lapCollectors):
            carId = len(self.lapCollectors)
            if carId == 0:
                isAi = False
                guid = self.guid()
            else:
                isAi = acsim.ac.getServerIP() == ''
                guid = None
            self.lapCollectors.append(LapCollector(self, carId, guid, isAi))
        self.time_elapsed_since_start += dt
        self.countdown_before_start = max(0, self.countdown_before_start - dt)
        self.lapTimeShowCountdown = max(0, self.lapTimeShowCountdown - dt)
        self.pitLaneTimeShowCountdown = max(0, self.pitLaneTimeShowCountdown - dt)
        if self.countdown_before_start > 0:
            return
        self.updateRacePositions(dt)
        self.updateTrackPositions()
        self.updateSplitAndSectorDeltas()
        self.updatePitLaneTime()
        self.updateFuelConsumption()
        # check if the order is consistent with the order received from spline positions
        # the leaderbord seems to have some severe glitches ... so this is disabled
        #self.check_order_consistency()
        # change spline positions to match the opponent's orders
        self.updateBestTimes()
        self.updateSetups()
        self.updateServerData()
        # check for session type change
        self.checkSessionTypeChange()
        # check for invalid car jumps (e.g., return to pits, restart, ...)
        self.checkCarJumps(dt)
        # check for car staying in pits
        if self.sim_info_obj.graphics.isInPit:
            self.invalidateCurrentLap("pit")
        # check if car is out of track
        if self.sim_info_obj.physics.numberOfTyresOut > self.numberOfTyresOutAllowed:
            self.invalidateCurrentLap("track limits")
        self.checkNewLapsForSaving()
        # compare current time to comparison base
        cself = self.lapCollectors[acsim.ac.getFocusedCar()]
        if not self.compareLap is None:
            self.comparison = cself.delta(self.compareLap)
        elif not self.deltaLap is None:
            self.comparison = cself.delta(self.deltaLap)
        else:
            self.comparison = None
        self.assistanceTracker.update(self.sim_info_obj)
        self.gui.update(dt)

    def render(self, dt):
        # make sure that messages are shown to the user, even if he sits in pits
        if self.lastSessionType is None:
            return
        self.gui.render(self.lastSessionType[0])

    def logFrame(self):
        if (not hasattr(self, "lastLogTimeStamp") or
            self.time_elapsed_since_start - self.lastLogTimeStamp > 5 or
            self.time_elapsed_since_start == self.lastLogTimeStamp):
            self.lastLogTimeStamp = self.time_elapsed_since_start
            return True
        return False

    def saveSetup(self, base_filename, setup, setup_car=None):
        try:
            stype, trackname, carname = self.lastSessionType
            if not setup_car is None:
                carname = setup_car
            dirname = expand_ac('Assetto Corsa', 'setups', carname, trackname)
            if not os.path.isdir(dirname):
                # hmm - assetto corsa uses a wrong trackname for the setups when track configurations are used
                trackname = acsim.ac.getTrackName(0)
                dirname = expand_ac('Assetto Corsa', 'setups', carname, trackname)

            name = re.sub('[^0-9a-zA-Z]+', '_', base_filename)
            save_path = os.path.join(dirname, name + ".ini")
            cnt = 0
            while os.path.exists(save_path):
                save_path = os.path.join(dirname, name + "-%d.ini" % cnt)
                cnt += 1
            open(save_path, "wb").write(setup)
            acinfo("Saved setup to %s.", save_path)
            p,basename = os.path.split(save_path)
            p,dirname =  os.path.split(p)
            self.addMessage(text="Setup saved to %s/%s" % (dirname,basename),
                            color=(1.0,1.0,1.0,1.0),
                            mtype=MTYPE_SETUP_SAVED)
            return save_path
        except:
            acerror("Error while saving setup:")
            acerror(traceback.format_exc())
            return None

    def cleanupAutosaveSetups(self):
        stype, trackname, carname = self.lastSessionType
        dirname = expand_ac('Assetto Corsa', 'setups', carname, trackname)
        if not os.path.isdir(dirname):
            # hmm - assetto corsa uses a wrong trackname for the setups when track configurations are used
            trackname = acsim.ac.getTrackName(0)
            dirname = expand_ac('Assetto Corsa', 'setups', carname, trackname)
        tc = acsim.ac.getTrackConfiguration(0)
        if not tc is None and not tc == '':
            filename_pref = "pt_a_" + tc + "_" # prefix with track config name
        else:
            filename_pref = "pt_autosave_"
        setups = glob.glob(os.path.join(dirname, filename_pref + "*.ini"))
        setup_map = {}
        for filepath in setups:
            filename = os.path.split(filepath)[1]
            acdebug("Considering setup %s", filename)
            M = re.match(filename_pref + r"([0-9]+)_([0-9]+)_([0-9]+)\.ini", filename)
            if not M is None:
                try:
                    laptime = int(M.group(1))*60000 + int(M.group(2))*1000 + int(M.group(3))
                    s = open(filepath, "rb").read()
                    if not s in setup_map:
                        setup_map[s] = {}
                    setup_map[s][laptime] = filepath
                except:
                    acwarning("Some error occured during processing cleanupAutosaveSetups. Trying to continue.")
                    acwarning(traceback.format_exc())
        cnt = 0
        for s in setup_map:
            lap_times = sorted(setup_map[s].keys())
            acinfo("keep setup %s" % setup_map[s][lap_times[0]])
            for lt in lap_times[1:]:
                acinfo("delete setup %s" % setup_map[s][lt])
                os.remove(setup_map[s][lt])
                cnt += 1
        self.addMessage(text="Kept %d setups, removed %d" % (len(setup_map), cnt),
                        color=(1.0,1.0,1.0,1.0),
                        mtype=MTYPE_LOCAL_FEEDBACK)
