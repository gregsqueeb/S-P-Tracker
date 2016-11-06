
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

import functools
import time
from threading import RLock

from ptracker_lib.helpers import *
from stracker_lib import config
from acplugins4python import ac_server_protocol, ac_server_helpers

interims_session_name = "STRACKER RACE OVER TIME"

def acquire_lock(func):

    @functools.wraps(acquire_lock)
    def _decorator(self, *args, **kwargs):
        with self.lock:
            res = func(self, *args, **kwargs)
            return res

    return _decorator

class SessionManager:

    def __init__(self, udp_getSessionInfo, udp_setSessionInfo, udp_nextSession):
        self.udp_getSessionInfo = udp_getSessionInfo
        self.udp_setSessionInfo = udp_setSessionInfo
        self.udp_nextSession = udp_nextSession
        self.skip_event = (time.time(), 0.0)
        self.lock = RLock()
        self.serverRestarted()

    def _cmpSessions(self, s1, s2):
        return (s1.name == s2.name
                    and s1.sessionType == s2.sessionType
                    and s1.laps == s2.laps
                    and s1.sessionTime == s2.sessionTime
                    and abs(s1.waittime - s2.waittime) <= 500)

    @acquire_lock
    def serverRestarted(self):
        try:
            self.raceOverTime = int(config.acconfig['SERVER']['RACE_OVER_TIME'])
        except:
            acwarning("Cannot read server's config option RACE_OVER_TIME. Session management will be limited.")
            self.raceOverTime = 0
        self.configuredSessions = {}
        self.csDeltaIdx = 0
        self.currSessIdx = None
        self.nextSessIdx = None
        self.nextSessionInfo = None
        self.currSessionInfo = None
        self.nextSessions = []

    @acquire_lock
    def sessionInfo(self, sessionInfo):
        if not sessionInfo.sessionIndex in self.configuredSessions:
            acdebug("adding session info for session index %d: %s", sessionInfo.sessionIndex, str(sessionInfo))
            self.configuredSessions[sessionInfo.sessionIndex] = sessionInfo
        for sidx in range(sessionInfo.sessionCount):
            if not sidx in self.configuredSessions:
                acdebug("querying session info for %d", sidx)
                self.udp_getSessionInfo(sessionIndex = sidx)
        if (sessionInfo.currSessionIndex != self.currSessIdx
                and sessionInfo.currSessionIndex == sessionInfo.sessionIndex):
            # session change
            self.currSessIdx = sessionInfo.currSessionIndex
            self.nextSessIdx = (self.currSessIdx + 1) % sessionInfo.sessionCount
            self.nextSessionInfo = None
            if len(self.nextSessions) > 0:
                if not self._cmpSessions(sessionInfo, self.nextSessions[0]):
                    acwarning("Somethings wrong with session management.")
                    acwarning("Expected session: %s", self.nextSessions[0])
                    acwarning("Got session     : %s", sessionInfo)
                self.nextSessions = self.nextSessions[1:]
        if sessionInfo.currSessionIndex == sessionInfo.sessionIndex:
            self.currSessionInfo = sessionInfo
        if sessionInfo.sessionIndex == self.nextSessIdx:
            # this event describes the next session
            self.nextSessionInfo = sessionInfo
        if self.nextSessionInfo is None:
            self.udp_getSessionInfo(sessionIndex = self.nextSessIdx)
        if len(self.nextSessions) > 0 and not self.nextSessionInfo is None:
            ns = self.nextSessions[0]
            if not self._cmpSessions(ns, self.nextSessionInfo):
                acdebug("next session (%d) does not match configured session, set session info", self.nextSessIdx)
                acdebug("current: %s", self.nextSessionInfo)
                acdebug("setting: %s", ns)
                self.nextSessionInfo = None
                self.udp_setSessionInfo(sessionIndex=self.nextSessIdx, sessionName=ns.name, sessionType=ns.sessionType, laps=ns.laps, timeSeconds=ns.sessionTime, waitTimeSeconds=round(ns.waittime/1000))
            else:
                if ns.name == interims_session_name:
                    acdebug("advancing to next session")
                    self.udp_nextSession()
                acdebug("next session (%d) matches configured session.", self.nextSessIdx)
        t = time.time()
        if (not self.currSessionInfo is None
                and self.currSessionInfo.raceFinishTimeStamp == self.skip_event[0]
                and t > self.skip_event[1]):
            self.skip_event = (t, 0.0)
            acdebug("advancing to next session")
            self.udp_nextSession()

    def _fixConfiguredSessions(self):
        for i in range(len(self.configuredSessions)):
            idx = (self.nextSessIdx + i + self.csDeltaIdx) % len(self.configuredSessions)
            self.nextSessions.append(self.configuredSessions[idx])

    @acquire_lock
    def raceFinished(self):
        if config.config.SESSION_MANAGEMENT.race_over_strategy == config.config.ROS_REPLACE_WITH_PRACTICE:
            if (not self.currSessionInfo.raceFinishTimeStamp is None
                    and self.currSessionInfo.sessionType == ac_server_protocol.SESST_RACE):
                timeElapsedSecs = time.time() - self.currSessionInfo.raceFinishTimeStamp
                if len(self.nextSessions) == 0:
                    t = round((self.raceOverTime - timeElapsedSecs)/60)
                    if t > 0:
                        self.nextSessionInfo = None
                        self.nextSessions = [
                            ac_server_helpers.DictToClass(name = interims_session_name, sessionType = ac_server_protocol.SESST_PRACTICE, laps = 0, sessionTime = t, waittime=15),
                        ]
                        self._fixConfiguredSessions()
                        self.csDeltaIdx += 1
                        acinfo("Added interims session.")
                    else:
                        acinfo("Skipped interims session because remaining time is too short.")
                else:
                    acwarning("Cannot add interims session when there are still pending changes")
            else:
                acwarning("Don't have raceFinishTimeStamp (%s) or the current session type (%d) is not race",
                    self.currSessionInfo.raceFinishTimeStamp,self.currSessionInfo.sessionType)
        elif config.config.SESSION_MANAGEMENT.race_over_strategy == config.config.ROS_SKIP:
            t = time.time()
            elapsed = t - self.currSessionInfo.raceFinishTimeStamp
            remaining = self.raceOverTime - elapsed
            wsbs = config.config.SESSION_MANAGEMENT.wait_secs_before_skip
            if remaining > wsbs + 5.:
                acinfo("skipping session in %d seconds:", wsbs)
                self.skip_event = (self.currSessionInfo.raceFinishTimeStamp, t + wsbs)
            else:
                acinfo("not skipping session (because remaining=%.1f <= wsbs=%.1f + 5.)", remaining, wsbs)

    @acquire_lock
    def replaceRaceLaps(self, raceLaps):
        found = False
        for idx in self.configuredSessions:
            s = self.configuredSessions[idx]
            if s.sessionType == ac_server_protocol.SESST_RACE:
                s.laps = raceLaps
                found = True
                break
        if found:
            acinfo("race laps set to %d", raceLaps)
            self._fixConfiguredSessions()
            self.nextSessionInfo = None
            return True
        else:
            acinfo("race not found, race lap set request ignored.")

    def _replaceTime(self, time, stype):
        found = False
        for idx in self.configuredSessions:
            s = self.configuredSessions[idx]
            if s.sessionType == stype:
                s.sessionTime = time
                found = True
                break
        if found:
            acinfo("session time type=%d set to %d minutes", stype, time)
            self._fixConfiguredSessions()
            self.nextSessionInfo = None
            return True
        else:
            acinfo("session type=%d not found, time set request ignored.", stype)

    @acquire_lock
    def replaceQualiTime(self, time):
        return self._replaceTime(time, ac_server_protocol.SESST_QUALIFY)

    @acquire_lock
    def replacePracticeTime(self, time):
        return self._replaceTime(time, ac_server_protocol.SESST_PRACTICE)

    @acquire_lock
    def onCommand(self, command):
        command = command.lower().strip()
        if command.startswith('rlaps'):
            command = command[len('rlaps'):].strip()
            l = int(command)
            return self.replaceRaceLaps(l)
        elif command.startswith('qtime'):
            command = command[len('qtime'):].strip()
            t = int(command)
            return self.replaceQualiTime(t)
        elif command.startswith('ptime'):
            command = command[len('ptime'):].strip()
            t = int(command)
            return self.replacePracticeTime(t)

    def helpCommands(self):
        return ["rlaps <num_laps>", "qtime <quali_mins>", "ptime <practice_mins>"]
