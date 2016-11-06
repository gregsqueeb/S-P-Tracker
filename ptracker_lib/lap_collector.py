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
import bisect
import copy
import collections
import math
import os.path
import re
import time
from ptracker_lib import acsim
from ptracker_lib.helpers import *
try:
    import acsys
    from ptracker_lib.config import config
except ImportError:
    # usage with stracker doesn't require acsys (hopefully?)
    acsys = None
    config = None

jump_delta = 20. # 20m city block distance threshold for checking for plausible motions of cars

def interpolate(x, x0, x1, y0, y1):
    f = (x-x0)/(x1-x0)
    if isinstance(y0, collections.Iterable):
        return [(1-f)*v0 + f*v1 for (v0,v1) in zip(y0, y1)]
    else:
        return (1-f)*y0 + f*y1

class LapCollectorItem:
    def __init__(self, **kw):
        for k in kw:
            setattr(self, k, kw[k])

    def copy(self):
        return copy.copy(self)

class BisectOnListAttr:
    def __init__(self, l, attr):
        self.l = l
        self.attr = attr

    def __getitem__(self, idx):
        return getattr(self.l[idx], self.attr)

    def __len__(self):
        return len(self.l)

tyre_re = re.compile(r'\((\w+)\)')
tyre_dict = {}

