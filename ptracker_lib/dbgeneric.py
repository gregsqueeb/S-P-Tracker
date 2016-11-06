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

################################################################################
# Never Eat Yellow Snow APPS - ptracker
#
# This file is part of the ptracker project. See ptracker.py for details.
################################################################################
import datetime
import pickle
import zlib
import struct
import functools
import re
import time
from ptracker_lib.helpers import *
from ptracker_lib.dbschemata import DbSchemata
import ptracker_lib
from ptracker_lib.constants import *

def prof(s, proft):
    t = time.time()
    acdebug("profiling %s: %.1f s", s, t-proft)
    return t

class DictCursor:
    def __init__(self, cols, description):
        colNames = list(map(lambda x: x[0], description))
        self.cols = cols
        self.colNames = {}
        for i,c in enumerate(colNames):
            self.colNames[c.lower()] = i

    def __getitem__(self, k):
        return self.cols[self.colNames[k.lower()]]

class Session:
    def __init__(self, **kw):
        for k in kw:
            setattr(self, k, kw[k])
        self.guid_cars_mapping = {}

def compress(sampleTimes, worldPositions, velocities, normSplinePositions, minDt = None):
    def compressTimeIntSignal(l):
        if len(l) == 0:
            l = [0]
        s = struct.pack('i', len(l))
        s += struct.pack('i', l[0])
        dl = tuple(map(lambda x: x[0]-x[1], zip(l[1:], l[0:-1])))
        s += struct.pack('i'*len(dl), *dl)
        return s
    def compressTimeFloatSignal(l):
        if len(l) == 0:
            l = [0.0]
        l_min = min(l)
        l_max = max(l)
        if l_max < l_min + 0.1:
            l_max = l_min + 0.1
        resolution = 2**30
        tl = tuple(map(lambda x: int((x-l_min)/(l_max-l_min)*resolution), l))
        return struct.pack('ffi', l_min, l_max, resolution) + compressTimeIntSignal(tl)
    def compress3dTimeFloatSignal(l):
        if len(l) == 0:
            l = [(0.0,0.0,0.0)]
        o = b""
        for i in range(3):
            tl = tuple(map(lambda x: x[i], l))
            o += compressTimeFloatSignal(tl)
        return o
    def take(array, idx):
        return list(map(lambda i, a=array: a[i], idx))
    if not minDt is None and len(sampleTimes) >= 2:
        idx = [0]
        for i in range(1,len(sampleTimes)-1):
            if sampleTimes[i] - sampleTimes[idx[-1]] >= minDt:
                idx.append(i)
        idx.append(len(sampleTimes)-1)
        sampleTimes = take(sampleTimes, idx)
        normSplinePositions = take(normSplinePositions, idx)
        worldPositions = take(worldPositions, idx)
        velocities = take(velocities, idx)
    o = compressTimeIntSignal(sampleTimes)
    o += compressTimeFloatSignal(normSplinePositions)
    o += compress3dTimeFloatSignal(worldPositions)
    o += compress3dTimeFloatSignal(velocities)
    return zlib.compress(o, 9)

def decompress(buffer):
    def decompressTimeIntSignal(o):
        n,l0 = struct.unpack('ii', o[:8])
        dl = struct.unpack('i'*(n-1), o[8:8+(n-1)*4])
        l = [l0]*n
        for i,d in enumerate(dl):
            l[i+1] = l[i]+d
        return o[8+(n-1)*4:], l
    def decompressTimeFloatSignal(o):
        l_min, l_max, resolution = struct.unpack('ffi', o[:12])
        o, tl = decompressTimeIntSignal(o[12:])
        l = list(map(lambda x: (x/resolution)*(l_max-l_min) + l_min, tl))
        return o, l
    def decompress3dTimeFloatSignal(o):
        unzipped = []
        for i in range(3):
            o, l = decompressTimeFloatSignal(o)
            unzipped.append(l)
        return o, list(zip(*unzipped))

    o = zlib.decompress(buffer)
    o, sampleTimes = decompressTimeIntSignal(o)
    o, normSplinePositions = decompressTimeFloatSignal(o)
    o, worldPositions = decompress3dTimeFloatSignal(o)
    o, velocities = decompress3dTimeFloatSignal(o)
    myassert(len(o) == 0)
    return (sampleTimes, worldPositions, velocities, normSplinePositions)

def valueListToDict(l, prefix, d):
    res = ""
    for i,v in enumerate(l):
        l = "%s_%d" % (prefix,i)
        d[l] = v
        res = res + "%s:%s" %(","*(i>0),l)
    return res

if 0:
  class CursorDebug:
    def __init__(self, cur):
        self.cur = cur

    def __getattr__(self, a):
        return getattr(self.cur, a)

    def execute(self, stmt, replacements = {}):
        def repl(M):
            v = M.group(1)
            r = replacements.get(v)
            if type(r) == str:
                return "'"+r+"'"
            elif r is None:
                return "NULL"
            else:
                return "%s" % r
        acdebug(re.subn(':([a-zA-Z_0-9]+)', repl, stmt)[0])
        import time
        t0 = time.time()
        res = self.cur.execute(stmt, replacements)
        t1 = time.time()
        acdebug("Time used: %.1f secs", t1-t0)
        return res
else:
    def CursorDebug(c):
        return c