class LapCollector:

    def __init__(self, ptracker = None, carId = -1, guid = None, isAI = -1):
        self.carId = carId
        self.guid = guid
        self.server_guid = None
        self.isAI = isAI
        self.unplausibleVelocity = (500/3.6)*(500/3.6)
        self.ptracker = ptracker
        self.init()
        acdebug("LC %d: created new lc instance for name=%s", carId, self.name)

    def init(self):
        if not config is None:
            if self.carId == 0:
                self.delta_t_ms = 1000./config.GLOBAL.save_samples_per_second_self
            else:
                self.delta_t_ms = 1000./config.GLOBAL.save_samples_per_second_other
        else:
            self.delta_t_ms = 1000.
        if not acsys is None:
            self.name = acsim.ac.getDriverName(self.carId)
            self.carName = acsim.ac.getCarName(self.carId)
        else:
            self.name = "<unknown>"
            self.carName = None
        if type(self.carName) == type(""):
            self.badge = os.path.join("content", "cars", self.carName, "ui", "badge.png")
            acdebug("LC %d: badge=%s", self.carId, self.badge)
        else:
            self.badge = None
        self.team = ""
        self.tyre = None
        self.isRecordLap = False
        self.samples = []
        self.sectorTimeHistory = {} # {lapIdx : [sector1, sector2, ...]}
        self.sectorTimes = []
        self.sectorsUpdated = False
        self.lapTimeHistory = {} # {lapIdx : lapTime}
        self.lapsUpdated = False
        self.lastLapTime = None
        self.lastLapOffset = None
        self.newLapDetected = False
        self.abEntryDetected = False
        self.possibleTspCorrection = 0
        self.tspCorrectionVotes = 0
        self.leaderboardIndex = None
        self.carsCount = 64
        self.inactivePosition = None
        self.inactiveVelocity = None
        self.inactiveCounter = 0
        self.activeCounter = 0
        self.maxLapSpeed = 0.0
        self.notDriving = True
        self.delta_self = 0
        self.delta_self_filtered = 0
        self.delta_self_alpha = 1.
        self.delta_self_2nd = 0
        self.LIVE = 0
        self.TRIGGERED = 1
        self.showCountdown = 0
        self.sectorsWorking = False
        self.raceFinished = False
        self.raceFinishedSince = 0.0
        self.bestLapTime = None
        self.lastLapHistory = None
        self.strackerLapCount = None
        self.lapCountOffset = 0
        self.lapValid = (self.carId == 0) # the first lap of opponents will be invalid
        self.lastTimeInPitLane = 0
        self.lastTimeInPit = 0
        self.pitLaneEnterTimestamp = None
        self.pitLaneLeaveTimestamp = None
        self.pitEnterTimestamp = None
        self.pitLeaveTimestamp = None
        self.connected = False
        self.server_guid = None
        self.jerkyMotionCounter = 0
        acdebug("LC %d: Initializing %s", self.carId, self.name)

    def playerId(self):
        return (self.guid, self.name, self.isAI)

    def currentSector(self):
        return (len(self.lapTimeHistory), len(self.sectorTimeHistory.get(len(self.lapTimeHistory), [])))

    def active(self):
        if not(type(self.name) == type("") and self.name != ""):
            return False
        if not self.carsCount is None and not self.leaderboardIndex is None and self.leaderboardIndex >= self.carsCount:
            return False
        if not self.connected:
            return False
        return True

    def setDelta(self, delta, triggerMode):
        if triggerMode == self.LIVE:
            self.delta_self_filtered = self.delta_self_filtered * (1.-self.delta_self_alpha) + delta * self.delta_self_alpha
            self.delta_self_alpha = max(1./config.CONFIG_RACE.delta_2nd_deriv_filter_strength, 1./((1./self.delta_self_alpha)+1.))
            self.delta_self = delta
        elif triggerMode == self.TRIGGERED:
            self.delta_self_filtered = self.delta_self
            self.delta_self = delta
        self.delta_self_2nd = self.delta_self - self.delta_self_filtered

    def splitTimes(self, num_sectors):
        s = 0
        res = []
        valid = True
        for k in range(len(self.sectorTimes)):
            valid = valid and not self.sectorTimes[k] is None
            if not self.sectorTimes[k] is None and self.sectorTimes[k] > 0:
                s += self.sectorTimes[k]
            if valid:
                res.append(s)
        if len(res) == 0 and not self.lastLapTime is None and self.lastLapTime > 0:
            while len(res) < num_sectors:
                res.append(None)
            res[num_sectors-1] = self.lastLapTime
        return res

    def update(self, sim_info_obj, lapCollectorSelf, softTspSectors, deltaT, server_data):
        self.lastLapHistory = None
        self.sectorsUpdated = False
        self.lapsUpdated = False
        self.newLapDetected = False
        self.abEntryDetected = False
        self.connected = acsim.ac.isConnected(self.carId)
        if self.connected and acsim.ac.getDriverName(self.carId) != self.name:
            self.init()
            acdebug("LC %d: name changed to %s, reinit", self.carId, self.name)
        if self.raceFinished:
            self.raceFinishedSince += deltaT
            acdump("LC %d: %s: raceFinished, return", self.carId, self.name)
            return
        try:
            self.updateActivity()
        except AssertionError:
            acdump("LC %d: Assertion error on updateActivity (%s)", self.carId, self.name)
            return
        if not self.active() or self.notDriving:
            acdump("LC %d: driver %s is inactive. Ignoring", self.carId, self.name)
            return
        self.updateSamples(sim_info_obj, lapCollectorSelf, softTspSectors)
        self.updateLaps(sim_info_obj)
        self.updateSectors(sim_info_obj, softTspSectors)
        self.updatePitInfo()
        self.updateServerData(server_data, sim_info_obj)

    def updateServerData(self, sd, sim_info_obj):
        self.team = sd.get('team', "")
        if self.carId == 0:
            t = sim_info_obj.graphics.tyreCompound
        else:
            t = sd.get('tyre', "")
        default_tyre = os.path.join("apps", "python", "ptracker", "images", "tyre_unknown.png")
        M = tyre_re.search(t)
        if not M is None:
            tc = M.group(1).lower()
        else:
            tc = ''
        if not tc in tyre_dict:
            tyre_dict[tc] = os.path.join("apps", "python", "ptracker", "images", "tyre_"+tc.lower()+".png")
            if not os.path.exists(tyre_dict[tc]):
                acinfo("tyre '%s' doesn't seem to have an image associated. Using default.", tc)
                tyre_dict[tc] = default_tyre
        self.tyre = tyre_dict[tc]

    def updatePitInfo(self):
        if len(self.samples) == 0:
            return
        timestamp = self.getTotalTime()
        if acsim.ac.isCarInPitlane(self.carId) and self.pitLaneEnterTimestamp is None:
            self.pitLaneEnterTimestamp = timestamp
        if not acsim.ac.isCarInPitlane(self.carId) and not self.pitLaneEnterTimestamp is None:
            self.pitLaneLeaveTimestamp = timestamp
        if acsim.ac.isCarInPit(self.carId) and self.pitEnterTimestamp is None:
            self.pitEnterTimestamp = timestamp
        if not acsim.ac.isCarInPit(self.carId) and not self.pitEnterTimestamp is None:
            self.pitLeaveTimestamp = timestamp
        if not acsim.ac.isCarInPitlane(self.carId):
            if not self.pitLaneEnterTimestamp is None and not self.pitLaneLeaveTimestamp is None:
                self.lastTimeInPitLane = self.pitLaneLeaveTimestamp - self.pitLaneEnterTimestamp
            if not self.pitEnterTimestamp is None and not self.pitLeaveTimestamp is None:
                self.lastTimeInPit = self.pitLeaveTimestamp - self.pitEnterTimestamp
            self.pitLaneEnterTimestamp = None
            self.pitLaneLeaveTimestamp = None
            self.pitEnterTimestamp = None
            self.pitLeaveTimestamp = None

    def updateActivity(self):
        lastNotDriving = self.notDriving
        v = acsim.ac.getCarState(self.carId, acsys.CS.Velocity)
        v = v[0]*v[0] + v[1]*v[1] + v[2]*v[2]
        if (v > self.unplausibleVelocity):
            acdebug("LC %d: Driver %s: velocity plausibilization failed. Ignoring frame", self.carId, self.name)
            myassert(0)
        cPos = acsim.ac.getCarState(self.carId, acsys.CS.WorldPosition)
        cVel = acsim.ac.getCarState(self.carId, acsys.CS.Velocity)
        if cPos != self.inactivePosition or cVel != self.inactiveVelocity:
            self.inactivePosition = cPos
            self.inactiveVelocity = cVel
            self.inactiveCounter = 0
            self.activeCounter += 1
        else:
            self.inactiveCounter += 1
            self.activeCounter = 0
        if lastNotDriving and self.activeCounter > 10:
            self.notDriving = False
            acdump("LC %d: driver %s set to active (%s, %s)", self.carId, self.name, str(cPos), str(cVel))
        elif not lastNotDriving and self.inactiveCounter > 10:
            self.notDriving = True
            acdump("LC %d: driver %s set to inactive (%s, %s)", self.carId, self.name, str(cPos), str(cVel))
        v = math.sqrt(v)
        if v > self.maxLapSpeed:
            self.maxLapSpeed = v
        if self.carId == 0:
            self.notDriving = False
        if self.notDriving != lastNotDriving:
            acdebug("LC %d: Driver %s is now active (%d)", self.carId, self.name, not self.notDriving)
            myassert( len(self.samples) == 0)

    def updateLaps(self, sim_info_obj):
        if not self.ptracker.hasStrackerLaptimes():
            self.bestLapTime = acsim.ac.getCarState(self.carId, acsys.CS.BestLap)
            if self.bestLapTime <= 0: self.bestLapTime = None
        if len(self.samples) >= 1:
            if self.lastLapOffset is None:
                self.lastLapOffset = self.samples[-1].lapOffset
            if self.lastLapOffset != self.samples[-1].lapOffset:
                self.lastLapOffset = self.samples[-1].lapOffset
                lastLap = self.samples[-1].lastLap
                lapIdx = self.samples[-1].lapCount-1
                if lapIdx >= 0 and lastLap > 0:
                    self.lapTimeHistory[lapIdx] = lastLap
                    self.lapsUpdated = True
                    self.lastLapTime = lastLap
                    self.lastLapValid = self.lapValid
                    self.lapValid = True
                    if sim_info_obj.graphics.numberOfLaps > 0 and self.samples[-1].lapCount == sim_info_obj.graphics.numberOfLaps:
                        self.raceFinished = True
                        self.raceFinishedSince = 0.0
                        acinfo("LC %d: Driver %s has finished the race", self.carId, self.name)

    def updateSectors(self, sim_info_obj, softTspSectors):
        sectorCount = sim_info_obj.static.sectorCount
        if not softTspSectors is None and not self.sectorsWorking and len(self.samples) >= 3:
            t1 = 0
            for idx,nspSector in enumerate(softTspSectors[:-1]):
                item = self.samples[-1]
                lastItem = self.samples[-2]
                if item.normSplinePosition >= nspSector + 0.05 > lastItem.normSplinePosition:
                    if idx == 0:
                        t0 = item.lapOffset
                    else:
                        t0 = self.interpolateBetweenSamples("totalSplinePosition", "totalTime", softTspSectors[idx-1] + item.nspOffset, False)
                    t1 = self.interpolateBetweenSamples("totalSplinePosition", "totalTime", nspSector + item.nspOffset, False)
                    if not t0 is None and not t1 is None:
                        self.addSectorTime(idx, int(t1-t0), False, sectorCount)
                    if self.sectorsUpdated:
                        acdebug("LC %d: calculated soft split for %s: %s", self.carId, self.name, self.sectorTimes)
        if self.carId == 0:
            currSectorIndex = sim_info_obj.graphics.currentSectorIndex
            lastSectorTime = sim_info_obj.graphics.lastSectorTime
            if lastSectorTime > 0:
                currSectorIndex -= 1
                if currSectorIndex < 0:
                    currSectorIndex += sectorCount
                self.addSectorTime(currSectorIndex, lastSectorTime, True, sectorCount)
        if (self.lapsUpdated and
            sectorCount > 1 and
            len(self.sectorTimes) == sectorCount - 1 and
            all(map(lambda x: not x is None, self.sectorTimes))):
            # special case if the lap count is changing too slow
            self.sectorTimes.append(self.lastLapTime - sum(self.sectorTimes))
            acdebug("LC %d: Calculated last split for %s: %s", self.carId, self.name, self.sectorTimes)
            self.sectorsUpdated = True

    def addSectorTime(self, currSectorIndex, lastSectorTime, updateSectorsWorking, sectorCount):
        if currSectorIndex >= 0 and currSectorIndex < 30 and len(self.samples):
            currLap = self.samples[-1].lapCount
            lapTime = self.samples[-1].lapTime
            if currSectorIndex == sectorCount - 1:
                currLap -= 1
            if not currLap in self.sectorTimeHistory:
                self.sectorTimeHistory[currLap] = []
            if lapTime < lastSectorTime and not currSectorIndex == sectorCount - 1:
                return
            self.sectorTimes = self.sectorTimeHistory[currLap]
            added = False
            while len(self.sectorTimes) <= currSectorIndex:
                added = True
                self.sectorTimes.append(None)
            if (not lastSectorTime <= 0 and
                (self.sectorTimes[currSectorIndex] is None or
                 self.sectorTimes[currSectorIndex] != lastSectorTime)):
                self.sectorTimes[currSectorIndex] = lastSectorTime
                added = True
            if added:
                acdump("LC %d: added sector time %d of currindex %d -> (%s)", self.carId, lastSectorTime, currSectorIndex, str(self.sectorTimes))
                self.sectorsUpdated = True
                if updateSectorsWorking:
                    self.sectorsWorking = True

    def getTotalTime(self):
        myassert(len(self.samples)>0)
        totalTime = self.samples[-1].totalTime
        if self.raceFinished:
            totalTime += int(self.raceFinishedSince*1000)
        return totalTime

    def getTotalSplinePosition(self):
        if len(self.samples) == 0:
            return 0
        return self.samples[-1].totalSplinePosition

    def updateSamples(self, sim_info_obj, lapCollectorSelf, softTspSectors):
        nsp = acsim.ac.getCarState(self.carId, acsys.CS.NormalizedSplinePosition)
        if self.ptracker.a2b:
            nsp = (nsp + self.ptracker.a2bOffset) % 1.0
        item = LapCollectorItem(
            lapTime = acsim.ac.getCarState(self.carId, acsys.CS.LapTime),
            normSplinePosition = nsp,
            lapCount = acsim.ac.getCarState(self.carId, acsys.CS.LapCount) + self.lapCountOffset,
            lastLap = acsim.ac.getCarState(self.carId, acsys.CS.LastLap),
            worldPosition = acsim.ac.getCarState(self.carId, acsys.CS.WorldPosition),
            velocity = acsim.ac.getCarState(self.carId, acsys.CS.Velocity),
        )

        if len(self.samples) > 0:
            lastItem = self.samples[-1]
        else:
            lastItem = None

        # adapt item's members to respect invalid information
        if self.carId != 0: # and not self.isAI:
            item.lapTime = None

        if sim_info_obj.graphics.status == 1 and self.carId != 0:
            item.lastLap = None
            item.lapCount = None

        acdump("LC(init) %d: lt=%s nsp=%.3f lc=%s ll=%s wp=%s v=%s", self.carId, item.lapTime, item.normSplinePosition, item.lapCount, item.lastLap, item.worldPosition, item.velocity)

        # ac.getCarState(carId, CS.LapCount) is broken for opponents in MP replays
        # -> workaround: cumulate lap count by NSP wraparounds
        if item.lapCount is None:
            if self.lapCountOffset == 0 and len(self.samples) == 0:
                # first item, might be before or after the nsp wraparound point
                if item.normSplinePosition > 0.5:
                    self.lapCountOffset = -1
                else:
                    self.lapCountOffset = 0
            elif len(self.samples) > 0 and item.normSplinePosition < 0.2 and lastItem.normSplinePosition > 0.8:
                self.lapCountOffset += 1
        if item.lapCount is None:
            item.lapCount = max(0, self.lapCountOffset)

        # ac.getCarState(carId, LapTime) is broken for opponents in MP and in MP replays
        # -> workaround: use totaltime from ego lap collector for calculating laptime
        if item.lapTime is None:
            if not self.ptracker.a2b:
                if len(lapCollectorSelf.samples) == 0:
                    # can't work around this, ignore that item
                    return
                item.totalTime = lapCollectorSelf.getTotalTime()
                if len(self.samples) == 0:
                    item.lapTime = item.totalTime
                    item.lapOffset = 0
                else:
                    if lastItem.lapCount < item.lapCount:
                        if not item.lastLap is None:
                            lapOffset = lastItem.lapOffset + item.lastLap
                        elif not softTspSectors is None and not softTspSectors[-1] is None:
                            # try to deduce the total time when the car has crossed the line
                            # using the soft split information
                            # last tsp is referring to finish line
                            tspFinish = softTspSectors[-1]
                            # create a temporary item to be appended to self.samples
                            # just to use the existing interpolation mechanism
                            tmpItem = item.copy()
                            tmpItem.totalTime = item.totalTime
                            tmpItem.totalSplinePosition = lastItem.totalSplinePosition + item.normSplinePosition - lastItem.normSplinePosition
                            if tmpItem.normSplinePosition < 0.2 and lastItem.normSplinePosition > 0.8:
                                tmpItem.totalSplinePosition += 1.
                            tmpAppended = False
                            if tmpItem.totalSplinePosition > lastItem.totalSplinePosition:
                                self.samples.append(tmpItem)
                                tmpAppended = True
                            tspFinish += item.lapCount
                            if tspFinish - self.samples[-1].totalSplinePosition > 0.5:
                                tspFinish -= 1.
                            elif tspFinish - self.samples[-1].totalSplinePosition < -0.5:
                                tspFinish += 1
                            if (tspFinish - self.samples[-1].totalSplinePosition) <= 0.01:
                                lapOffset = self.tAtTsp(tspFinish, True)
                                if lapOffset is None or abs(lapOffset - self.samples[-1].totalTime) > 500:
                                    # if extrapoltaion is too large, use the fallback
                                    lapOffset = lastItem.totalTime
                                    acdump("LC %d: USING FALLBACK FOR SOFT SPLIT ON FINISH LINE (extrapolating %d ms)", self.carId, abs(lapOffset - self.samples[-1].totalTime))
                                lapOffset = int(lapOffset)
                            else:
                                acdump("LC %d: USING FALLBACK FOR SOFT SPLIT ON FINISH LINE (tsp offset too large)", self.carId)
                                lapOffset = lastItem.totalTime
                            if tmpAppended:
                                self.samples = self.samples[:-1]
                        else:
                            lapOffset = lastItem.totalTime
                    else:
                        lapOffset = lastItem.lapOffset
                    item.lapTime = item.totalTime - lapOffset
            else:
                if (len(self.samples) == 0 or lastItem.lapTime == 0) and (nsp - self.ptracker.a2bOffset) % 1.0 > 0.5:
                    # not yet crossed start line
                    item.lapTime = 0
                else:
                    if len(self.samples) == 0 or lastItem.lapTime == 0:
                        self.startTime = time.time() - 0.001
                        item.lapTime = 1
                    else:
                        if item.lastLap == lastItem.lastLap:
                            item.lapTime = int((time.time() - self.startTime)*1000.)
                        else:
                            item.lapTime= 0

        if (lastItem is None or lastItem.lapTime == 0) and item.lapTime > 0 and self.ptracker.a2b:
            self.abEntryDetected = True

        if len(self.samples) == 0:
            item.lapOffset = 0
            if item.lapCount == 0 and item.lapTime < 5000 and item.normSplinePosition > 0.5:
                acdump("LC %d: nspOffset = -1 for driver %s (lc=%d lt=%d nsp=%.4f)",
                    self.carId, self.name, item.lapCount, item.lapTime, item.normSplinePosition)
                item.nspOffset = -1
            else:
                item.nspOffset = item.lapCount
                acdump("LC %d: nspOffset = lc for driver %s (lc=%d lt=%d nsp=%.4f)",
                    self.carId, self.name, item.lapCount, item.lapTime, item.normSplinePosition)
            if not hasattr(item, "totalTime"): item.totalTime = item.lapOffset + item.lapTime
            item.totalSplinePosition = item.nspOffset + item.normSplinePosition
            self.samples.append(item)
        else:
            # workaround for broken lapTime API
            if lastItem.lapCount > 0 and item.lapCount < lastItem.lapCount:
                # probably retired
                acdump("LC %d: %s has retired?", self.carId, self.name)
                return
            item.nspOffset = lastItem.nspOffset
            item.lapOffset = lastItem.lapOffset
            if item.lapTime < lastItem.lapTime:
                acdump("LC %d: %s: new lap detected lt(%d -> %d) lc(%d -> %d).", self.carId, self.name, lastItem.lapTime, item.lapTime, lastItem.lapCount, item.lapCount)
                if not item.lastLap is None:
                    # if we are in hotlap mode and we cross SF line the first time
                    # or if we are at nords-tourist and cross the "enable line" after a return to pits
                    if (self.ptracker.lastSessionType[0] == 3  and item.lapCount == 0 and lastItem.lapCount == 0) or (self.ptracker.a2b and item.lapCount == lastItem.lapCount):
                        acdump("Saving lapOffset due to special case hotlap / ab")
                        item.lapOffset += lastItem.lapTime
                        # don't show the lap in the display, do not attempt to notify server
                        self.lastLapValid = False
                    # if the lastLap API returned 0 or the same value than the for the last lap
                    elif item.lastLap <= 0 or (item.lastLap == lastItem.lastLap and item.lapTime < 1000):
                        acdump("LC %d: item.lastlap(=%d), lastItem.lastLap(=%d); ignoring sample and wait for correct one.", self.carId, item.lastLap, lastItem.lastLap)
                        return
                    else:
                        item.lapOffset += item.lastLap
                else:
                    # ac.getCarState(carId, CS.LastLap) is broken for opponents in MP replays
                    # -> (nasty) workaround: lastLap = totalTime - lapTime (current) - lapOffset
                    item.lastLap = item.totalTime - item.lapTime - item.lapOffset
                    item.lapOffset += item.lastLap
                self.newLapDetected = True
            else:
                if item.lastLap is None:
                    # ac.getCarState(carId, CS.LastLap) is broken for opponents in MP replays
                    # -> (nasty) workaround: lastLap = totalTime - lapTime (current) - lapOffset
                    item.lastLap = lastItem.lastLap
            if item.normSplinePosition < 0.2 and lastItem.normSplinePosition > 0.8:
                acdump("LC %d: %s: nsp wraparound detected for driver (%.4f -> %.4f) lapTime=(%d->%d) lapOffset=%d, lapCountOffset=%d",
                    self.carId, self.name, lastItem.normSplinePosition, item.normSplinePosition, lastItem.lapTime, item.lapTime, item.lapOffset, self.lapCountOffset)
                item.nspOffset += 1
            elif item.normSplinePosition < lastItem.normSplinePosition:
                # driver is probably driving backwards
                # assert that nsp values are increasing...
                item.normSplinePosition = lastItem.normSplinePosition
            if not hasattr(item, "totalTime"): item.totalTime = item.lapOffset + item.lapTime
            item.totalSplinePosition = item.nspOffset + item.normSplinePosition
            # check for car jumps (probably back to pits...)
            if self.checkJerkyMotion(item):
                if acsim.ac.isCarInPitlane(self.carId):
                    acdebug("LC %d: %s: probably returned to pits", self.carId, self.name)
                    # we used to init() here, but this has side effects if we loose the ego car's lapOffset. So we just reset the sample list to the last sample.
                    self.samples = [item]
                # if this occurs too many times in a row, something strange is happening. we assume that the car teleported to somewhere and we reset the sample list
                # happens on mod tracks with buggy pit lane information
                self.jerkyMotionCounter += 1
                if self.jerkyMotionCounter > 100:
                    acwarning("LC %d: %s: seems to have teleported; resetting. Buggy mod track?", self.carId, self.name)
                    self.samples = [item]
                return
            self.jerkyMotionCounter = 0
            if len(self.samples) >= 2:
                if (lastItem.totalTime < self.samples[-2].totalTime + self.delta_t_ms):
                    self.samples = self.samples[:-1]
            # check if the totalSplinePosition changed unnaturally and we are near the SF line
            if item.totalSplinePosition > lastItem.totalSplinePosition + 0.5 and item.totalSplinePosition % 1.0 > 0.95:
                acdump("LC %d: Correcting tsp at the SF line (-1)", self.carId)
                item.totalSplinePosition -= 1.0
            if item.totalSplinePosition < lastItem.totalSplinePosition - 0.5 and item.totalSplinePosition % 1.0 < 0.05:
                acdump("LC %d: Correcting tsp at the SF line (+1)", self.carId)
                item.totalSplinePosition += 1.0
            acdump("LC(corr) %d: lt=%s nsp=%.3f lc=%s ll=%s tsp=%s tt=%s lo=%s wp=%s v=%s", self.carId, item.lapTime, item.normSplinePosition, item.lapCount, item.lastLap, item.totalSplinePosition, item.totalTime, item.lapOffset, item.worldPosition, item.velocity)
            self.samples.append(item)
        if not self.strackerLapCount is None and self.ptracker.hasStrackerLaptimes():
            if item.normSplinePosition > 0.2 and item.normSplinePosition < 0.8:
                newOffset = max(0, self.strackerLapCount - item.lapCount)
                if newOffset != 0:
                    acinfo("LC %d: Correcting lapCountOffset for player %s (%d -> %d) strackerLapCount=%d item.lapCount=%d",
                           self.carId, self.name, self.lapCountOffset, self.lapCountOffset + newOffset, self.strackerLapCount, item.lapCount)
                    self.lapCountOffset += newOffset
        else:
            self.strackerLapCount = None
        # check if we are in the middle of a lap and the nsp offset is != lapCount
        # in this case we have to correct it
        if item.nspOffset >= 0 and item.nspOffset != item.lapCount:
            delta = item.nspOffset - item.lapCount
            if delta == self.possibleTspCorrection:
                self.tspCorrectionVotes += 1
            else:
                acdump("LC %d: tsp inconsistency of driver %s (%d - %d=%d)", self.carId, self.name, item.nspOffset, item.lapCount, delta)
                self.tspCorrectionVotes = 1
                self.possibleTspCorrection = delta
            if self.tspCorrectionVotes >= 200:
                acdump("LC %d: re-calculating tsp's of driver %s (delta:%.1f)", self.carId, self.name, delta)
                for i in range(len(self.samples)):
                    self.samples[i].nspOffset -= delta
                    self.samples[i].totalSplinePosition = self.samples[i].nspOffset + self.samples[i].normSplinePosition
                self.possibleTspCorrection = 0
                self.tspCorrectionVotes = 0
        else:
            if self.tspCorrectionVotes > 0:
                acdump("LC %d: tsp inconsistency of driver %s cancelled after %d votes", self.carId, self.name, self.tspCorrectionVotes)
            self.tspCorrectionVotes = 0

    def checkJerkyMotion(self,item):
        if len(self.samples) < 1:
            return False
        lastItem = self.samples[-1]
        if self.ptracker.a2b and lastItem.lapTime == 0:
            return False
        p = item.worldPosition
        v = item.velocity
        lp = lastItem.worldPosition
        lv = lastItem.velocity
        dt = (item.totalTime - lastItem.totalTime)*0.001
        max_delta = 0.
        for i in range(3):
            d1 = abs( p[i] -  v[i]*dt - lp[i])
            d2 = abs(lp[i] + lv[i]*dt -  p[i])
            max_delta = max(max_delta, d1, d2)
        jump_detected = max_delta > jump_delta
        if jump_detected:
            acdump("LC %d: JUMP: dt=%.2f n=%d delta=%.1f (p,v)=(%s,%s) (lp,lv)=(%s,%s)", self.carId, dt, len(self.samples), max_delta, str(p), str(v), str(lp), str(lv))
        return jump_detected

    def adaptTotalSplinePositionsToLap(self, lapCount):
        if self.isRecordLap and lapCount != self.lastLapCount:
            self.lastLapCount = lapCount
            for i in range(len(self.samples)):
                self.samples[i].totalSplinePosition = self.samples[i].normSplinePosition + lapCount

    def interpolateBetweenSamples(self, srcAttr, destAttr, srcVal, extrapolate):
        srcList = BisectOnListAttr(self.samples, srcAttr)
        i = bisect.bisect_left(srcList, srcVal)
        if i <= 0 and extrapolate: i = 1
        if i >= len(srcList) and extrapolate: i = len(srcList)-1
        if i >= 1 and i < len(srcList):
            s0 = srcList[i-1]
            s1 = srcList[i]
            d0 = getattr(self.samples[i-1], destAttr)
            d1 = getattr(self.samples[i], destAttr)
            res = interpolate(srcVal, s0, s1, d0, d1)
        else:
            res = None
        return res

    def tAtTsp(self, tsp, extrapolate):
        return self.interpolateBetweenSamples('totalSplinePosition', 'totalTime', tsp, extrapolate)

    def tspAtT(self, t, extrapolate):
        return self.interpolateBetweenSamples('totalTime', 'totalSplinePosition', t, extrapolate)

    def delta(self, other):
        if len(self.samples) < 2 or len(other.samples) < 2:
            return 0.0
        if self.isRecordLap:
            self.adaptTotalSplinePositionsToLap(int(other.samples[-1].totalSplinePosition))
            tsp_other = other.samples[-1].totalSplinePosition
            # get the time we have been at this tsp
            t = self.tAtTsp(tsp_other, True)
            # we'd compare this time against other.samples[-1].lapTime
            tBase = other.samples[-1].lapTime
            # unfortunately, sometimes this is not advisable (when the spline position
            # wraps around, the lapTime still increases)
            # another way to do it is to compare the totalTime since spline position
            # wrap-around
            t0 = other.tAtTsp(math.floor(other.samples[-1].totalSplinePosition), False)
            if not t0 is None:
                t1 = other.samples[-1].totalTime
                if abs(other.samples[-1].lapTime - (t1-t0)) > self.lastLapTime*0.5:
                    tBase = t1-t0
            delta = t - tBase
        elif other.isRecordLap:
            delta = -other.delta(self)
        else:
            tsp_self  =  self.samples[-1].totalSplinePosition
            tsp_other = other.samples[-1].totalSplinePosition
            if tsp_self >= tsp_other:
                # we are in front, delta must be negative
                # find nsp_other in self.samples[:].totalSplinePosition
                t = self.tAtTsp(tsp_other, False)
                if t is None:
                    delta = self.samples[0].totalTime-self.samples[-1].totalTime
                else:
                    delta = t - self.samples[-1].totalTime
                if self.raceFinished and other.raceFinished:
                    delta = self.samples[-1].totalTime - other.samples[-1].totalTime
                elif self.raceFinished:
                    delta = delta + (self.samples[-1].totalTime - other.samples[-1].totalTime)
            else:
                # we are behind, delta must be positive
                delta = -other.delta(self)
        return delta

    def toLapHistory(self, withoutSamples = False):
        if not self.lastLapHistory is None:
            return self.lastLapHistory
        if withoutSamples == False:
            myassert( len(self.samples) >= 4 )
            # get the indices of the last lap (i.e. from samples[-2] the lapTime must be decreasing)
            for i in range(len(self.samples)-2,0,-1):
                if self.samples[i].lapTime < self.samples[i-1].lapTime:
                    break
            indices = range(len(self.samples)-2, i-1,-1)
            if self.ptracker.a2b:
                while len(indices) > 0 and self.samples[indices[0]].lapTime == 0:
                    indices = indices[1:]
                while len(indices) > 0 and self.samples[indices[-1]].lapTime == 0:
                    indices = indices[:-1]
                myassert(len(indices) >= 2)
            else:
                myassert(len(self.samples)-2 == indices[0])
            tspOffset = math.floor(self.samples[indices[0]].totalSplinePosition)
            if self.samples[indices[0]].normSplinePosition < 0.2:
                tspOffset -= 1.
            sampleTimes = [None]*len(indices)
            normSplinePositions = [None]*len(indices)
            worldPositions = [None]*len(indices)
            velocities = [None]*len(indices)
            for k,i in enumerate(indices):
                j = -(k+1)
                sampleTimes[j] = self.samples[i].lapTime
                normSplinePositions[j] = self.samples[i].totalSplinePosition-tspOffset
                worldPositions[j] = self.samples[i].worldPosition
                velocities[j] = self.samples[i].velocity
            if indices[-1]-1 > 0:
                # we won't need the samples before this lap anymore. So we free the memory...
                self.samples = self.samples[indices[-1]-1:]
            if not self.ptracker.a2b:
                for nsp in [0.0,1.05,0.1]:
                    i = bisect.bisect_left(normSplinePositions, nsp)
                    i = max(i,1)
                    i = min(i,len(normSplinePositions)-1)
                    if not (abs(normSplinePositions[i-1] - nsp) < 0.15 and abs(normSplinePositions[i] - nsp) < 0.15):
                        acdebug("LC %d: ASSERTION: %.3f << nsp=%.3f << %.3f", self.carId, normSplinePositions[i-1], nsp, normSplinePositions[i])
                        acdebug("LC %d: normSplinePositions=%s", self.carId, str(list(map(lambda x: "%.2f"%x, normSplinePositions))))
                    myassert(abs(normSplinePositions[i-1] - nsp) < 0.15 and abs(normSplinePositions[i] - nsp) < 0.15)
            for t in range(0,sampleTimes[-1],1000):
                i = bisect.bisect_left(sampleTimes, t)
                i = max(i,1)
                i = min(i,len(sampleTimes)-1)
                myassert(abs(sampleTimes[i-1] - t) < 2000 and abs(sampleTimes[i] - t) < 2000)
        else:
            sampleTimes = []
            normSplinePositions = []
            worldPositions = []
            velocities = []
        lapTime = self.lapTimeHistory.get(self.samples[-1].lapCount-1, None)
        sectorTimes = self.sectorTimeHistory.get(self.samples[-1].lapCount-1, [])
        lastLapHistory = LapCollectorItem(
                    lapTime = lapTime,
                    sectorTimes = sectorTimes,
                    sampleTimes = sampleTimes,
                    normSplinePositions = normSplinePositions,
                    worldPositions = worldPositions,
                    velocities = velocities,
                    sectorsAreSoftSplits = (not self.sectorsWorking) or (self.carId != 0),
                    )
        if withoutSamples == False:
            fromLapHistory(lastLapHistory.lapTime, sectorTimes, sampleTimes, worldPositions, velocities, normSplinePositions, self.ptracker.a2b) # double check for plausibility
            self.lastLapHistory = lastLapHistory
        return lastLapHistory

def fromLapHistory(lapTime, sectorTimes, sampleTimes, worldPositions, velocities, normSplinePositions, a2b = False):
    acdebug("fromLapHistory called with n=%d samples, lapTime=%d, sectorTimes=%s a2b=%s",
            len(sampleTimes) if not sampleTimes is None else 0,
            lapTime,
            list(filter(lambda x: not x in [0,None], sectorTimes)),
            a2b,
            )
    if sampleTimes is None:
        return None
    if not lapTime is None and len(sampleTimes) >= 2:
        iStart = 0
        iEnd = None
        for i in range(len(sampleTimes)-1):
            if sampleTimes[i+1] < sampleTimes[i]:
                if i < len(sampleTimes)/2:
                    iStart = i+1
                elif iEnd is None:
                    iEnd = i+1
            if normSplinePositions[i+1] < normSplinePositions[i]:
                if i < len(sampleTimes)/2:
                    iStart = i+1
                elif iEnd is None:
                    iEnd = i+1
        if iEnd is None: iEnd = len(sampleTimes)
        sampleTimes = sampleTimes[iStart:iEnd]
        worldPositions = worldPositions[iStart:iEnd]
        velocities = velocities[iStart:iEnd]
        normSplinePositions = normSplinePositions[iStart:iEnd]
        myassert( len(sampleTimes) > 4)
        # iterate through all items and check for plausibility
        length = 0.0
        dnsp_max = normSplinePositions[0] + 1. - normSplinePositions[-1]
        for i in range(1, len(sampleTimes)):
            length += point_distance(worldPositions[i], worldPositions[i-1])
            dnsp_max = max(dnsp_max, normSplinePositions[i]-normSplinePositions[i-1])
        try:
            length_per_nsp = length/(normSplinePositions[-1]-normSplinePositions[0])
        except ZeroDivisionError:
            myassert(False)
        if not a2b:
            dl_max = length_per_nsp*dnsp_max
            myassert(dl_max < 250.)
            if sampleTimes[0] > 0:
                # use last sample before lapTime to have samples before the start of the lap
                pos = len(sampleTimes)-1
                while pos >= 0 and sampleTimes[pos] > lapTime:
                    pos -= 1
                if pos >= 0 and sampleTimes[pos] <= lapTime:
                    sampleTimes.insert(0, sampleTimes[pos]-lapTime)
                    normSplinePositions.insert(0, normSplinePositions[pos]-1.)
                    velocities.insert(0, velocities[pos])
                    worldPositions.insert(0, worldPositions[pos])
            if sampleTimes[-1] < lapTime:
                # we use first sample after start to have samples after the end of the lap
                pos = 0
                while pos < len(sampleTimes) and sampleTimes[pos] < 0:
                    pos += 1
                if pos < len(sampleTimes) and sampleTimes[pos] >= 0:
                    sampleTimes.append(sampleTimes[pos]+lapTime)
                    normSplinePositions.append(normSplinePositions[pos]+1.)
                    velocities.append(velocities[pos])
                    worldPositions.append(worldPositions[pos])
        myassert(sampleTimes[0] < 3000)
        myassert(normSplinePositions[0] < 0.2)
        myassert(sampleTimes[-1] > lapTime - 3000)
        if a2b:
            myassert(normSplinePositions[-1] > 0.8)
        else:
            myassert(normSplinePositions[-1] > 0.5)
        issorted = lambda l: all(l[i] <= l[i+1] for i in range(len(l)-1))
        myassert(issorted(sampleTimes))
        myassert(issorted(normSplinePositions))
        myassert(lapTime >= sampleTimes[-2]-sampleTimes[1])
        n = len(sampleTimes)
        myassert(len(worldPositions) == n and len(velocities) == n and len(normSplinePositions) == n)
        res = LapCollector()
        for i in range(n):
            item = LapCollectorItem(
                lapTime = sampleTimes[i],
                totalTime = sampleTimes[i],
                normSplinePosition = normSplinePositions[i],
                totalSplinePosition = normSplinePositions[i],
                lapCount = 0,
                lastLap = 0,
                worldPosition = worldPositions[i],
                velocity = velocities[i],
                )
            res.samples.append(item)
        res.isRecordLap = True
        res.lastLapCount = 0
        res.lastLapTime = lapTime
        res.sectorTimes = sectorTimes
        return res
    return None

def cmp(xx,yy):
    if xx is None and not yy is None: return 1
    if yy is None and not xx is None: return -1
    if xx is None and yy is None: return 0
    if xx < yy: return -1
    if xx > yy: return 1
    return 0

def compare_lc_items_race(x, y):
    if not x.raceFinished and not y.raceFinished:
        if len(x.samples) == 0 and len(y.samples) == 0:
            return cmp(x.leaderboardIndex, y.leaderboardIndex)
        elif len(x.samples) == 0:
            return 1
        elif len(y.samples) == 0:
            return -1
        else:
            return -cmp(x.samples[-1].totalSplinePosition, y.samples[-1].totalSplinePosition)
    if x.raceFinished and not y.raceFinished:
        return -1
    elif y.raceFinished and not x.raceFinished:
        return 1
    else:
        return cmp(x.leaderboardIndex, y.leaderboardIndex)

def compare_lc_items_quali(x, y):
    return cmp(x.bestLapTime, y.bestLapTime)