class GenericBackend(DbSchemata):
    def __init__(self, lapHistoryFactory, db, perform_backups, force_version = None):
        self.currentSession = None
        DbSchemata.__init__(self, lapHistoryFactory, db, perform_backups, force_version)

    def getBestLap(self, trackname, carname, assertValidSectors=0, playerGuid=None, allowSoftSplits=False, assertHistoryInfo=False):
        with self.db:
            cur = self.db.cursor()

            stmt = ""
            if not carname is None:
                stmt += " AND Car=:carname"
            zero = 0
            invalid = self.invalidSplit
            for s in range(min(assertValidSectors, 10)):
                stmt += " AND SectorTime%d>:zero AND SectorTime%d<:invalid" % (
                    s, s)
            if assertValidSectors > 0:
                if not allowSoftSplits:
                    stmt += " AND SectorsAreSoftSplits=0"
                else:
                    stmt += " AND NOT SectorTime0=:invalid"
            if assertHistoryInfo:
                stmt += " AND LapId IN (SELECT LapId FROM LapBinBlob WHERE HistoryInfo NOTNULL)"
            if not playerGuid is None:
                stmt += " AND SteamGuid=:playerGuid"
            lapValid = 1
            stmt = """
                SELECT LapTime,
                       SectorTime0,SectorTime1,SectorTime2,
                       SectorTime3,SectorTime4,SectorTime5,
                       SectorTime6,SectorTime7,SectorTime8,
                       SectorTime9,
                       LapId
                FROM LapTimes
                WHERE (Track=:trackname AND Valid=:lapValid %s) ORDER BY LapTime ASC LIMIT 1;
            """ % stmt

            cur.execute(stmt, locals())

            row = cur.fetchone()
            if row is None:
                return None
            sectorTimes = list(map(int, row[1:11]))
            for i, s in enumerate(sectorTimes):
                if s >= self.invalidSplit:
                    sectorTimes[i] = None
            lapId = row[11]
            hi = cur.execute("SELECT HistoryInfo FROM LapBinBlob WHERE LapId=:lapId", locals()).fetchone()
            if not hi is None: hi = hi[0]
            try:
                sampleTimes, worldPositions, velocities, normSplinePositions = decompress(hi)
                res = self.lapHistoryFactory(lapTime=int(row[0]),
                                             sectorTimes=sectorTimes,
                                             sampleTimes=sampleTimes,
                                             worldPositions=worldPositions,
                                             velocities=velocities,
                                             normSplinePositions=normSplinePositions,
                                             a2b=False)
            except:
                try:
                    res = self.lapHistoryFactory(lapTime=int(row[0]),
                                                 sectorTimes=sectorTimes,
                                                 sampleTimes=sampleTimes,
                                                 worldPositions=worldPositions,
                                                 velocities=velocities,
                                                 normSplinePositions=normSplinePositions,
                                                 a2b=True)
                except:
                    res = self.lapHistoryFactory(lapTime=int(row[0]),
                                                 sectorTimes=sectorTimes,
                                                 sampleTimes=None,
                                                 worldPositions=None,
                                                 velocities=None,
                                                 normSplinePositions=None)
            return res

    def getSBandPB(self, trackname, carname, playerGuid, cursor = None):
        if cursor is None:
            with self.db:
                cur = self.db.cursor()
                return self.getSBandPB(trackname, carname, playerGuid, cur)
        else:
            cur = cursor
            cur.execute("""
                SELECT LapTime
                FROM LapTimes
                WHERE (Track=:trackname AND Car=:carname AND SteamGuid=:playerGuid AND Valid>=1) ORDER BY LapTime ASC LIMIT 1;
            """, locals())
            r = cur.fetchone()
            if r is None:
                pb = None
            else:
                pb = r[0]

            cur.execute("""
                SELECT LapTime
                FROM LapTimes
                WHERE (Track=:trackname AND Car=:carname AND Valid>=1) ORDER BY LapTime ASC LIMIT 1;
            """, locals())
            r = cur.fetchone()
            if r is None:
                sb = None
            else:
                sb = r[0]

            return {'pb':pb, 'sb':sb}

    def getBestSectorTimes(self, trackname, carname, playerGuid = None, cursor = None):
        if cursor is None:
            with self.db:
                c = self.db.cursor()
                return self.getBestSectorTimes(trackname, carname, playerGuid, c)
        else:
            cur = cursor
            res = []
            stmt = ""
            if not playerGuid is None:
                stmt += " AND SteamGuid=:playerGuid"
            lapValid = 1
            for i in range(10):
                cur.execute("""
                    SELECT SectorTime%d
                    FROM LapTimes
                    WHERE (Track=:trackname AND Car=:carname AND Valid=:lapValid %s)
                    ORDER BY SectorTime%d ASC LIMIT 1;
                """ % (i,stmt,i), locals())
                row = cur.fetchone()

                if row is None:
                    res.append(None)
                else:
                    res.append(int(row[0]+0.5))

            for i,r in enumerate(res):
                if not r is None and r >= self.invalidSplit:
                    res[i] = None

            return res

    def newSession(self, trackname, carnames, sessionType, multiplayer,
                   numberOfLaps, duration, server, sessionState):
        self.currentSession = Session(
                trackname=trackname,
                carnames=set(carnames),
                sessionType=sessionType,
                multiplayer=multiplayer,
                numberOfLaps=numberOfLaps,
                duration=duration,
                server=server,
                startTime=unixtime_now(),
                endTime=0,
                dbSessionId=None,
                penaltiesEnabled=sessionState.get('penaltiesEnabled',None),
                allowedTyresOut=sessionState.get('allowedTyresOut',None),
                tyreWearFactor=sessionState.get('tyreWearFactor',None),
                fuelRate=sessionState.get('fuelRate',None),
                damage=sessionState.get('damage',None),
        )

    def finishSession(self, positions):
        if self.currentSession is None:
            acinfo("currentsession is none, no session to finish.")
            return
        sessionId = self.currentSession.dbSessionId
        if sessionId is None:
            acdebug("session seems to be empty, ignoring")
            return
        with self.db:
            cur = self.db.cursor()
            for i,p in enumerate(positions):
                sessionPosition = i+1
                steamGuid = p['steamGuid']
                playerName = p['playerName']
                playerIsAI = p['playerIsAI']
                if steamGuid is None:
                    if playerIsAI:
                        steamGuid = "AI_"
                    else:
                        steamGuid = "unknown_guid_"
                    steamGuid += playerName
                carname = self.currentSession.guid_cars_mapping.get(steamGuid, None)
                if carname is None:
                    acinfo("Player %s (Position %d) has not been associated in this session. Ignoring." % (playerName, sessionPosition))
                    continue
                raceFinished = p['raceFinished']
                finishTime = p['finishTime']
                if not raceFinished:
                    sessionPosition += 1000
                cur.execute("""
                    UPDATE PlayerInSession SET
                        FinishPosition = :sessionPosition,
                        FinishPositionOrig = :sessionPosition,
                        RaceFinished = :raceFinished,
                        FinishTime = :finishTime
                    WHERE PlayerInSessionId IN (SELECT PlayerInSessionId FROM PlayerInSessionView
                                                WHERE SteamGuid=:steamGuid AND Car=:carname AND SessionId=:sessionId)
                """, locals())
            endTime = unixtime_now()
            cur.execute("""
                UPDATE Session SET
                    EndTimeDate = :endTime
                WHERE SessionId = :sessionId
            """, locals())
        self.currentSession = None

    def registerLap(self, trackChecksum, carChecksum, acVersion,
                    steamGuid, playerName, playerIsAI,
                    lapHistory, tyre, lapCount, sessionTime, fuelRatio, valid, carname,
                    staticAssists, dynamicAssists, maxSpeed, timeInPitLane, timeInPit, escKeyPressed,
                    teamName, gripLevel, collisionsCar, collisionsEnv, cuts, ballast):
        ptVersion = ptracker_lib.version
        with self.db:
            cur = self.db.cursor()
            trackname = self.currentSession.trackname
            # assert we have the combo in the database
            cur.execute("""
                INSERT INTO Tracks(Track)
                    SELECT :trackname
                    WHERE NOT EXISTS (SELECT 1 FROM Tracks WHERE Track=:trackname)
            """, locals())
            self.currentSession.carnames.add(carname)
            for cn in self.currentSession.carnames:
                cur.execute("""
                    INSERT INTO Cars(Car)
                        SELECT :cn
                        WHERE NOT EXISTS (SELECT 1 FROM Cars WHERE Car=:cn)
                """, locals())
            # assert we have the player in the database
            if steamGuid is None:
                if playerIsAI:
                    steamGuid = "AI_"
                else:
                    steamGuid = "unknown_guid_"
                steamGuid += playerName
            cur.execute("""
                INSERT INTO Players(SteamGuid,Name,ArtInt)
                    SELECT :steamGuid,:playerName,:playerIsAI
                    WHERE NOT EXISTS (SELECT 1 FROM Players WHERE SteamGuid=:steamGuid)
            """, locals())
            cur.execute("""
                UPDATE Players SET
                    Name = :playerName,
                    ArtInt = :playerIsAI
                WHERE SteamGuid=:steamGuid
            """, locals())
            # team
            if teamName is None or teamName.strip() == "":
                teamName = None
                teamId = None
            else:
                teamName = teamName.strip()
                cur.execute("""
                    INSERT INTO Teams(TeamName)
                    SELECT :teamName
                    WHERE NOT EXISTS (SELECT 1 FROM Teams WHERE TeamName=:teamName)
                """, locals())
                teamId = cur.execute("SELECT TeamId FROM Teams WHERE TeamName=:teamName", locals()).fetchone()[0]
            # assert we have the tyre in the database
            if tyre is None:
                tyre = "unknown"
            cur.execute("""
                INSERT INTO TyreCompounds(TyreCompound)
                    SELECT :tyre
                    WHERE NOT EXISTS (SELECT 1 FROM TyreCompounds WHERE TyreCompound=:tyre)
            """, locals())
            # assert we have the combo in the database
            carnames = self.currentSession.carnames
            # assert we have the session in the database
            myassert(not self.currentSession is None)
            if self.currentSession.dbSessionId is None:
                self.currentSession.comboId = self.getOrCreateComboId(cur, trackname, carnames)
                cur.execute("""
                    INSERT INTO Session(
                        TrackId,
                        SessionType,
                        Multiplayer,
                        NumberOfLaps,
                        Duration,
                        ServerIpPort,
                        StartTimeDate,
                        EndTimeDate,
                        PenaltiesEnabled,
                        AllowedTyresOut,
                        TyreWearFactor,
                        FuelRate,
                        Damage,
                        ComboId
                        )
                    SELECT
                        Tracks.TrackId,
                        :sessionType,
                        :multiplayer,
                        :numberOfLaps,
                        :duration,
                        :server,
                        :startTime,
                        :endTime,
                        :penaltiesEnabled,
                        :allowedTyresOut,
                        :tyreWearFactor,
                        :fuelRate,
                        :damage,
                        :comboId
                    FROM Tracks WHERE Track=:trackname
                """, self.currentSession.__dict__)
                self.currentSession.dbSessionId = cur.lastrowid
                myassert( not self.currentSession.dbSessionId is None)
            self.currentSession.guid_cars_mapping[steamGuid] = carname
            sessionId = self.currentSession.dbSessionId
            playerId = cur.execute("SELECT PlayerId FROM Players WHERE SteamGuid=:steamGuid", locals()).fetchone()[0]
            carId = cur.execute("SELECT CarId FROM Cars WHERE Car=:carname", locals()).fetchone()[0]
            absUsed = staticAssists.get('ABS', None)
            autoBlibUsed = staticAssists.get('autoBlib', None)
            autoBrakeUsed = staticAssists.get('autoBrake', None)
            autoClutchUsed = staticAssists.get('autoClutch', None)
            stabilityControlUsed = staticAssists.get('stabilityControl', None)
            tractionControlUsed = staticAssists.get('tractionControl', None)
            visualDamageUsed = staticAssists.get('visualDamage', None)
            slipStreamFactor = staticAssists.get('slipStream', None)
            tyreBlankets = staticAssists.get('tyreBlankets', None)
            inputMethod = staticAssists.get('input_method', None)
            shifter = staticAssists.get('shifter', None)
            maxAbsInLap = dynamicAssists.get('ABS', None)
            maxTcInLap = dynamicAssists.get('tractionControl', None)
            ambientTemp = dynamicAssists.get('ambientTemp', None)
            trackTemp = dynamicAssists.get('trackTemp', None)
            autoShifterUsed = dynamicAssists.get('autoShifter', None)
            idealLineUsed = dynamicAssists.get('idealLine', None)
            # assert we have the player associated with the session
            cur.execute("""
                INSERT INTO PlayerInSession(
                    SessionId,
                    PlayerId,
                    ACVersion,
                    PTVersion,
                    TrackChecksum,
                    CarChecksum,
                    CarId,
                    InputMethod,
                    Shifter,
                    TeamId
                    )
                SELECT :sessionId, :playerId, :acVersion, :ptVersion, :trackChecksum, :carChecksum, :carId,
                       :inputMethod, :shifter, :teamId
                WHERE NOT EXISTS (SELECT 1 FROM PlayerInSession WHERE
                                    SessionId=:sessionId AND PlayerID=:playerId AND CarID=:carId)
            """, locals())
            if len(staticAssists) > 0:
                # make sure we update the stracker db with the correct data, even if we have saved a lap
                # without these assist data already
                cur.execute("""
                    UPDATE PlayerInSession SET
                        InputMethod = :inputMethod,
                        Shifter = :shifter
                    WHERE SessionId=:sessionId AND PlayerID=:playerId AND CarID=:carId
                """, locals())
            # finally we can store the lap :-)
            sectorTimes = [int(s+0.5) if not s is None else None for s in lapHistory.sectorTimes[:]]
            while len(sectorTimes) < 10:
                sectorTimes.append(self.invalidSplit)
            for i,v in enumerate(sectorTimes):
                if v is None:
                    sectorTimes[i] = self.invalidSplit
            sectorsAreSoftSplits = lapHistory.sectorsAreSoftSplits
            if not lapHistory.sampleTimes is None:
                historyInfoCmp = compress(lapHistory.sampleTimes, lapHistory.worldPositions, lapHistory.velocities, lapHistory.normSplinePositions)
                acdebug("len(historyInfoCmp) = %d bytes" % len(historyInfoCmp))
            else:
                historyInfoCmp = None
            lapTime = lapHistory.lapTime
            st0, st1, st2, st3, st4, st5, st6, st7, st8, st9 = tuple(sectorTimes[:10])
            timestamp = unixtime_now()
            if gripLevel == 0.0: gripLevel = None
            if not maxSpeed is None:
                maxSpeed *= 3.6 # convert m/s to km/h
            cur.execute("""
                INSERT INTO Lap(
                    PlayerInSessionId,
                    TyreCompoundId,
                    LapCount,
                    SessionTime,
                    LapTime,
                    SectorTime0, SectorTime1, SectorTime2, SectorTime3, SectorTime4,
                    SectorTime5, SectorTime6, SectorTime7, SectorTime8, SectorTime9,
                    FuelRatio,
                    Valid,
                    SectorsAreSoftSplits,
                    MaxABS,
                    MaxTC,
                    TemperatureAmbient,
                    TemperatureTrack,
                    Timestamp,
                    AidABS,
                    AidTC,
                    AidAutoBlib,
                    AidAutoBrake,
                    AidAutoClutch,
                    AidAutoShift,
                    AidIdealLine,
                    AidStabilityControl,
                    AidSlipStream,
                    AidTyreBlankets,
                    MaxSpeed_KMH,
                    TimeInPitLane,
                    TimeInPit,
                    ESCPressed,
                    GripLevel,
                    CollisionsCar,
                    CollisionsEnv,
                    Cuts,
                    Ballast
                    )
                SELECT
                    tmp.PlayerInSessionId,
                    tmp.TyreCompoundId,
                    :lapCount,
                    :sessionTime,
                    :lapTime,
                    :st0, :st1, :st2, :st3, :st4, :st5, :st6, :st7, :st8, :st9,
                    :fuelRatio,
                    :valid,
                    :sectorsAreSoftSplits,
                    :maxAbsInLap,
                    :maxTcInLap,
                    :ambientTemp,
                    :trackTemp,
                    :timestamp,
                    :absUsed,
                    :tractionControlUsed,
                    :autoBlibUsed,
                    :autoBrakeUsed,
                    :autoClutchUsed,
                    :autoShifterUsed,
                    :idealLineUsed,
                    :stabilityControlUsed,
                    :slipStreamFactor,
                    :tyreBlankets,
                    :maxSpeed,
                    :timeInPitLane,
                    :timeInPit,
                    :escKeyPressed,
                    :gripLevel,
                    :collisionsCar,
                    :collisionsEnv,
                    :cuts,
                    :ballast
                FROM
                    ((SELECT PlayerInSessionId FROM PlayerInSessionView
                        WHERE SteamGuid=:steamGuid AND Car=:carname AND SessionId=:sessionId) AS tmp0
                     CROSS JOIN
                     (SELECT TyreCompoundId FROM TyreCompounds WHERE TyreCompound=:tyre) AS tmp1) AS tmp
            """, locals())
            lapId = cur.lastrowid
            if not historyInfoCmp is None:
                cur.execute("INSERT INTO LapBinBlob(LapId, HistoryInfo) VALUES(:lapId, :historyInfoCmp)", locals())

    def lapStats(self, mode, limit, track, artint, cars, ego_guid, valid, minSessionStartTime, tyre_list = None, server=None, group_by_guid=False, groups=[], withHistoryInfo=False, lapIdOnly=False, cursor=None):
        if cursor is None:
            with self.db:
                c = self.db.cursor()
                return self.lapStats( mode, limit, track, artint, cars, ego_guid, valid, minSessionStartTime, tyre_list, server, group_by_guid, groups, cursor=c)
        else:
            proft = time.time()
            startt = proft
            if track is None:
                acwarning("supplied track value is None. Ignoring query.")
                return
            limitOffset = limit[0]
            limitNum = limit[1]
            if limitOffset is None:
                pass
            elif limitOffset < 1:
                limitOffset = 0
            else:
                limitOffset -= 1 # position to index
            myassert(not "'" in track and all([not "'" in car for car in cars]))
            if mode in ['top', 'top-extended']:
                cur = CursorDebug(cursor)
                cur.execute("DROP TABLE IF EXISTS BestLapTimeHelper")
                carMapping = self.carMapping(cur)
                carValues = valueListToDict(cars, 'selected_cars', locals())
                lapValidVals = valueListToDict(valid, 'selected_valid', locals())
                try:
                    time_from = minSessionStartTime[0]
                    time_to = minSessionStartTime[1]
                except:
                    time_from = minSessionStartTime
                    time_to = None
                sess_time_from = None if time_from is None else time_from - 24*60*60
                sess_time_to = None if time_to is None else time_to + 24*60*60
                if time_to is None and time_from is None:
                    session_time_cond = ""
                    lap_timestamp_cond = ""
                elif time_to is None:
                    session_time_cond = "Session.StartTimeDate >= :sess_time_from AND"
                    lap_timestamp_cond = "Lap.Timestamp >= :time_from AND"
                elif time_from is None:
                    session_time_cond = "Session.StartTimeDate <= :sess_time_to AND"
                    lap_timestamp_cond = "Lap.Timestamp <= :time_to AND"
                else:
                    session_time_cond = "Session.StartTimeDate BETWEEN :sess_time_from AND :sess_time_to AND"
                    lap_timestamp_cond = "Lap.Timestamp BETWEEN :time_from AND :time_to AND"
                session_time_cond = ""
                if tyre_list is None:
                    tyre_compound_cond = ""
                else:
                    myassert(not "'" in " ".join(tyre_list))
                    tyre_compound_cond = "Lap.TyreCompoundId IN (SELECT TyreCompoundId FROM TyreCompounds WHERE "
                    tyre_compound_cond += " OR ".join(["LOWER(TyreCompound) LIKE '%"+t+"%'" for t in tyre_list])
                    tyre_compound_cond += ") AND"
                if server is None:
                    server_cond = ""
                else:
                    server_cond = "Session.ServerIpPort = :server AND"
                if len(groups) == 0 or 0 in groups:
                    groups_cond = ""
                else:
                    groups_cond = "PlayerInSession.PlayerId IN (SELECT PlayerId FROM GroupEntries WHERE GroupId IN ("
                    groups_cond += ",".join([str(int(g)) for g in groups])
                    groups_cond += ")) AND"
                if withHistoryInfo:
                    hi_cond = "LapBinBlob.HistoryInfo NOTNULL AND"
                    hi_tab = "JOIN LapBinBlob ON (LapBinBlob.LapId = Lap.LapId)"
                else:
                    hi_cond = ""
                    hi_tab = ""
                if group_by_guid in [True, 1]:
                    # group by player only
                    group_by_clause = "GROUP BY PlayerInSession.PlayerId"
                    # we cannot get the carid from BestLapTimeHelper (because it is not part of GROUP BY)
                    blth_carId = "PlayerInSession.PlayerId AS PlayerId"
                    matchLapTimesCond = "AND BestLapTimeHelper.PlayerId=LapTimes.PlayerId"
                    matchPISCond = "AND BestLapTimeHelper.PlayerId = PlayerInSession.PlayerId"
                elif group_by_guid == 2:
                    group_by_clause = "GROUP BY PlayerInSession.CarId"
                    blth_carId = "PlayerInSession.CarId AS CarId"
                    matchLapTimesCond = "AND BestLapTimeHelper.CarId=LapTimes.CarId"
                    matchPISCond = "AND BestLapTimeHelper.CarId=PlayerInSession.CarId"
                else:
                    # group by player/car
                    group_by_clause = "GROUP BY PlayerInSession.PlayerId,PlayerInSession.CarId"
                    # we can get the carid from BestLapTimeHelper
                    blth_carId = "PlayerInSession.PlayerId AS PlayerId , PlayerInSession.CarId AS CarId"
                    matchLapTimesCond = "AND BestLapTimeHelper.PlayerId=LapTimes.PlayerId AND BestLapTimeHelper.CarId=LapTimes.CarId"
                    matchPISCond = "AND BestLapTimeHelper.PlayerId = PlayerInSession.PlayerId AND BestLapTimeHelper.CarId=PlayerInSession.CarId"
                stmt_select_loi = """
                    SELECT PlayerInSession.PlayerInSessionId AS PlayerInSessionId FROM
                        PlayerInSession JOIN Session ON (PlayerInSession.SessionId=Session.SessionId)
                                        JOIN Players ON (Players.PlayerId=PlayerInSession.PlayerId)
                    WHERE Players.ArtInt=:artint AND
                          Session.TrackId IN (SELECT TrackId FROM Tracks WHERE Track=:track) AND
                          %(session_time_cond)s
                          %(server_cond)s
                          %(groups_cond)s
                          PlayerInSession.CarId IN (SELECT CarId FROM Cars WHERE Car IN (%(carValues)s))
                """ % locals()
                stmt = """
                    CREATE TEMP TABLE BestLapTimeHelper AS
                        SELECT MIN(LapTime) AS LapTime, COUNT(Lap.LapId) AS NumLaps, %(blth_carId)s
                        FROM Lap JOIN PlayerInSession ON (Lap.PlayerInSessionId=PlayerInSession.PlayerInSessionId)
                                 %(hi_tab)s
                        WHERE
                            Lap.Valid IN (%(lapValidVals)s)  AND
                            %(lap_timestamp_cond)s
                            %(tyre_compound_cond)s
                            %(hi_cond)s
                            Lap.PlayerInSessionId IN (%(stmt_select_loi)s)
                        %(group_by_clause)s
                """ % locals()
                cur.execute(stmt, locals())
                proft = prof("ls create bestlaptimehelper", proft)
                totalNumLaps = cur.execute("SELECT COUNT(*) FROM BestLapTimeHelper").fetchone()[0]
                if limitOffset is None:
                    a = cur.execute("""
                        SELECT COUNT(*) FROM BestLapTimeHelper
                        WHERE BestLapTimeHelper.LapTime < (SELECT MIN(LapTime) FROM BestLapTimeHelper
                                                           WHERE PlayerId IN (SELECT PlayerId FROM Players WHERE SteamGuid=:ego_guid))
                    """, locals()).fetchone()
                    limitOffset = max(0, a[0] - limitNum//2)
                if limitOffset > 0:
                    c = cur.execute("SELECT COUNT(*) FROM BestLapTimeHelper").fetchone()[0]
                    if c < limitOffset + limitNum:
                        limitOffset = max(0, c-limitNum)
                proft = prof("ls limits", proft)

                bestServerLaps = {}
                fastestLap = 0
                if not lapIdOnly:
                    # get best server laps
                    cur.execute("""
                        SELECT Car, MIN(LapTime) AS LapTime
                        FROM Lap NATURAL JOIN PlayerInSession NATURAL JOIN Session NATURAL JOIN Tracks NATURAL JOIN Cars NATURAL JOIN Players
                        WHERE Track=:track AND Car IN (%(carValues)s) AND ArtInt=:artint AND Valid IN (%(lapValidVals)s)
                        GROUP BY Car
                    """ % locals(), locals())

                    for a in cur.fetchall():
                        bestServerLaps[a[0]] = a[1]
                    if len(bestServerLaps) > 0:
                        fastestLap = min(bestServerLaps.values())
                    proft = prof("ls get best server laps", proft)

                cur.execute("""
                    WITH BestLapIds AS (
                              SELECT MAX(Lap.LapId) AS LapId, MAX(NumLaps) AS NumLaps FROM
                                   BestLapTimeHelper
									       JOIN Lap ON (BestLapTimeHelper.LapTime = Lap.LapTime)
									       JOIN PlayerInSession ON (Lap.PlayerInSessionId = PlayerInSession.PlayerInSessionId AND
                                                                    PlayerInSession.PlayerInSessionId IN (%(stmt_select_loi)s)
                                                                    %(matchPISCond)s)
                                   GROUP BY Lap.LapTime,PlayerInSession.PlayerId ,PlayerInSession.CarId
                                   ORDER BY Lap.LapTime
                                   LIMIT :limitNum
                                   OFFSET :limitOffset
                                  )
                    SELECT LapTimes.LapTime AS LapTime, Valid, Name, LapTimes.Car AS Car, LapTimes.Timestamp AS Timestamp,
                           TyreCompound, LapTimes.SteamGuid AS SteamGuid, LapTimes.LapId AS LapId,
                           PenaltiesEnabled, TyreWearFactor, FuelRate, Damage, AidABS,
                           AidAutoBlib, AidAutoBrake, AidAutoClutch, AidAutoShift,
                           AidIdealLine, AidStabilityControl, AidTractionControl,
                           AidSlipStream, AidTyreBlankets, InputMethod, InputShifter, LapMaxABS,
                           LapMaxTC, TemperatureAmbient, TemperatureTrack, MaxSpeed_KMH,
                           TimeInPitLane, TimeInPit, NumLaps,
                           SectorTime0, SectorTime1, SectorTime2, SectorTime3, SectorTime4, SectorTime5,
                           SectorTime6, SectorTime7, SectorTime8, SectorTime9
                    FROM BestLapIds JOIN LapTimes ON (BestLapIds.LapId = LapTimes.LapId)
                    ORDER BY LapTime
                """ % locals(),locals())
                proft = prof("ls lap stat table", proft)

                desc = cur.description
                ans = cur.fetchall()
                laps = []
                for i,cols in enumerate(ans):
                    a = DictCursor(cols, desc)
                    r = {}
                    r['pos'] = limitOffset + i + 1
                    r['lapTime'] = a["LapTime"]
                    r['valid'] = a["Valid"]
                    r['name'] = ['?',a["Name"]][not a["Name"] is None]
                    r['car'] = a["Car"]
                    r['uicar'] = carMapping.get(a["Car"], a["Car"])
                    r['timeStamp'] = a["Timestamp"]
                    r['tyre'] = a["TyreCompound"]
                    r['guid'] = a["SteamGuid"]
                    r['id'] = a["LapId"]
                    r['penalties'] = a["PenaltiesEnabled"]
                    r['tyreWear'] = a["TyreWearFactor"]
                    r['fuelRate'] = a["FuelRate"]
                    r['damage'] = a["Damage"]
                    r['abs'] = a["AidABS"]
                    r['autoBlib'] = a["AidAutoBlib"]
                    r['autoBrake'] = a["AidAutoBrake"]
                    r['autoClutch'] = a["AidAutoClutch"]
                    r['autoShift'] = a["AidAutoShift"]
                    r['idealLine'] = a["AidIdealLine"]
                    r['stabilityControl'] = a["AidStabilityControl"]
                    r['tractionControl'] = a["AidTractionControl"]
                    r['slipStream'] = a["AidSlipStream"]
                    r['tyreBlankets'] = a["AidTyreBlankets"]
                    r['inputMethod'] = a["InputMethod"]
                    r['inputShifter'] = a["InputShifter"]
                    r['maxABS'] = a["LapMaxABS"]
                    r['maxTC'] = a["LapMaxTC"]
                    r['tempAmbient'] = a["TemperatureAmbient"]
                    r['tempTrack'] = a["TemperatureTrack"]
                    r['maxSpeed'] = a["MaxSpeed_KMH"]
                    r['sectors'] = list(map(lambda x: (x>0 and x<self.invalidSplit and int(x+0.5)) or None, cols[-10:]))
                    r['bestServerLap'] = bestServerLaps.get(r['car'], None) == r['lapTime']
                    r['gapToBest'] = r['lapTime'] - fastestLap
                    r['timeInPitLane'] = a['TimeInPitLane']
                    r['timeInPit'] = a['TimeInPit']
                    r['numLaps'] = a['NumLaps']
                    laps.append(r)
                if mode == 'top-extended':
                    for r in laps:
                        lapId = r['id']
                        a = cur.execute("SELECT Cuts, CollisionsCar, CollisionsEnv, GripLevel, Ballast, TyreCompound FROM Lap NATURAL JOIN TyreCompounds WHERE LapId=:lapId", locals()).fetchone()
                        if a is None: a = [None]*6
                        r['cuts'] = a[0]
                        r['collcar'] = a[1]
                        r['collenv'] = a[2]
                        r['grip'] = a[3]
                        r['ballast'] = a[4]
                        r['tyres'] = a[5]
                    proft = prof("ls extended", proft)
                bestSectors = []
                if not lapIdOnly:
                    cur.execute("""
                        SELECT MIN(SectorTime0)
                             , MIN(SectorTime1)
                             , MIN(SectorTime2)
                             , MIN(SectorTime3)
                             , MIN(SectorTime4)
                             , MIN(SectorTime5)
                             , MIN(SectorTime6)
                             , MIN(SectorTime7)
                             , MIN(SectorTime8)
                             , MIN(SectorTime9)
                        FROM BestLapTimeHelper JOIN LapTimes ON
                            (BestLapTimeHelper.LapTime=LapTimes.LapTime
                             %(matchLapTimesCond)s)
                        LIMIT 1
                    """ % locals(), locals())
                    bestSectors = list(cur.fetchone())
                    for si in range(len(bestSectors)):
                        if bestSectors[si] == self.invalidSplit:
                            bestSectors[si] = None
                        elif not bestSectors[si] is None:
                            bestSectors[si] = int(bestSectors[si]+0.5)
                    proft = prof("ls best sectors", proft)
                prof("ls total", startt)
                return {'laps':laps, 'bestSectors':bestSectors, 'totalNumLaps':totalNumLaps}

    def getNameByGuid(self, guid):
        with self.db:
            cur = self.db.cursor()
            cur.execute("SELECT Name FROM Players WHERE SteamGuid = :guid", locals())
            a = cur.fetchone()
            if not a is None and len(a) == 1:
                return a[0]
            return None

    def sessionStats(self, limit, tracks, sessionTypes, ego_guid, minSessionStartTime, minNumPlayers, multiplayer, minNumLaps = None):
        with self.db:
            c = self.db.cursor()

            if type(sessionTypes) == type(""): sessionTypes = [sessionTypes]
            if sessionTypes is None:
                sessionTypeCond = ""
            else:
                sessionTypeValues = valueListToDict(sessionTypes, 'session_type_selected', locals())
                sessionTypeCond = "AND SessionType IN (%s)" % sessionTypeValues

            if type(tracks) == type(""): tracks = [tracks]
            if tracks is None:
                trackSelection = "SELECT TrackId FROM Tracks"
                trackWhereStmt = ""
            else:
                trackValues = valueListToDict(tracks, 'tracks_selected', locals())
                trackSelection = "SELECT TrackId FROM Tracks WHERE Track IN (%s)" % trackValues
                trackWhereStmt = "WHERE SelectedSessions.TrackId IN (SELECT * FROM SelectedTrackIds)"

            if multiplayer is None or (0 in multiplayer and 1 in multiplayer):
                mpCondition = ""
            else:
                mpValues = valueListToDict(multiplayer, 'mp_selected', locals())
                mpCondition = "AND Multiplayer IN (%s)" % mpValues

            if minNumLaps is None:
                nlCondition = ""
            else:
                nlCondition = "AND NumberOfLaps >= :minNumLaps"

            try:
                t1, t2 = tuple(minSessionStartTime)
            except (ValueError,TypeError):
                t1 = minSessionStartTime
                t2 = None
            if t1 is None: t1 = 0
            if t2 is None:
                tCond = "StartTimeDate > :t1"
            else:
                tCond = "StartTimeDate BETWEEN :t1 AND :t2"

            # the following is a session statistics select statement
            stmt = """
                WITH SelectedSessions AS (
                        SELECT * FROM Session
                        WHERE %(tCond)s
                              %(sessionTypeCond)s
                              %(mpCondition)s
                              %(nlCondition)s
                        ),
                    SelectedTrackIds AS (
                        %(trackSelection)s
                        )
                SELECT * FROM (
                    WITH PlayersWithPositions AS (
                        SELECT
                            PlayerInSession.PlayerId AS PlayerId,
                            SelectedSessions.SessionId AS SessionId,
                            PlayerInSession.FinishPosition AS FinishPosition,
                            PlayerInSession.RaceFinished AS RaceFinished,
                            Players.Name AS Name,
                            Players.SteamGuid AS SteamGuid
                        FROM SelectedSessions
                             JOIN PlayerInSession ON (PlayerInSession.SessionId = SelectedSessions.SessionId)
                             JOIN Players ON (PlayerInSession.PlayerId = Players.PlayerId)
                        %(trackWhereStmt)s
                        )
                    SELECT SelectedSessions.SessionId AS SessionId,
                           SelectedSessions.SessionType,
                           Pos1.Name AS Pos1,
                           Pos2.Name AS Pos2,
                           Pos3.Name AS Pos3,
                           SelfPos.FinishPosition AS SelfPosition,
                           NumPlayers.N AS NumPlayers,
                           SelectedSessions.StartTimeDate AS StartTimeDate,
                           SelectedSessions.Multiplayer,
                           Tracks.Track
                    FROM SelectedSessions JOIN Tracks ON (SelectedSessions.TrackId = Tracks.TrackId) LEFT JOIN
                        (SELECT Name, SessionId FROM PlayersWithPositions WHERE FinishPosition = 1) AS Pos1 ON (SelectedSessions.SessionId = Pos1.SessionId) LEFT JOIN
                        (SELECT Name, SessionId FROM PlayersWithPositions WHERE FinishPosition = 2) AS Pos2 ON (SelectedSessions.SessionId = Pos2.SessionId) LEFT JOIN
                        (SELECT Name, SessionId FROM PlayersWithPositions WHERE FinishPosition = 3) AS Pos3 ON (SelectedSessions.SessionId = Pos3.SessionId) LEFT JOIN
                        (SELECT FinishPosition, SessionId
                         FROM PlayersWithPositions
                         WHERE SteamGuid = :ego_guid AND FinishPosition < 1000) AS SelfPos ON (SelectedSessions.SessionId = SelfPos.SessionId) LEFT JOIN
                        (SELECT COUNT(*) AS N, SessionId
                         FROM PlayersWithPositions GROUP BY SessionId) AS NumPlayers ON (SelectedSessions.SessionId = NumPlayers.SessionId)
                    ) AS Result
                WHERE Result.NumPlayers >= :minNumPlayers
                ORDER BY Result.StartTimeDate DESC
                """ % locals()
            limitOffset = limit[0]
            if limitOffset is None: limitOffset = 0
            limitNum = limit[1]
            limitOffset -= 1

            count = c.execute("SELECT COUNT(*) FROM (%s) AS TMP" % stmt, locals()).fetchone()[0]
            if limitOffset > 0:
                if count < limitOffset + limitNum:
                    limitOffset = count-limitNum
            limitOffset = max(0, limitOffset)

            stmt += "LIMIT :limitNum OFFSET :limitOffset"

            ans = c.execute(stmt, locals()).fetchall()

            trackMapping = self.trackMapping(c)

            sessions = []
            for i,a in enumerate(ans):
                r = {}
                r['id'] = a[0]
                r['type'] = a[1]
                r['podium'] = [a[2], a[3], a[4]] # names might be None
                r['posSelf'] = a[5]
                r['numPlayers'] = a[6]
                r['timeStamp'] = a[7]
                r['multiplayer'] = a[8]
                r['track'] = a[9]
                r['uitrack'] = trackMapping.get(r['track'], r['track'])
                r['counter'] = limitOffset + i + 1
                sessions.append(r)
            return {'sessions' : sessions, 'numberOfSessions' : count}

    def alltracks(self):
        with self.db:
            c = CursorDebug(self.db.cursor())
            ans = c.execute("SELECT Track FROM Tracks NATURAL JOIN Combos GROUP BY Track").fetchall()
            trackMapping = self.trackMapping(c)
            res = []
            for r in ans:
                res.append(dict(track=r[0], uitrack=trackMapping.get(r[0], r[0])))
            return res

    def allcars(self):
        with self.db:
            c = CursorDebug(self.db.cursor())
            ans = c.execute("SELECT Car FROM Cars NATURAL JOIN ComboCars GROUP BY Car").fetchall()
            carMapping = self.carMapping(c)
            res = []
            for r in ans:
                res.append(dict(car=r[0], uicar=carMapping.get(r[0], r[0])))
            return res

    def allservers(self):
        with self.db:
            c = CursorDebug(self.db.cursor())
            ans = c.execute("SELECT DISTINCT ServerIpPort FROM Session").fetchall()
            res = []
            for a in ans:
                res.append(a[0])
            return res

    def currentCombo(self, server=None):
        with self.db:
            c = CursorDebug(self.db.cursor())
            scond = " WHERE ServerIpPort = :server" if not server is None else ""
            acdebug("currentCombo.")
            ans = c.execute("SELECT Track,CarIds FROM Session NATURAL JOIN ComboView NATURAL JOIN Tracks WHERE SessionId IN (SELECT MAX(SessionId) FROM Session %(scond)s)"%locals(), locals()).fetchone()
            if ans is None or len(ans) != 2:
                return (None,[])
            track = ans[0]
            carStr = ans[1]
            ans = c.execute("SELECT Car FROM Cars WHERE CarId IN (%(carStr)s)" % locals()).fetchall()
            cars = []
            for a in ans:
                cars.append(a[0])
            acdebug("currentCombo: %s %s %s", track, carStr, cars)
            return (track, cars)

    def lapDetails(self, lapid, withHistoryInfo=False): # withHistoryInfo is ignored locally
        if lapid is None:
            return {}
        with self.db:
            proft = time.time()
            startt = proft
            c = self.db.cursor()
            trackMapping = self.trackMapping(c)
            carMapping = self.carMapping(c)
            ans = c.execute("""
                SELECT * FROM LapTimes WHERE LapId=:lapid
            """, locals()).fetchone()
            if ans is None:
                return {}
            res = {}
            for i,v in enumerate(ans):
                if c.description[i][0].lower() == 'historyinfo' and not v is None:
                    # convert the 'memoryinfo' instance to a bytes array
                    v = bytes(v)
                res[c.description[i][0].lower()] = v
            for s in range(10):
                if res['sectortime%d'%s] == self.invalidSplit:
                    res['sectortime%d'%s] = None
                else:
                    res['sectortime%d'%s] = int(res['sectortime%d'%s]+0.5)
            proft = prof("ld normal info", proft)
            if withHistoryInfo:
                ans = c.execute("SELECT HistoryInfo FROM LapBinBlob WHERE LapId=:lapid", locals()).fetchone()
                if not ans is None and not ans[0] is None: res['historyinfo'] = bytes(ans[0])
            proft = prof("ld binary blob", proft)
            ans = c.execute("SELECT Cuts, CollisionsCar, CollisionsEnv, GripLevel, Ballast FROM Lap WHERE LapId=:lapid", locals()).fetchone()
            proft = prof("ld collision info", proft)
            res['cuts'] = ans[0]
            res['collisionscar'] = ans[1]
            res['collisionsenv'] = ans[2]
            res['griplevel'] = ans[3]
            res['ballast'] = ans[4]
            # get the lap counts
            playerid = res['playerid']
            track = res['track']
            carid = res['carid']
            numLapKeys = {0:"numlaps_invalid", 1:"numlaps_valid", 2:"numlaps_unknown"}
            for valid in [0,1,2]:
                ans = c.execute("""
                    SELECT COUNT(*) FROM Lap NATURAL JOIN PlayerInSession NATURAL JOIN Session NATURAL JOIN Tracks WHERE Track=:track AND CarId=:carid AND valid=:valid AND PlayerId=:playerid
                """, locals()).fetchone()
                res[numLapKeys[valid]] = ans[0]
            proft = prof("ld valid count", proft)
            # get the theoretical best
            bestSectors = self.getBestSectorTimes(res['track'], res['car'], res['steamguid'], cursor=c)
            tb = 0
            bs = []
            for s in bestSectors:
                if s is None:
                    break
                tb += s
                bs.append(s)
            if tb == 0:
                tb = None
            res['bestSectors'] = bs
            res['tb'] = tb
            proft = prof("ld best sectors", proft)
            # best lap time
            sbAndPb = self.getSBandPB(res['track'], res['car'], res['steamguid'], cursor=c)
            res['pb'] = sbAndPb['pb']
            proft = prof("ld sb and pb", proft)
            # get the versions used
            pisid = res['playerinsessionid']
            ans = c.execute("""
                SELECT ACVersion, PTVersion, TrackChecksum, CarChecksum, ServerIpPort, EndTimeDate
                FROM PlayerInSession NATURAL JOIN Session
                WHERE PlayerInSessionId = :pisid
            """, locals()).fetchone()
            if not ans[0] is None:
                M = re.match(r'(.*)\s*PT@AC\s*(.*)', ans[0])
                if not M is None:
                    res['acVersion'] = M.group(2)
                    res['ptVersion'] = M.group(1)
                else:
                    res['acVersion'] = ans[0]
                    res['ptVersion'] = "unknown"
            else:
                res["acVersion"] = "unknown"
                res["ptVersion"] = "unknown"
            res['stVersion'] = ans[1]
            res['trackChecksum'] = ans[2]
            res['carChecksum'] = ans[3]
            res['server'] = ans[4]
            et = ans[5]
            ans = c.execute("SELECT FuelRatio FROM Lap WHERE LapId=:lapid", locals()).fetchone()
            if ans is None or et == 0:
                res['fuelratio'] = -1.
            else:
                res['fuelratio'] = ans[0]
            track = res['track']
            car = res['car']
            ans = c.execute("SELECT RequiredTrackChecksum FROM Tracks WHERE Track=:track", locals()).fetchone()
            if ans[0] is None:
                res['trackChecksumCheck'] = None
            else:
                res['trackChecksumCheck'] = res['trackChecksum'] == ans[0]
            ans = c.execute("SELECT RequiredCarChecksum FROM Cars WHERE Car=:car", locals()).fetchone()
            if ans[0] is None:
                res['carChecksumCheck'] = None
            else:
                res['carChecksumCheck'] = res['carChecksum'] == ans[0]
            res['uitrack'] = trackMapping.get(res['track'], res['track'])
            res['uicar'] = carMapping.get(res['car'], res['car'])
            proft = prof("ld versions and checksums", proft)
            lapId = res['lapid']
            c.execute("""
                WITH ValidPlayerInSessionLaps AS (
	               SELECT LapId, LapTime
	               FROM Lap NATURAL JOIN PlayerInSession NATURAL JOIN Session
	               WHERE PlayerInSessionId = (SELECT PlayerInSessionId FROM Lap NATURAL JOIN PlayerInSession WHERE LapId=:lapId) AND VALID = 1
                ) SELECT LapId FROM ValidPlayerInSessionLaps WHERE LapTime = (SELECT MIN(LapTime) FROM ValidPlayerInSessionLaps)
            """ % locals(), locals())
            a = c.fetchone()
            res['driversBestValidSessionLapId'] = None if a is None else a[0]
            proft = prof("ld best players session lapId", proft)
            c.execute("""
                WITH ValidSessionLaps AS (
                	SELECT LapId, LapTime
                	FROM Lap NATURAL JOIN PlayerInSession NATURAL JOIN Session
                	WHERE SessionId = (SELECT SessionId FROM Lap NATURAL JOIN PlayerInSession NATURAL JOIN Session WHERE LapId=:lapId) AND VALID = 1
                ) SELECT LapId FROM ValidSessionLaps WHERE LapTime = (SELECT MIN(LapTime) FROM ValidSessionLaps)
            """, locals())
            a = c.fetchone()
            res['bestValidSessionLapId'] = None if a is None else a[0]
            proft = prof("ld best session lapId", proft)
            # fetch session cars
            c.execute("""
                SELECT Car FROM
                    Lap LEFT JOIN PlayerInSession ON Lap.PlayerInSessionId = PlayerInSession.PlayerInSessionId LEFT JOIN
                    Session ON PlayerInSession.SessionId = Session.SessionId LEFT JOIN
                    ComboCars ON (Session.ComboId = ComboCars.ComboId) LEFT JOIN
                    Cars ON (ComboCars.CarId = Cars.CarId)
                WHERE Lap.LapId = :lapid
            """, locals())
            comboCars = [x[0] for x in c.fetchall()]
            proft = prof("ld session cars", proft)
            bestEgoServerLap = self.lapStats('top', [None,1], track, 0, comboCars, res['steamguid'], [1,2], 0, withHistoryInfo=True, lapIdOnly=True, cursor=c)
            res['driversBestValidServerLapId'] = None if len(bestEgoServerLap['laps']) == 0 else bestEgoServerLap['laps'][0]['id']
            proft = prof("ld driver's best info", proft)
            bestServerLap = self.lapStats('top', [0,1], track, 0, comboCars, res['steamguid'], [1,2], 0, withHistoryInfo=True, lapIdOnly=True, cursor=c)
            res['bestValidServerLapId'] = None if len(bestServerLap['laps']) == 0 else bestServerLap['laps'][0]['id']
            proft = prof("ld server's best info", proft)
            prof("ld total",startt)
            return res

    def comparisonInfo(self, lapIds):
        with self.db:
            t = time.time()
            c = self.db.cursor()
            trackMapping = self.trackMapping(c)
            carMapping = self.carMapping(c)
            lapIds = ",".join(map(lambda x: str(x), lapIds))
            c.execute("""
                SELECT Track, Car, LapTime, LapBinBlob.HistoryInfo, Lap.LapId, Length, Name
                FROM Lap NATURAL JOIN PlayerInSession NATURAL JOIN Session NATURAL JOIN Tracks NATURAL JOIN Cars NATURAL JOIN Players JOIN LapBinBlob ON (Lap.LapId = LapBinBlob.LapId)
                WHERE Lap.LapId IN (%s)
            """ % lapIds)
            res = {}
            for a in c.fetchall():
                if a[3] is None:
                    continue
                res[a[4]] = dict(track=a[0], uitrack=trackMapping.get(a[0],a[0]), uicar=carMapping.get(a[1],a[1]), laptime=a[2], length=a[5], historyinfo=a[3], player=a[6])
            prof("ci total", t)
            return res

    def sessionDetails(self, sessionid):
        with self.db:
            c = self.db.cursor()
            carMapping = self.carMapping(c)
            si = c.execute("""
                SELECT Track, SessionType, NumberOfLaps, Duration, StartTimeDate, EndTimeDate, UiTrackName
                FROM Session NATURAL JOIN Tracks
                WHERE SessionId=:sessionid
            """, locals()).fetchone()
            sessionInfo = dict(track=si[0], uitrack=si[6], sessionType=si[1], numLaps=si[2], duration=si[3], timestamp=[si[4], si[5]])
            ans = c.execute("""
                SELECT COUNT(*) FROM Session NATURAL JOIN PlayerInSession NATURAL JOIN PisCorrections
                WHERE SessionId=:sessionid AND (DeltaTime IS NOT NULL OR DeltaLaps IS NOT NULL OR DeltaPoints IS NOT NULL)
            """, locals()).fetchone()
            sessionInfo['corrected'] = ans[0] > 0
            cs = c.execute("""
                SELECT CSName,EventName,EventId,SessionName,CSId,CSEventSessionId
                FROM CSEventSessions NATURAL JOIN CSEvent NATURAL JOIN CSSeasons
                WHERE SessionId = :sessionid
            """, locals()).fetchone()
            if not cs is None:
                sessionInfo.update(csName=cs[0], csEventName=cs[1], csEventId=cs[2], csSessionName=cs[3], csId=cs[4], csEventSessionId=cs[5])
            players = c.execute("""
                SELECT FinishPosition,RaceFinished,PlayerInSessionId,PlayerId,FinishTime,Car,Name,FinishPositionOrig,SteamGuid,TeamName
                FROM PlayerInSession NATURAL JOIN Session
                                     NATURAL JOIN Cars
                                     NATURAL JOIN Players
                                     LEFT JOIN Teams ON (Teams.TeamId = PlayerInSession.TeamId)
                WHERE SessionId=:sessionid
                ORDER BY FinishPosition
            """, locals()).fetchall()
            classification = []
            for cp in players:
                pisId = cp[2]
                corr = c.execute("SELECT DeltaTime,DeltaLaps,DeltaPoints,Comment FROM PisCorrections WHERE PlayerInSessionId=:pisId", locals()).fetchone()
                if corr is None:
                    corr = [None]*4

                nl = c.execute("SELECT MAX(LapCount) FROM Lap WHERE PlayerInSessionId=:pisId", locals()).fetchone()[0]
                fl = c.execute("SELECT MIN(LapTime) FROM Lap WHERE PlayerInSessionId=:pisId", locals()).fetchone()[0]
                pitinfo_av = c.execute("SELECT COUNT(*) FROM Lap WHERE PlayerInSessionId=:pisId AND TimeInPitLane IS NULL", locals()).fetchone()[0]
                pitinfo_av = pitinfo_av == 0
                n_stops    = c.execute("SELECT COUNT(*) FROM Lap WHERE PlayerInSessionId=:pisId AND TimeInPit > 0", locals()).fetchone()[0]
                n_pitlane  = c.execute("SELECT COUNT(*) FROM Lap WHERE PlayerInSessionId=:pisId AND TimeInPitLane > 0", locals()).fetchone()[0]
                t_pitlane  = c.execute("SELECT SUM(TimeInPitLane) FROM Lap WHERE PlayerInSessionId=:pisId AND TimeInPitLane > 0", locals()).fetchone()[0]
                n_valid = c.execute("SELECT COUNT(*) FROM Lap WHERE PlayerInSessionId=:pisId AND Valid = 1", locals()).fetchone()[0]
                c.execute("SELECT SUM(Cuts), SUM(CollisionsEnv), SUM(CollisionsCar) FROM Lap WHERE PlayerInSessionId=:pisId", locals())
                n_cuts, n_collenv, n_collcar = c.fetchone()
                finishTime = cp[4]

                name = cp[6] if cp[9] is None else cp[6] + " [%s]" % cp[9]

                classification.append(
                    dict(pos=cp[0] if not cp[0] is None else 1000,
                         finished=cp[1],
                         pisId=cp[2],
                         pId=cp[3],
                         finishTime=finishTime,
                         car=cp[5],
                         uicar=carMapping.get(cp[5], cp[5]),
                         numLaps=nl,
                         fastestLap=fl,
                         name=name,
                         numPitStops=n_stops,
                         numDriveThroughs=max(0, n_pitlane-n_stops),
                         totalTimePitLane=t_pitlane,
                         pitInfoAvailable=pitinfo_av,
                         finishPositionOrig=cp[7] if not cp[7] is None else 1000,
                         deltaTime=corr[0],
                         deltaLaps=corr[1],
                         deltaPoints=corr[2],
                         corrComment=corr[3],
                         guid=cp[8],
                         numLapsValid=n_valid,
                         numCuts=n_cuts,
                         numCollisions=n_collenv+n_collcar if not n_collenv is None and not n_collcar is None else None,
                         numCollisionsC2C=n_collcar))
            for i,c in enumerate(classification):
                if c['pos'] >= 1000:
                    c['pos'] = "DNF"
                if c['finishPositionOrig'] >= 1000:
                    c['finishPositionOrig'] = "DNF"
            return dict(sessionInfo=sessionInfo, classification=classification)

    def recalculateSessionPositions(self, c, sid):
        ans = c.execute("SELECT NumberOfLaps,SessionType FROM Session WHERE SessionId=:sid", locals()).fetchone()
        numLaps = ans[0] if not ans is None else None
        sType = ans[1] if not ans is None else None
        if numLaps is None or sType != "Race":
            # not supported. Only races with fixed number of laps can be handled atm.
            return
        ans = c.execute("""
            SELECT PlayerInSessionId,FinishPositionOrig,DeltaTime,DeltaLaps,FinishTime
            FROM PlayerInSession NATURAL LEFT JOIN PisCorrections
            WHERE SessionId=:sid
            ORDER BY FinishPositionOrig
        """, locals()).fetchall()
        players = []
        correctionsFound = False
        for a in ans:
            players.append(dict(pisid=a[0],
                                posorig=a[1],
                                deltatime=a[2] if not a[2] is None else 0,
                                deltalaps=a[3] if not a[3] is None else 0,
                                finishtime=a[4]))
            correctionsFound = correctionsFound or players[-1]['deltatime'] != 0 or players[-1]['deltalaps'] != 0
            acinfo("correctionsFound=%s",correctionsFound)
        if not correctionsFound:
            c.execute("""
                UPDATE PlayerInSession SET
                    FinishPosition=FinishPositionOrig
                WHERE PlayerInSessionId IN (SELECT PlayerInSessionId FROM Session NATURAL JOIN PlayerInSession WHERE SessionId=:sid)
            """, locals())
            return
        finishLineCrossings = []
        for p in players:
            pisid = p['pisid']
            p['newPos'] = 1000
            ans = c.execute("""
                SELECT MAX(LapCount) FROM Lap
                WHERE PlayerInSessionId=:pisid
            """, locals()).fetchone()
            if ans:
                lapCount = ans[0]
                ans = c.execute("SELECT LapId FROM Lap WHERE LapCount=:lapCount AND PlayerInSessionId=:pisid", locals()).fetchall()
                lastLapCandidates = list(map(lambda x: x[0], ans))
                laps = []
                for llc in lastLapCandidates:
                    laps = []
                    ft = 0
                    for lc in range(1,lapCount+1):
                        ans = c.execute("SELECT MAX(LapId) FROM Lap WHERE LapId<=:llc AND PlayerInSessionId=:pisid AND LapCount=:lc", locals()).fetchone()
                        lapid = ans[0]
                        acinfo("lapid=%s, llc=%s, pisid=%s, lc=%s", lapid, llc, pisid, lc)
                        ans = c.execute("SELECT LapTime FROM Lap WHERE LapId=:lapid", locals()).fetchone()
                        if ans is None:
                            acinfo("Cannot reconstruct race timing from database.")
                            ft = None
                            break
                        laptime = ans[0]
                        laps.append((ans[0], laptime))
                        ft += laptime
                    if ft is None:
                        break
                    if ft == p['finishtime']:
                        break
                if not p['finishtime'] is None and not ft is None:
                    if ft != p['finishtime']:
                        acwarning("recalculateSessionPositions could not reconstruct the finish time from the driven laps (PlayerInSessionId=%d), using a virtual start time", pisid)
                        acwarning("  finishtime=%d sum(laps)=%d", p['finishtime'], ft)
                    p['startTime'] = p['finishtime'] - ft
                else:
                    p['startTime'] = 0
                p['laps'] = laps
            else:
                p['startTime'] = 0
                p['laps'] = []
            t = p['startTime'] + p['deltatime']
            finishLineCrossings.append( (p, t, 0+p['deltalaps']) )
            for lapcount,ld in enumerate(p['laps']):
                laptime = ld[1]
                t += laptime
                finishLineCrossings.append( (p, t, lapcount+1+p['deltalaps']) )

        # sort the fl crossings with ascending t
        finishLineCrossings.sort(key=lambda x: x[1])

        for flc in finishLineCrossings:
            p = flc[0]
            t = flc[1]
            lc= flc[2]
            m = t // 60000
            s =(t-m*60000)//1000
            ms = t%1000
            acinfo("  <oldpos=%2d> <t=%02d:%03d.%03d> <lc=%2d>", p['posorig'],m,s,ms,lc)

        classment = []
        cNumLaps = 0
        winnerIdx = None
        # find the first fl crossing with enough number of laps
        for idx,flc in enumerate(finishLineCrossings):
            lc = flc[2]
            if winnerIdx is None or (lc > cNumLaps and lc <= numLaps):
                winnerIdx = idx
                cNumLaps = lc
        finish = []
        playersFinished = set([])
        for flc in finishLineCrossings[winnerIdx:]:
            p = flc[0]
            t = flc[1]
            lc = flc[2]
            if not p['pisid'] in playersFinished:
                playersFinished.add(p['pisid'])
                finish.append( (p, t, lc) )
        def cmpFinish(f1, f2):
            lc1 = f1[2]
            lc2 = f2[2]
            t1 = f1[1]
            t2 = f2[1]
            if lc1 > lc2: return -1
            if lc2 > lc1: return 1
            if t1 < t2: return -1
            if t2 < t1: return 1
            return 0
        finish.sort(key=functools.cmp_to_key(cmpFinish))
        for idx,flc in enumerate(finish):
            flc[0]['newPos'] = idx+1
        for p in players:
            pisid = p['pisid']
            newpos = p['newPos']
            acinfo("recalc players pos: %d <oldPos=%d> <newPos=%d>", pisid, p['posorig'], newpos)
            c.execute("""
                UPDATE PlayerInSession
                SET FinishPosition=:newpos
                WHERE PlayerInSessionId=:pisid
            """, locals())

    def playerInSessionPaCModify(self, pis_id, delta_time, delta_points, delta_laps, comment):
        with self.db:
            c = self.db.cursor()
            ans = c.execute("""
                SELECT SessionId,NumberOfLaps,SessionType,PisCorrectionId
                FROM PlayerInSession NATURAL JOIN Session NATURAL LEFT JOIN PisCorrections
                WHERE PlayerInSessionId=:pis_id
            """,locals()).fetchone()
            sid = ans[0]
            numLaps = ans[1]
            stype = ans[2]
            piscid = ans[3]
            emptyData = (delta_time is None and delta_points is None and delta_laps is None and comment is None)
            if piscid is None and not emptyData:
                c.execute("""
                    INSERT INTO PisCorrections(PlayerInSessionId,DeltaPoints,DeltaTime,DeltaLaps,Comment)
                    VALUES(:pis_id, :delta_points, :delta_time, :delta_laps, :comment)
                """, locals())
            else:
                if not emptyData:
                    c.execute("""
                        UPDATE PisCorrections
                        SET DeltaPoints=:delta_points,
                            DeltaTime=:delta_time,
                            DeltaLaps=:delta_laps,
                            Comment=:comment
                        WHERE PlayerInSessionId=:pis_id
                    """, locals())
                else:
                    c.execute("""
                        DELETE FROM PisCorrections WHERE PisCorrectionId=:piscid
                    """, locals())
            self.recalculateSessionPositions(c, sid)

    def playerInSessionDetails(self, pisId):
        with self.db:
            c = self.db.cursor()
            carMapping = self.carMapping(c)
            c.execute("SELECT Name FROM PlayerInSession NATURAL JOIN Players WHERE PlayerInSessionId=:pisId LIMIT 1", locals())
            ans = c.fetchone()
            pisInfo = {'name' : ans[0]}
            c.execute("""
                SELECT LapTime, Valid, Name, Car, Timestamp,
                       TyreCompound, SteamGuid, LapId,
                       PenaltiesEnabled, TyreWearFactor, FuelRate, Damage, AidABS,
                       AidAutoBlib, AidAutoBrake, AidAutoClutch, AidAutoShift,
                       AidIdealLine, AidStabilityControl, AidTC,
                       AidSlipStream, AidTyreBlankets, InputMethod, Shifter, MaxABS,
                       MaxTC, TemperatureAmbient, TemperatureTrack, MaxSpeed_KMH, LapCount,
                       TimeInPitLane, TimeInPit, ESCPressed, Cuts, CollisionsCar, CollisionsEnv,
                       FuelRatio, EndTimeDate,
                       SectorTime0, SectorTime1, SectorTime2, SectorTime3, SectorTime4, SectorTime5,
                       SectorTime6, SectorTime7, SectorTime8, SectorTime9
                FROM Lap NATURAL JOIN PlayerInSession NATURAL JOIN Session NATURAL JOIN Cars NATURAL JOIN Tracks NATURAL JOIN Players NATURAL JOIN TyreCompounds
                WHERE PlayerInSessionId=:pisId
                ORDER BY LapCount
            """,locals())
            desc = c.description
            ans = c.fetchall()
            laps = []
            for i,cols in enumerate(ans):
                a = DictCursor(cols, desc)
                r = {}
                r['lapTime'] = a["LapTime"]
                r['valid'] = a["Valid"]
                r['lapCount'] = a['LapCount']
                r['name'] = ['?',a["Name"]][not a["Name"] is None]
                r['car'] = a["Car"]
                r['uicar'] = carMapping.get(a["Car"], a["Car"])
                r['timeStamp'] = a["Timestamp"]
                r['tyre'] = a["TyreCompound"]
                r['guid'] = a["SteamGuid"]
                r['id'] = a["LapId"]
                r['penalties'] = a["PenaltiesEnabled"]
                r['tyreWear'] = a["TyreWearFactor"]
                r['fuelRate'] = a["FuelRate"]
                r['damage'] = a["Damage"]
                r['abs'] = a["AidABS"]
                r['autoBlib'] = a["AidAutoBlib"]
                r['autoBrake'] = a["AidAutoBrake"]
                r['autoClutch'] = a["AidAutoClutch"]
                r['autoShift'] = a["AidAutoShift"]
                r['idealLine'] = a["AidIdealLine"]
                r['stabilityControl'] = a["AidStabilityControl"]
                r['tractionControl'] = a["AidTC"]
                r['slipStream'] = a["AidSlipStream"]
                r['tyreBlankets'] = a["AidTyreBlankets"]
                r['inputMethod'] = a["InputMethod"]
                r['inputShifter'] = a["Shifter"]
                r['maxABS'] = a["MaxABS"]
                r['maxTC'] = a["MaxTC"]
                r['tempAmbient'] = a["TemperatureAmbient"]
                r['tempTrack'] = a["TemperatureTrack"]
                r['maxSpeed'] = a["MaxSpeed_KMH"]
                r['timeInPitLane'] = a['TimeInPitLane']
                r['timeInPit'] = a['TimeInPit']
                r['escKeyPressed'] = a['ESCPressed']
                r['cuts'] = a['Cuts']
                r['collisions'] = a['CollisionsEnv'] + a['CollisionsCar'] if not a['CollisionsEnv'] is None and not a['CollisionsCar'] is None else None
                r['collisionsCar'] = a['CollisionsCar']
                endtime = a['EndTimeDate']
                acdebug("endtime=%s fr=%s", endtime, a['FuelRatio'])
                r['fuelRatio'] = a['FuelRatio'] if endtime != 0 else -1.
                r['sectors'] = list(map(lambda x: (x>0 and x<self.invalidSplit and int(x+0.5)) or None, cols[-10:]))
                laps.append(r)
            return {'laps':laps, 'playerInSessioInfo':pisInfo}

    def getPlayers(self, limit, searchPattern = None, inBanList = False, group_id = None, include_groups = False, inWhitelist = False, orderby=None):
        with self.db:
            c = CursorDebug(self.db.cursor())
            now = unixtime_now()
            if not searchPattern is None:
                searchPattern = "%" + searchPattern.lower() + "%"
                search_stmt = "WHERE LOWER(Name) LIKE :searchPattern"
            else:
                search_stmt = ""
            if inBanList:
                if search_stmt == "":
                    search_stmt = "WHERE"
                else:
                    search_stmt += " AND"
                search_stmt += " (NOT BannedUntil IS NULL) AND (BannedUntil >= :now)"
                if orderby is None:
                    orderby = 'banneduntil'
            else:
                if orderby is None:
                    orderby = 'lastseen'
            if orderby == 'banneduntil':
                order_stmt = "ORDER BY BannedUntil DESC"
            elif orderby == 'drivername':
                order_stmt = "ORDER BY Name"
            else: # orderby == 'lastseen':
                order_stmt = "ORDER BY PisId DESC"
            if inWhitelist:
                if search_stmt == "":
                    search_stmt = "WHERE"
                else:
                    search_stmt += " AND"
                search_stmt += " Whitelisted = 1"
            if not group_id is None and not group_id <= 0:
                if search_stmt == "":
                    search_stmt = "WHERE"
                else:
                    search_stmt += " AND"
                search_stmt += " GroupId=:group_id"
            limit_stmt = ""
            count = c.execute("""
                WITH BannedPlayers AS (
                    SELECT PlayerId,MAX(BanCount) AS BanCount,MAX(BannedUntil) AS BannedUntil FROM Players NATURAL LEFT JOIN BlacklistedPlayers
                    GROUP BY PlayerId, Name, SteamGuid, IsOnline
                )
                SELECT COUNT(*) FROM (SELECT PlayerId, Name, SteamGuid, IsOnline, BanCount, BannedUntil, Whitelisted FROM Players NATURAL LEFT JOIN PlayerInSession NATURAL LEFT JOIN Session NATURAL LEFT JOIN BannedPlayers NATURAL LEFT JOIN GroupEntries
                                      %(search_stmt)s
                                      GROUP BY PlayerId, Name, SteamGuid, IsOnline, BanCount, BannedUntil, Whitelisted) AS Temp
            """ % locals(), locals()).fetchone()
            if count is None: count = 0
            else: count = count[0]
            if not limit is None:
                if limit[0] is None:
                    offset = 1
                else:
                    offset = limit[0]
                offset -= 1
                limit = limit[1]
                if offset + limit > count:
                    offset = count-limit
                if offset < 0:
                    offset = 0
                limit_stmt = "LIMIT %d OFFSET %d" % (limit, offset)
            ans = c.execute("""
                WITH BannedPlayers AS (
                    SELECT PlayerId,MAX(BanCount) AS BanCount,MAX(BannedUntil) AS BannedUntil FROM Players NATURAL LEFT JOIN BlacklistedPlayers
                    GROUP BY PlayerId, Name, SteamGuid, IsOnline
                )
                SELECT PlayerId, MAX(PlayerInSessionId) AS PisId, Name, SteamGuid, IsOnline, MAX(StartTimeDate), BanCount, BannedUntil, Whitelisted
                FROM Players NATURAL LEFT JOIN PlayerInSession NATURAL LEFT JOIN Session NATURAL LEFT JOIN BannedPlayers NATURAL LEFT JOIN GroupEntries
                %(search_stmt)s
                GROUP BY PlayerId, Name, SteamGuid, IsOnline, BanCount, BannedUntil, Whitelisted
                %(order_stmt)s
                %(limit_stmt)s
            """ % locals(), locals()).fetchall()
            ply = []
            for p in ans:
                ply.append(dict(playerId=p[0], lastSessionId=p[1], name=p[2], guid=p[3], isOnline=p[4], lastSeen=p[5], banCount=p[6], bannedUntil=p[7], whitelisted=p[8]))
            res = {'players':ply, 'count':count}
            if include_groups:
                res['groups'] = self.allgroups(c)
            return res

    def allgroups(self, cursor=None):
        if cursor is None:
            with self.db:
                c = self.db.cursor()
                return self.allgroups(c)
        ans = cursor.execute("SELECT GroupId, GroupName FROM PlayerGroups WHERE GroupId!=0 ORDER BY GroupName").fetchall()
        groups = [{'name':'(everyone)', 'groupid':0}]
        for c in ans:
            groups.append({'groupid':c[0], 'name':c[1]})
        return groups

    def modifyGroup(self, add_group = None, del_group = None, group_id = None, add_player_id = None, del_player_id = None,
                    whitelist_player_id = None, unwhitelist_player_id = None):
        with self.db:
            c = self.db.cursor()
            if not add_group is None:
                c.execute("INSERT INTO PlayerGroups(GroupName) VALUES(:add_group)", locals())
                group_id=c.lastrowid
                return group_id
            elif not del_group is None and del_group != 0:
                c.execute("DELETE FROM GroupEntries WHERE GroupId=:del_group", locals())
                c.execute("DELETE FROM SetupDeposit WHERE GroupId=:del_group", locals())
                c.execute("DELETE FROM PlayerGroups WHERE GroupId=:del_group", locals())
            elif not add_player_id is None and not group_id is None and group_id != 0:
                c.execute("INSERT INTO GroupEntries(GroupId,PlayerId) VALUES(:group_id,:add_player_id)", locals())
            elif not del_player_id is None and not group_id is None and group_id != 0:
                c.execute("DELETE FROM GroupEntries WHERE GroupId=:group_id AND PlayerId=:del_player_id", locals())
            elif not whitelist_player_id is None:
                c.execute("UPDATE Players SET Whitelisted = 1 WHERE PlayerId = :whitelist_player_id", locals())
            elif not unwhitelist_player_id is None:
                c.execute("UPDATE Players SET Whitelisted = NULL WHERE PlayerId = :unwhitelist_player_id", locals())

    def setupDepositGet(self, guid, car, track, setupid = None):
        with self.db:
            c = self.db.cursor()
            ans = c.execute("""
                SELECT SetupDeposit.SetupId, SetupDeposit.Name AS SetupName, Players.Name AS SenderName, PlayerGroups.GroupName, Players.SteamGuid=:guid
                FROM SetupDeposit LEFT JOIN Players ON (SetupDeposit.PlayerId=Players.PlayerId)
                                  LEFT JOIN PlayerGroups ON (SetupDeposit.GroupId=PlayerGroups.GroupId)
                WHERE
                    SetupDeposit.CarId IN (SELECT CarId FROM Cars WHERE Car=:car) AND
                    SetupDeposit.TrackId IN (SELECT TrackId FROM Tracks WHERE Track=:track) AND
                    (SetupDeposit.GroupId IN (SELECT GroupId FROM GroupEntries NATURAL LEFT JOIN Players WHERE SteamGuid=:guid) OR
                     SetupDeposit.GroupId=0 OR
                     SetupDeposit.PlayerId IN (SELECT PlayerId FROM Players WHERE SteamGuid=:guid))
                ORDER BY SenderName,SetupName""", locals()).fetchall()
            setups = []
            okToSend = False
            for a in ans:
                if a[0] == setupid:
                    okToSend = True
                setups.append(dict(setupid=a[0], name=a[1], sender=a[2], group=a[3], owner=a[4]))
            selectedSet = None
            if okToSend and not setupid is None:
                ans = c.execute("SELECT Setup FROM SetupDeposit WHERE SetupId=:setupid", locals()).fetchone()
                if not ans is None and not ans[0] is None:
                    selectedSet = bytes(ans[0])
            ans = c.execute("""
                SELECT GroupEntries.GroupId, GroupName
                FROM GroupEntries LEFT JOIN Players ON (GroupEntries.PlayerId=Players.PlayerId)
                                  LEFT JOIN PlayerGroups ON (GroupEntries.GroupId=PlayerGroups.GroupId)
                WHERE Players.SteamGuid=:guid AND GroupEntries.GroupId!=0
            """, locals()).fetchall()
            memberOfGroup = [dict(group_id=0, group_name="(everyone)")]
            for a in ans:
                if a[0] != 0:
                    memberOfGroup.append(dict(group_id=a[0], group_name=a[1]))
            return {'setups':setups, 'selectedSet': {'id':setupid, 'set':selectedSet}, 'memberOfGroup':memberOfGroup}

    def setupDepositSave(self, guid, car, track, name, groupid, setup):
        with self.db:
            c = self.db.cursor()
            setup = bytes(setup)
            # make sure that car and track exists
            c.execute("""
                INSERT INTO Cars(Car)
                    SELECT :car
                    WHERE NOT EXISTS (SELECT 1 FROM Cars WHERE Car=:car)
            """, locals())
            c.execute("""
                INSERT INTO Tracks(Track)
                    SELECT :track
                    WHERE NOT EXISTS (SELECT 1 FROM Tracks WHERE Track=:track)
            """, locals())
            ans = c.execute("SELECT CarId FROM Cars WHERE Car=:car", locals()).fetchone()
            carid = ans[0] if not ans is None else None
            ans = c.execute("SELECT TrackId FROM Tracks WHERE Track=:track", locals()).fetchone()
            trackid = ans[0] if not ans is None else None
            ans = c.execute("SELECT PlayerId FROM Players WHERE SteamGuid=:guid", locals()).fetchone()
            playerid = ans[0] if not ans is None else None
            ans = c.execute("SELECT GroupEntryId FROM GroupEntries WHERE PlayerId=:playerid AND GroupId=:groupid", locals()).fetchone()
            groupOK = (groupid==0) or (not ans is None and len(ans) > 0)
            # assert that group_id 0 exists
            c.execute("""
                INSERT INTO PlayerGroups(GroupId,GroupName)
                    SELECT 0,'(everyone)'
                    WHERE NOT EXISTS (SELECT 1 FROM PlayerGroups WHERE GroupId=0)
            """, locals())
            c.execute("""
                INSERT INTO SetupDeposit(PlayerId,TrackId,CarId,GroupId,Name,Setup)
                VALUES (:playerid,:trackid,:carid,:groupid,:name,:setup)
            """, locals())

    def setupDepositRemove(self, guid, setupid):
        with self.db:
            c = self.db.cursor()
            c.execute("DELETE FROM SetupDeposit WHERE SetupId=:setupid and PlayerId IN (SELECT PlayerId FROM Players WHERE SteamGuid=:guid)", locals())

    def playerDetails(self, playerid = None, guid = None):
        with self.db:
            c = self.db.cursor()
            if not playerid is None:
                plyCond = " WHERE PlayerId=:playerid"
            else:
                plyCond = " WHERE SteamGUID=:guid"
            res = {}
            ans = c.execute("SELECT * FROM Players %(plyCond)s"%locals(), locals()).fetchone()
            playerInfo = {}
            for i,v in enumerate(ans):
                playerInfo[c.description[i][0].lower()] = v
            playerid = playerInfo['playerid']
            guid = playerInfo['steamguid']
            res['info'] = playerInfo
            ans = c.execute("SELECT * FROM Blacklist WHERE PlayerId=:playerid ORDER BY DateAdded DESC", locals())
            desc = c.description
            ans = ans.fetchall()
            res['bans'] = []
            if not ans is None:
                for row in ans:
                    ban = {}
                    for i,v in enumerate(row):
                        ban[desc[i][0].lower()] = v
                    res['bans'].append(ban)
            ans = c.execute("""
                SELECT COUNT(*) FROM
                Lap WHERE PlayerInSessionId IN
                    (SELECT PlayerInSessionId FROM PlayerInSession WHERE PlayerId=:playerid)
            """, locals()).fetchone()
            if ans is None:
                ans = 0
            else:
                ans = ans[0]
            res['numLaps'] = ans
            res['numPodiums'] = [None,None,None]
            for i in range(3):
                fp = i+1
                ans = c.execute("""
                    SELECT COUNT(*) FROM PlayerInSession NATURAL JOIN Session
                    WHERE PlayerId=:playerid AND FinishPosition=:fp AND SessionType='Race'
                """, locals()).fetchone()
                if ans is None:
                    ans = 0
                else:
                    ans = ans[0]
                res['numPodiums'][i] = ans
            ans = c.execute("""
                SELECT COUNT(*) FROM PlayerInSession NATURAL JOIN Session
                WHERE PlayerId=:playerid AND NOT FinishPosition IS NULL AND SessionType='Race'
            """, locals()).fetchone()
            if ans is None:
                ans = 0
            else:
                ans = ans[0]
            res['numRaces']= ans
            ans = c.execute("""
                SELECT GroupId FROM GroupEntries
                WHERE PlayerId=:playerid
            """, locals()).fetchall()
            res['memberOfGroup'] = []
            for a in ans:
                res['memberOfGroup'].append(a[0])
            return res

    def messagesDisabled(self, guid, name, newVal=None):
        with self.db:
            c = self.db.cursor()
            # assert that player is existing
            if c.execute("SELECT PlayerId FROM Players WHERE SteamGuid=:guid", locals()).fetchone() is None:
                c.execute("INSERT INTO Players(SteamGuid,Name) VALUES(:guid,:name)", locals())
            if not newVal is None:
                c.execute("UPDATE Players SET MessagesDisabled=:newVal WHERE SteamGuid=:guid", locals())
            return c.execute("SELECT MessagesDisabled FROM Players WHERE SteamGuid=:guid", locals()).fetchone()[0]

    def modifyBlacklistEntry(self, playerid = None, addBan = None, unban = None, extendPeriod = None, importedGuid = None):
        with self.db:
            now = unixtime_now()
            c = self.db.cursor()
            blId = None
            if not playerid is None:
                ans = c.execute("""
                    SELECT BlacklistId,DateAdded,Duration FROM BlacklistedPlayers
                    WHERE PlayerId=:playerid AND NOT BannedUntil IS NULL AND BannedUntil >= :now
                """, locals()).fetchone()
                if not ans is None:
                    blId = ans[0]
                    dateAdded = ans[1]
                    duration = ans[2]
            if not addBan is None:
                if blId is None:
                    c.execute("""
                        INSERT INTO Blacklist(PlayerId,DateAdded,Duration)
                        VALUES(:playerid,:now,:addBan)
                    """, locals())
            elif unban:
                if not blId is None:
                    newDur = now - dateAdded-1
                    c.execute("""
                        UPDATE Blacklist
                        SET Duration=:newDur
                        WHERE BlacklistId=:blId
                    """, locals())
            elif not importedGuid is None:
                ans = c.execute("SELECT PlayerId FROM Players WHERE SteamGuid=:importedGuid", locals()).fetchone()
                if ans is None:
                    c.execute("INSERT INTO Players(SteamGuid,Name,ArtInt) VALUES(:importedGuid,'Imported from blacklist',0)", locals())
                    playerid=c.lastrowid
                else:
                    playerid=ans[0]
                ans = c.execute("""
                    SELECT BlacklistId,DateAdded,Duration FROM BlacklistedPlayers
                    WHERE PlayerId=:playerid AND NOT ((BannedUntil IS NULL) OR BannedUntil <= :now)
                """, locals()).fetchone()
                if ans is None:
                    if extendPeriod is None:
                        duration=60*60*24*365*5
                    else:
                        duration = int(extendPeriod)
                    c.execute("""
                        INSERT INTO Blacklist(PlayerId,DateAdded,Duration)
                        VALUES(:playerid,:now,:duration)
                    """, locals())
                else:
                    if not extendPeriod is None:
                        blId = ans[0]
                        dateAdded = ans[1]
                        newDur = now + extendPeriod - dateAdded
                        c.execute("""
                            UPDATE Blacklist
                            SET Duration=:newDur
                            WHERE BlacklistId=:blId
                        """, locals())
            elif not extendPeriod is None:
                if not blId is None:
                    newDur = now + extendPeriod - dateAdded
                    c.execute("""
                        UPDATE Blacklist
                        SET Duration=:newDur
                        WHERE BlacklistId=:blId
                    """, locals())

    def auth(self, guid, track=None, cars=None, server=None, valid=None, minNumLaps=None, maxTimePercentage=None, tyre_list=None, maxRank=None, groups=[]):
        now = unixtime_now()
        with self.db:
            c = self.db.cursor()
            reason = []
            ok = True
            # check if guid is currently blacklisted
            ans = c.execute("""
                SELECT BannedUntil FROM BlacklistedPlayers NATURAL JOIN Players
                WHERE SteamGuid=:guid AND NOT BannedUntil IS NULL AND BannedUntil >= :now
            """, locals()).fetchone()
            blacklisted = not ans is None
            if blacklisted:
                reason.append("You are currently blacklisted on this server (until %s)." % (unixtime2datetime(ans[0]).date()))
                ok = False
            ans = c.execute("SELECT Whitelisted FROM Players WHERE SteamGuid=:guid", locals()).fetchone()
            whitelisted = not ans is None and ans[0]
        if not maxTimePercentage is None or not maxRank is None or not minNumLaps is None:
            if track is None and cars is None:
                track, cars = self.currentCombo(server)
            if valid is None:
                valid = [1,2]
            pb = self.lapStats(
                mode='top',
                limit=[None,1],
                track=track,
                artint=0,
                cars=cars,
                ego_guid=guid,
                valid=valid,
                minSessionStartTime=0,
                tyre_list=tyre_list,
                server=server,
                group_by_guid=True,
                groups=groups)
            if not maxTimePercentage is None:
                if len(pb['laps']) > 0 and pb['laps'][0]['guid'] == guid:
                    pbTime = pb['laps'][0]['lapTime']
                    sb = self.lapStats(
                        mode='top',
                        limit=[0,1],
                        track=track,
                        artint=0,
                        cars=cars,
                        ego_guid=None,
                        valid=valid,
                        minSessionStartTime=0,
                        tyre_list=tyre_list,
                        groups=groups,
                        server=server
                    )
                    sbTime = sb['laps'][0]['lapTime']
                    maxTime = int(float(sbTime)*maxTimePercentage / 100. + 0.5)
                    maxTimeOK = pbTime <= maxTime
                    if not maxTimeOK:
                        ok = False
                        reason.append("Your best lap time is too slow: %s > %s" % (format_time_ms(pbTime, False),format_time_ms(maxTime, False)))
                else:
                    ok = False
                    reason.append("You don't have a best lap required for this server.")
            if not maxRank is None:
                if len(pb['laps']) > 0 and pb['laps'][0]['guid'] == guid:
                    pbRank = pb['laps'][0]['pos']
                    if pbRank > maxRank:
                        ok = False
                        reason.append("Your qualification rank is not sufficient: %d > %d" % (pbRank, maxRank))
                else:
                    ok = False
                    reason.append("You don't have a best lap required for this server.")
            if not minNumLaps is None:
                if len(pb['laps']) > 0 and pb['laps'][0]['guid'] == guid:
                    numLaps = pb['laps'][0]['numLaps']
                    if numLaps < minNumLaps:
                        ok = False
                        reason.append("You have not done enough laps in this combo: %d < %d" % (numLaps, minNumLaps))
                else:
                    ok = False
                    reason.append("You have not done enough laps in this combo: none < %d" % (minNumLaps))
        if whitelisted and not ok:
            acinfo("Player %s is whitelisted which overrules other authentication procedures.", guid)
            ok = True
            reason = []
        return ok, reason

    def setOnline(self, server_name, guids_online):
        with self.db:
            c = self.db.cursor()
            guids_online = set(guids_online)
            ans = c.execute("SELECT SteamGuid FROM Players WHERE IsOnline=:server_name", locals()).fetchall()
            old_guids = set(map(lambda x: x[0], ans))
            for guid in guids_online - old_guids:
                c.execute("UPDATE Players SET IsOnline=:server_name WHERE SteamGuid=:guid", locals())
            for guid in old_guids - guids_online:
                c.execute("UPDATE Players SET IsOnline=NULL WHERE SteamGuid=:guid", locals())

    def csGetSeasons(self, cs_id = None):
        with self.db:
            c = self.db.cursor()
            ans = c.execute("SELECT CSId,CSName FROM CSSeasons ORDER BY CSId DESC", locals()).fetchall()
            seasons = []
            events = None
            for a in ans:
                seasons.append(dict(id=a[0], name=a[1]))
            point_schemata = []
            ans = c.execute("SELECT PointSchemaId,PSName FROM CSPointSchema ORDER BY PointSchemaId DESC", locals()).fetchall()
            for a in ans:
                point_schemata.append(dict(pointSchemaId=a[0], psName=a[1]))
            for ps in point_schemata:
                psid = ps['pointSchemaId']
                ans = c.execute("SELECT Position,Points FROM CSPointSchemaEntry WHERE PointSchemaId = :psid", locals()).fetchall()
                schema = {}
                for a in ans:
                    if not a[0] is None and not a[1] is None:
                        schema[a[0]] = a[1]
                ps['schema'] = schema
                ans = c.execute("SELECT COUNT(*) FROM CSEventSessions WHERE PointSchemaId=:psid", locals()).fetchone()
                ps['removable'] = ans is None or (ans[0] == 0)
            if not cs_id is None:
                ans = c.execute("SELECT EventId,EventName FROM CSEvent WHERE CSId = :cs_id ORDER BY EventId DESC", locals()).fetchall()
                events = []
                for a in ans:
                    events.append(dict(id=a[0], name=a[1]))
                players = {}
                teams = {}
                for e in events:
                    eid = e['id']
                    ans = c.execute("""
                        SELECT CSEventSessionId,SessionId,PointSchemaId,SessionType,Duration,NumberOfLaps,StartTimeDate,EndTimeDate,PSName,SessionName
                        FROM CSEventSessions NATURAL JOIN Session NATURAL JOIN CSPointSchema
                        WHERE EventId = :eid
                        ORDER BY CSEventSessionId
                    """, locals()).fetchall()
                    sessions = []
                    startTime = None
                    endTime = None
                    for a in ans:
                        sessions.append(dict(eventSessionId=a[0],
                                             sessionId=a[1],
                                             pointSchemaId=a[2],
                                             sessionType=a[3],
                                             duration=a[4],
                                             numberOfLaps=a[5],
                                             startTime=a[6],
                                             endTime=a[7],
                                             psName=a[8],
                                             sessionName=a[9]))
                        if startTime is None or (not a[6] is None and a[6] < startTime):
                            startTime = a[6]
                        if endTime is None or (not a[7] is None and a[7] > endTime):
                            endTime = a[7]
                    e['startTime'] = startTime
                    e['endTime'] = endTime
                    e['sessions'] = sessions
                    for s in sessions:
                        sid = s['sessionId']
                        psid = s['pointSchemaId']
                        ans = c.execute("""
                            SELECT SteamGuid,Name,PlayerId,Position,Points,DeltaPoints,Teams.TeamId,TeamName
                            FROM Session
                                 NATURAL JOIN PlayerInSession
                                 NATURAL JOIN Players
                                 LEFT JOIN CSPointSchemaEntry ON (PlayerInSession.FinishPosition = CSPointSchemaEntry.Position)
                                 NATURAL LEFT JOIN PisCorrections
                                 LEFT JOIN Teams ON (PlayerInSession.TeamId = Teams.TeamId)
                            WHERE SessionId = :sid AND (CSPointSchemaEntry.PointSchemaId IS NULL OR CSPointSchemaEntry.PointSchemaId = :psid)
                            ORDER BY PlayerInSession.FinishPosition
                        """, locals()).fetchall()
                        classment = []
                        teamClassment = {}
                        for a in ans:
                            guid = a[0]
                            name = a[1]
                            pid = a[2]
                            pos = a[3]
                            points = a[4]
                            delta_points = a[5]
                            teamId = a[6]
                            teamName = a[7]
                            if points is None and delta_points is None:
                                continue
                            if not pid in players:
                                players[pid] = dict(name=name, guid=guid, cum_points=0, teams=set())
                            if points is None:
                                points = 0
                            if delta_points is None:
                                delta_points = 0
                            points += delta_points
                            players[pid]['cum_points'] += points
                            players[pid]['teams'].add(teamName if not teamName is None else "(none)")
                            classment.append( (pid, pos, points) )
                            if not teamId is None:
                                if not teamId in teams:
                                    teams[teamId] = dict(name=teamName, cum_points=0)
                                teams[teamId]['cum_points'] += points
                                if not teamId in teamClassment:
                                    teamClassment[teamId] = 0
                                teamClassment[teamId] += points
                        teamClassment = sorted(teamClassment.items(), key=lambda x: x[1], reverse=True)
                        res = []
                        for i,tci in enumerate(teamClassment):
                            res.append( (tci[0], i+1, tci[1]) )
                        s['classment'] = classment
                        s['teamClassment'] = res
                # players is a dict mapping player ids to a dict with cum_points, name and guid
                # next line converts this into a list of dicts with cum_points, name, guid and playerid
                players = list(map(lambda x: dict(list(x[1].items()) + [('pid',x[0])]), players.items()))
                # sort in descending cum_points order
                players.sort(key=lambda x: x['cum_points'], reverse=True)

                # same for teams
                teams = list(map(lambda x: dict(list(x[1].items()) + [('pid',x[0])]), teams.items()))
                teams.sort(key=lambda x: x['cum_points'], reverse=True)

            else:
                ans = c.execute("""
                    SELECT EventId,CSName||':'||EventName,CSId FROM
                    CSEvent NATURAL JOIN CSSeasons
                    ORDER BY EventId DESC
                """, locals()).fetchall()
                events = []
                for a in ans:
                    events.append(dict(id=a[0], name=a[1], cs_id=a[2]))
                players = None
                teams = None

            return dict(seasons=seasons, events=events, point_schemata=point_schemata, players=players, teams=teams)

    def csModify(self,
                 add_season_name=None, del_season=None, cs_id=None,
                 add_event_name=None, del_event=None,
                 add_schema_name=None, del_schema=None,
                 pos=None, points=None, ps_id=None, delpos=None,
                 add_session_name=None, event_id=None, session_id=None,
                 remove_event_session_id=None):
        with self.db:
            c = self.db.cursor()
            if not add_season_name is None:
                c.execute("INSERT INTO CSSeasons(CSName) VALUES(:add_season_name)", locals())
                return c.lastrowid
            if not del_season is None:
                c.execute("""DELETE FROM CSEventSessions WHERE EventId IN
                                (SELECT EventId
                                 FROM CSEventSessions NATURAL JOIN CSEvent
                                 WHERE CSId = :del_season)""", locals())
                c.execute("DELETE FROM CSEvent WHERE CSId = :del_season", locals())
                c.execute("DELETE FROM CSSeasons WHERE CSId = :del_season", locals())
                return
            if not add_event_name is None:
                c.execute("INSERT INTO CSEvent(CSId,EventName) VALUES(:cs_id,:add_event_name)", locals())
                return c.lastrowid
            if not del_event is None:
                c.execute("DELETE FROM CSEventSessions WHERE EventId=:del_event", locals())
                c.execute("DELETE FROM CSEvent WHERE EventId=:del_event", locals())
                return
            if not add_schema_name is None:
                c.execute("INSERT INTO CSPointSchema(PSName) VALUES(:add_schema_name)", locals())
                return c.lastrowid
            if not del_schema is None:
                c.execute("DELETE FROM CSPointSchemaEntry WHERE PointSchemaId=:del_schema", locals())
                c.execute("DELETE FROM CSPointSchema WHERE PointSchemaId=:del_schema", locals())
                return
            if not pos is None and not points is None and not ps_id is None:
                # check if there is already an entry for this position
                ans = c.execute("""
                    SELECT PointSchemaEntryId FROM CSPointSchemaEntry
                    WHERE Position=:pos AND PointSchemaId=:ps_id
                """, locals()).fetchone()
                if not ans is None:
                    pse_id = ans[0]
                    c.execute("UPDATE CSPointSchemaEntry SET Points = :points WHERE PointSchemaEntryId = :pse_id", locals())
                else:
                    c.execute("INSERT INTO CSPointSchemaEntry(PointSchemaId,Position,Points) VALUES(:ps_id,:pos,:points)", locals())
                return
            if not delpos is None and not ps_id is None:
                c.execute("DELETE FROM CSPointSchemaEntry WHERE Position = :delpos AND PointSchemaId = :ps_id", locals())
                return
            if not add_session_name is None and not event_id is None and not ps_id is None and not session_id is None:
                c.execute("""INSERT INTO CSEventSessions(EventId,SessionId,PointSchemaId,SessionName)
                             VALUES(:event_id,:session_id,:ps_id,:add_session_name)""", locals())
                return
            if not remove_event_session_id is None:
                c.execute("DELETE FROM CSEventSessions WHERE CSEventSessionId = :remove_event_session_id", locals())
                return

    def csSetTeamName(self, cs_id, pid, team_name):
        with self.db:
            cur = self.db.cursor()
            if team_name is None:
                teamId = None
            else:
                team_name = team_name.strip()
                cur.execute("""
                    INSERT INTO Teams(TeamName)
                    SELECT :team_name
                    WHERE NOT EXISTS (SELECT 1 FROM Teams WHERE TeamName=:team_name)
                """, locals())
                teamId = cur.execute("SELECT TeamId FROM Teams WHERE TeamName=:team_name", locals()).fetchone()[0]
            cur.execute("""
                UPDATE PlayerInSession SET TeamId=:teamId
                WHERE PlayerInSessionId IN
                    (SELECT PlayerInSessionId FROM
                     CSEventSessions NATURAL JOIN CSEvent
                                     NATURAL JOIN Session
                                     NATURAL JOIN PlayerInSession
                     WHERE CSId=:cs_id AND PlayerId=:pid
                    )
            """, locals())

    def modifyLap(self, lapid, valid):
        with self.db:
            c = self.db.cursor()
            c.execute("UPDATE Lap SET Valid=:valid WHERE LapId=:lapid", locals())

    def modifyRequiredChecksums(self, track = None, reqTrackChecksum = None, car = None, reqCarChecksum = None):
        with self.db:
            c = self.db.cursor()
            if not track is None:
                c.execute("UPDATE Tracks SET RequiredTrackChecksum=:reqTrackChecksum WHERE Track=:track", locals())
            if not car is None:
                c.execute("UPDATE Cars SET RequiredCarChecksum=:reqCarChecksum WHERE Car=:car", locals())

    def getRequiredChecksums(self):
        with self.db:
            c = self.db.cursor()
            ans = c.execute("SELECT Track,RequiredTrackChecksum FROM Tracks").fetchall()
            trackres = {}
            for a in ans:
                trackres[a[0]] = a[1]
            ans = c.execute("SELECT Car,RequiredCarChecksum FROM Cars").fetchall()
            carres = {}
            for a in ans:
                carres[a[0]] = a[1]
            return {'tracks':trackres, 'cars':carres}

    def statistics(self, servers=None, startDate=None, endDate=None, cars=None, tracks=None, invalidate_laps=False):
        with self.db:
            res = {}
            c = self.db.cursor()
            trackMapping=self.trackMapping(c)
            carMapping=self.carMapping(c)

            conditions = []
            if endDate is None:
                endDate = int(datetime2unixtime(datetime.datetime.now()))
            if startDate is None:
                startDate = endDate - 3*30*24*60*60
            conditions.append("Session.StartTimeDate >= %d AND Session.StartTimeDate <= %d" % ((startDate), (endDate)))
            list_to_str = lambda l: ",".join(["'" + x.replace("'", "") + "'" for x in l])
            if not servers is None:
                conditions.append("Session.ServerIpPort IN (%s)" % list_to_str(servers))
            if not cars is None:
                conditions.append("PlayerInSession.CarId IN (SELECT CarId FROM Cars WHERE Car IN (%s))" % list_to_str(cars))
            if not tracks is None:
                conditions.append("Session.TrackId IN (SELECT TrackId FROM Tracks WHERE Track IN (%s))" % list_to_str(tracks))

            cond = " AND ".join(conditions)
            if cond != "":
                cond = "WHERE " + cond

            if invalidate_laps:
                c.execute("""
                    UPDATE Lap SET Valid=0 WHERE LapId IN
                        (SELECT LapId FROM
                            Lap NATURAL JOIN
                            PlayerInSession NATURAL JOIN
                            Session NATURAL JOIN
                            Tracks
                         %(cond)s)
                """ % locals())

            ans = c.execute("SELECT COUNT(*), SUM(length)/1000. FROM Lap NATURAL JOIN PlayerInSession NATURAL JOIN Session NATURAL JOIN Tracks %(cond)s" % locals()).fetchone()
            res['numLaps'] = ans[0]
            res['kmDriven'] = ans[1]

            trackIds = c.execute("""
                SELECT TrackId,Track,Cnt FROM
                (
                	SELECT TrackId,COUNT(LapId) AS Cnt
                	FROM Lap
                		NATURAL JOIN PlayerInSession
                		NATURAL JOIN Session
                    %(cond)s
                	GROUP BY TrackId
                ) AS Tmp NATURAL JOIN Tracks""" % locals() ).fetchall()
            res['lapsPerTrack'] = {}
            for tid,tname,nLaps in trackIds:
                res['lapsPerTrack'][trackMapping.get(tname,tname)] = nLaps
            carIds = c.execute("""
                SELECT CarId,Car,Cnt FROM
                (
                	SELECT CarId,COUNT(LapId) AS Cnt
                	FROM Lap
                		NATURAL JOIN PlayerInSession
                        NATURAL JOIN Session
                    %(cond)s
                	GROUP BY CarId
                ) AS Tmp NATURAL JOIN Cars""" % locals() ).fetchall()
            res['lapsPerCar'] = {}
            for cid,cname,nLaps in carIds:
                res['lapsPerCar'][carMapping.get(cname,cname)] = nLaps
            comboIds = c.execute("""
                SELECT ComboId, COUNT(LapId) AS Cnt
                FROM Lap NATURAL JOIN PlayerInSession NATURAL JOIN Session
                %(cond)s
                GROUP BY ComboId
                ORDER BY Cnt DESC
            """ % locals() ).fetchall()
            res['lapsPerCombo'] = {}
            for comboId, nLaps in comboIds:
                res['lapsPerCombo'][comboId] = {}
                res['lapsPerCombo'][comboId]['lapCount'] = nLaps
                res['lapsPerCombo'][comboId]['track'] = c.execute("SELECT Track FROM Tracks NATURAL JOIN Combos WHERE Combos.ComboId = :comboId", locals()).fetchone()[0]
                res['lapsPerCombo'][comboId]['uitrack'] = trackMapping.get(res['lapsPerCombo'][comboId]['track'],res['lapsPerCombo'][comboId]['track'])
                res['lapsPerCombo'][comboId]['cars'] = [x[0] for x in c.execute("SELECT Car FROM Cars NATURAL JOIN ComboCars WHERE ComboId = :comboId ORDER BY Car", locals()).fetchall()]
                res['lapsPerCombo'][comboId]['uicars'] = [carMapping.get(x, x) for x in res['lapsPerCombo'][comboId]['cars']]
            res['recentCombos'] = []
            for comboId,startTD in c.execute("""
                        SELECT ComboId, Max(StartTimeDate) AS StartTimeDate
                        FROM Session NATURAL JOIN PlayerInSession
                        %(cond)s
                        GROUP BY ComboId
                        ORDER BY StartTimeDate DESC
                    """ % locals()).fetchall():
                res['recentCombos'].append( (comboId, startTD) )

            res['numPlayers'] = c.execute("SELECT COUNT(*) FROM Players").fetchone()[0]
            now = unixtime_now()
            res['bannedPlayers'] = c.execute("""
                SELECT COUNT(*) FROM BlacklistedPlayers
                WHERE NOT BannedUntil IS NULL AND BannedUntil >= :now
                """, locals()).fetchone()[0]
            ppd = c.execute("""
                SELECT Day,COUNT(PlayerId) FROM (
                    SELECT (StartTimeDate/(60*60*24)) AS Day,PlayerId
                    FROM PlayerInSession NATURAL JOIN Session
                    %(cond)s
                    GROUP BY Day,PlayerId
                    ORDER BY Day
                ) AS Tmp GROUP BY Day
                """ % locals() ).fetchall()
            res['numPlayersOnlinePerDay'] = []
            for day,cnt in ppd:
                res['numPlayersOnlinePerDay'].append(dict(datetime=unixtime2datetime(day*60*60*24), count=cnt))
            return res

    def trackAndCarDetails(self, tracks = None, cars = None, overwrite = False):
        with self.db:
            cur = self.db.cursor()
            if overwrite:
                cond = 0
            else:
                cond = 1
            if not tracks is None:
                for t in tracks:
                    e = cur.execute("SELECT Track FROM Tracks WHERE Track=:track", t).fetchone()
                    if e is None:
                        cur.execute("INSERT INTO Tracks(Track) VALUES (:track)", t)
                    if "uiname" in t:  cur.execute("UPDATE Tracks SET UiTrackName=:uiname WHERE Track=:track" + (" AND UiTrackName IS NULL")*cond, t)
                    if "length" in t:  cur.execute("UPDATE Tracks SET Length=:length WHERE Track=:track" + (" AND Length IS NULL")*cond, t)
                    if "mapdata" in t: cur.execute("UPDATE Tracks SET MapData=:mapdata WHERE Track=:track" + (" AND MapData IS NULL")*cond, t)
            if not cars is None:
                for c in cars:
                    e = cur.execute("SELECT Car FROM Cars WHERE Car=:car", c).fetchone()
                    if e is None:
                        cur.execute("INSERT INTO Cars(Car) VALUES (:car)", c)
                    if "uiname" in c: cur.execute("UPDATE Cars SET UiCarName=:uiname WHERE Car=:car" + (" AND UiCarName IS NULL")*cond, c)
                    if "brand" in c:  cur.execute("UPDATE Cars SET Brand=:brand WHERE Car=:car" + (" AND Brand IS NULL")*cond, c)
                    if "badge" in c:  cur.execute("UPDATE Cars SET BadgeData=:badge WHERE Car=:car" + (" AND BadgeData IS NULL")*cond, c)
            cur.execute("SELECT Track,UiTrackName,Length,Length(MapData) > 0 FROM Tracks ORDER BY UiTrackName,Track")
            tracks = list(map(lambda x: dict(acname=x[0], uiname=x[1], length=x[2], mapdata=x[3]), cur.fetchall()))
            cur.execute("SELECT Car,UiCarName,Brand,Length(BadgeData) > 0 FROM Cars ORDER BY UiCarName,Car")
            cars = list(map(lambda x: dict(acname=x[0], uiname=x[1], brand=x[2], badge=x[3]), cur.fetchall()))
            return dict(tracks=tracks, cars=cars)

    def trackMap(self, track):
        with self.db:
            cur = self.db.cursor()
            cur.execute("SELECT MapData FROM Tracks WHERE Track=:track", locals())
            r = cur.fetchone()
            return bytes(r[0]) if not r is None else None

    def carBadge(self, car):
        with self.db:
            cur = self.db.cursor()
            cur.execute("SELECT BadgeData FROM Cars WHERE Car=:car", locals())
            r = cur.fetchone()
            return bytes(r[0]) if not r is None else None

    def trackMapping(self, c):
        c.execute("SELECT Track,UiTrackName FROM Tracks")
        res = {}
        for i in c.fetchall():
            res[i[0]] = i[0] if i[1] is None else i[1]
        return res

    def carMapping(self, c):
        c.execute("SELECT Car,UiCarName FROM Cars")
        res = {}
        for i in c.fetchall():
            res[i[0]] = i[0] if i[1] is None else i[1]
        return res

    def getOrCreateComboId(self, c, trackId, carIdList):
        if type(trackId) == str:
            c.execute("SELECT TrackId From Tracks WHERE Track = :trackId", locals())
            trackId = c.fetchone()[0]
        carIds = []
        for cid in carIdList:
            if type(cid) == str:
                c.execute("SELECT CarId FROM Cars WHERE Car = :cid", locals())
                cid = c.fetchone()[0]
            carIds.append(cid)
        carIdsStr = ",".join([str(cid) for cid in sorted(carIds)])
        c.execute("SELECT ComboId FROM ComboView WHERE TrackId = :trackId AND CarIds = :carIdsStr", locals())
        comboId = c.fetchone()
        if not comboId is None:
            return comboId[0]
        c.execute("SELECT Max(ComboId) FROM Combos")
        max_id = c.fetchone()
        if not max_id is None: max_id = max_id[0]
        if max_id is None: max_id = 0
        comboId = max_id + 1
        acdebug("create combo comboId=%d trackId=%d carIds=%s", comboId, trackId, carIds)
        c.execute("INSERT INTO Combos (ComboId,TrackId) VALUES(:comboId, :trackId)", locals())
        for cid in carIds:
            c.execute("INSERT INTO ComboCars (ComboId,CarId) VALUES(:comboId, :cid)", locals())
        return comboId

    def queryFuelConsumption(self, trackname, carname):
        with self.db:
            c = self.db.cursor()
            c.execute("DROP TABLE IF EXISTS FuelTemp")
            c.execute("""

                CREATE TEMP TABLE FuelTemp AS
                		 SELECT FuelRatio, LapCount,PlayerInSessionId FROM Lap NATURAL JOIN PlayerInSession NATURAL JOIN Session
                		 WHERE
			                 PlayerInSessionId IN (SELECT MAX(PlayerInSessionId)
												   FROM (
												            SELECT PlayerInSessionId, COUNT(*) AS Count FROM Lap NATURAL JOIN PlayerInSession NATURAL JOIN Session
															WHERE CarId IN (SELECT CarId FROM Cars WHERE Car = :carname)
																  AND TrackId IN (SELECT TrackId FROM Tracks WHERE Track = :trackname)
																  AND FuelRatio >= 0.0
															GROUP BY PlayerInSessionId)
												   WHERE Count >= 2)
                		 ORDER BY LapCount
            """, locals())
            a = c.execute("""
                SELECT AVG(R.FuelRatio - L.FuelRatio), COUNT(*) FROM
                	FuelTemp AS L LEFT JOIN FuelTemp AS R
                	WHERE L.LapCount = R.LapCount+1 AND R.PlayerInSessionId = L.PlayerInSessionId AND R.FuelRatio > L.FuelRatio
            """, locals()).fetchone()
            if not a is None and not a[0] is None:
                acdebug("average fuel consumption per lap: %.1f %%", a[0]*100.)
                return a[0]
            else:
                acdebug("average fuel consumption not available")

    def recordChat(self, guid, name, message, server):
        with self.db:
            cur = self.db.cursor()
            now = unixtime_now()
            ans = cur.execute("SELECT PlayerId FROM Players WHERE SteamGUID = :guid", locals()).fetchone()
            if ans is None:
                cur.execute("INSERT INTO Players(SteamGuid, Name) VALUES(:guid, :name)", locals())
                pid = cur.lastrowid
            else:
                pid = ans[0]
            cur.execute("INSERT INTO ChatHistory(PlayerId, Timestamp, Content, Server) VALUES(:pid, :now, :message, :server)", locals())

    def filterChat(self, guid = None, server = None, startTime = None, endTime = None, limit = None):
        with self.db:
            cur = self.db.cursor()
            search = []
            if not guid is None:
                search.append("PlayerId IN (SELECT PlayerId FROM Players WHERE SteamGuid=:guid)")
            if not server is None:
                search.append("Server=:server")
            if not startTime is None:
                search.append("Timestamp >= :startTime")
            if not endTime is None:
                search.append("Timestamp <= :endTime")
            search = " AND ".join(search)
            if search != '': search = "WHERE " + search
            count = cur.execute("SELECT COUNT(*) FROM ChatHistory %(search)s" % locals(), locals()).fetchone()[0]
            if limit is None:
                limit = [1, count]
            limitOffset = limit[0]
            limitNum = limit[1]
            if limitOffset is None:
                limitOffset = 0
            elif limitOffset < 1:
                limitOffset = 0
            else:
                limitOffset -= 1 # position to index
            slimit = "LIMIT :limitNum OFFSET :limitOffset"
            cur.execute("""
                SELECT Name, Timestamp, Content, PlayerId FROM ChatHistory NATURAL JOIN Players
                %(search)s
                ORDER BY Timestamp DESC
                %(slimit)s
            """ % locals(), locals())
            desc = cur.description
            ans = cur.fetchall()
            res = []
            for r in ans:
                line = {}
                for i,v in enumerate(r):
                    line[desc[i][0].lower()] = v
                res.append(line)
            return {'messages' : res, 'totalCount': count}

    def populate(self, other):
        def arg_list(n):
            return (','.join([':%d']*n)) % tuple(range(n))
        with other.db:
            other_cur = other.db.cursor()
            with self.db:
                cur = self.db.cursor()
                tables = other.tables(cur=other_cur)
                for table in tables:
                    if not (len(cur.execute("SELECT * FROM " + table).fetchall()) == 0):
                        raise RuntimeError("Table %s is not empty. Cannot migrate to non-empty database!" % table)
                self.deferr_foreign_key_constraints(cur)
                for table in sorted(tables):
                    acinfo("populating %s", table)
                    other_cur.execute('SELECT * FROM ' + table)
                    for row in other_cur.fetchall():
                        # bypass the :<name> substitution
                        stmt = 'INSERT INTO ' + table + ' VALUES(' + arg_list(len(row)) + ')'
                        mrow = tuple(map(lambda x: [x, None][x == float('inf')], row))
                        try:
                            cur.execute(stmt, mrow)
                        except:
                            acerror("statement: %s", stmt)
                            for i,p in enumerate(row):
                                acerror("  parameter: type %s %s -> %s", type(p), repr(p), repr(mrow[i]))
                            raise
                self.postPopulate(cur)

    def compressDB(self, mode, steamGuid=None):
        # create the compress index if not exists
        try:
            with self.db:
                cur = self.db.cursor()
                cur.execute("CREATE INDEX IdxCompressLapTime ON Lap(LapTime,PlayerInSessionId,Valid)")
        except (KeyboardInterrupt, SystemExit):
            raise
        except:
            # we assume that the index already exists
            pass
        with self.db:
            cur = self.db.cursor()
            if mode == COMPRESS_DELETE_ALL:
                tables = self.tables(cur)
                # make sure we delete the foreign key tables first
                tables = ["Lap", "PlayerInSession", "Session", "SetupDeposit", "ComboCars", "Combos"] + tables
                for t in tables:
                    cur.execute("DELETE FROM %(t)s" % locals())
            elif mode == COMPRESS_NULL_ALL_BINARY_BLOBS:
                cur.execute("UPDATE LapBinBlob SET HistoryInfo = NULL")
            elif mode == COMPRESS_NULL_ALL_BINARY_BLOBS_EXCEPT_GUID:
                cur.execute("UPDATE LapBinBlob SET HistoryInfo = NULL WHERE LapId NOT IN (SELECT LapId FROM LapTimes WHERE SteamGuid=:steamGuid)", locals())
            elif mode == COMPRESS_NULL_SLOW_BINARY_BLOBS:
                timenow = unixtime2datetime(unixtime_now())
                thresh_1day = int(datetime2unixtime(timenow - datetime.timedelta(days=1)))
                thresh_2days = int(datetime2unixtime(timenow - datetime.timedelta(days=2)))
                thresh_5days = int(datetime2unixtime(timenow - datetime.timedelta(days=5)))
                thresh_1wk = int(datetime2unixtime(timenow - datetime.timedelta(days=7)))
                thresh_1month = int(datetime2unixtime(timenow - datetime.timedelta(days=31)))
                thresh_1year = int(datetime2unixtime(timenow - datetime.timedelta(days=365)))
                cur.execute("""
                    WITH CompressHelper AS (
                       SELECT MIN(LapTime) AS LapTime,
                              PlayerInSession.PlayerId AS PlayerId,
                              PlayerInSession.CarId AS CarId,
                              Session.TrackId AS TrackId,
                              Valid,
                              CASE WHEN StartTimeDate >= :thresh_1day THEN 1
                                   WHEN StartTimeDate >= :thresh_2days THEN 2
                                   WHEN StartTimeDate >= :thresh_5days THEN 3
                                   WHEN StartTimeDate >= :thresh_1wk THEN 4
                                   WHEN StartTimeDate >= :thresh_1month THEN 5
                                   WHEN StartTimeDate >= :thresh_1year THEN 6
                                   ELSE 7
                              END AS DateTimeClass
                       FROM Lap JOIN PlayerInSession ON (Lap.PlayerInSessionId=PlayerInSession.PlayerInSessionId)
                                JOIN Session ON (PlayerInSession.SessionId=Session.SessionId)
                       GROUP BY PlayerId,CarId,TrackId,Valid,DateTimeClass
                    )
                    UPDATE LapBinBlob SET HistoryInfo=NULL
                    WHERE LapId NOT IN (SELECT LapId FROM Lap NATURAL JOIN PlayerInSession
                                                              NATURAL JOIN Session
                                                              JOIN CompressHelper ON
                                                                (CompressHelper.LapTime=Lap.LapTime AND
                                                                 CompressHelper.PlayerId=PlayerInSession.PlayerId AND
                                                                 CompressHelper.TrackId=Session.TrackId AND
                                                                 CompressHelper.Valid=Lap.Valid))
                """, locals())
            self.postCompress(cur)
        self.postCompress(None)
        return True
