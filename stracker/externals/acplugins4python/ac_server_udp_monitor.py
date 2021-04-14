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

import copy, time
from threading import RLock
from . import ac_server_protocol
from .ac_server_helpers import DictToClass

class ACUdpMonitor:
    def __init__(self):
        # pluginId = 0 -> this plugin
        # pluginId = 1 -> proxied plugin
        self.HistoryInfo = DictToClass
        self.InfoRequest = DictToClass
        self.lock = RLock()
        self.reset()

    def reset(self, carId = None):
        with self.lock:
            if carId is None:
                self.intervals = [0,0]
                self.cu_history = [{},{}] # [pluginId][carId]
                self.info_requests = []
            else:
                if carId in self.cu_history[0]: del self.cu_history[0][carId]
                if carId in self.cu_history[1]: del self.cu_history[1][carId]

    def calcRTInterval(self):
        with self.lock:
            res = self.intervals[0]
            if 0 < self.intervals[1] < res or res == 0:
                res = self.intervals[1]
            return res

    def setIntervals(self, pluginId, interval):
        with self.lock:
            oldInterval = self.calcRTInterval()
            self.intervals[pluginId] = interval
            newInterval = self.calcRTInterval()
            return newInterval

    def getInterval(self, pluginId):
        with self.lock:
            if self.intervals[pluginId] < 0:
                return None
            return self.intervals[pluginId]

    def infoRequest(self, pluginId, cls, f_filter):
        with self.lock:
            if len(self.info_requests) < 64:
                self.info_requests.append(self.InfoRequest(timestamp=time.time(), pluginId=pluginId, cls=cls, f_filter=f_filter))

    def okToSend(self, pluginId, packet):
        with self.lock:
            if type(packet) == ac_server_protocol.CarUpdate:
                # CarUpdate packets
                if self.intervals[pluginId] == 0:
                    # no rt report configured, CarUpdate event will not be passed
                    return False
                t = time.perf_counter()
                threshold = t - max(0, (self.intervals[pluginId]-50)*0.001)
                if not packet.carId in self.cu_history[pluginId]:
                    # create a history info object for the car if not already there
                    self.cu_history[pluginId][packet.carId] = self.HistoryInfo(lastSendTime = threshold, firstSendTime = t, count = 0)
                lastT = self.cu_history[pluginId][packet.carId].lastSendTime
                if t-lastT > self.intervals[pluginId]*10:
                    log_dbg("car %d has not been updated for a long time (the player probably left) - resetting statistics" % packet.carId)
                    self.cu_history[pluginId][packet.carId] = self.HistoryInfo(lastSendTime = threshold, firstSendTime = t, count = 0)
                    lastT = threshold
                if ((self.intervals[pluginId] <= self.intervals[1-pluginId] or self.intervals[1-pluginId] <= 0) or
                    (lastT <= threshold)):
                    # this plugin has the quicker update rate
                    h = self.cu_history[pluginId][packet.carId]
                    h.lastSendTime = t
                    h.count += 1
                    # limit the history to 30s, intervals are in milliseconds
                    maxcnt = 30000./max(10,self.intervals[pluginId])
                    if h.count > maxcnt:
                        avg = (h.lastSendTime - h.firstSendTime)/h.count
                        h.count = maxcnt
                        h.firstSendTime = h.lastSendTime - avg*h.count
                    return True
                return False
            elif type(packet) in [ac_server_protocol.SessionInfo, ac_server_protocol.CarInfo]:
                # Requested info packets
                for ir in self.info_requests:
                    if ir.pluginId == pluginId:
                        if ir.cls == type(packet):
                            if ir.f_filter(packet):
                                self.info_requests.remove(ir)
                                return True
                        else:
                            pass
                # no request found for this packet. Probably already sent to proxy
                return False
            # generic packet. Needs proxying
            return True

    def plausibilityCheck(self):
        with self.lock:
            t = time.time()
            for ir in copy.copy(self.info_requests):
                if t - ir.timestamp > 5.:
                    self.info_requests.remove(ir)
                    if ir.pluginId == 0:
                        log=log_err
                    else:
                        log=log_dbg
                    log("Timeout [pluginId=%d] while waiting for request (%.1fs) for request %s." % (ir.pluginId, t-ir.timestamp, ir.cls))
            for pluginId in [0,1]:
                if pluginId == 0:
                    log=log_err
                else:
                    log=log_dbg
                if self.intervals[pluginId] > 0:
                    for carId in list(self.cu_history[pluginId].keys()):
                        h = self.cu_history[pluginId][carId]
                        if h.count <= 10: continue
                        avgInterval = (h.lastSendTime - h.firstSendTime)/h.count*1000
                        if avgInterval > self.intervals[pluginId]*1.5 or avgInterval < self.intervals[pluginId]*0.5:
                            log("Realtime report interval mismatch [pluginId=%d, carId=%d]. Configured %d ms, measured %.1f ms. Resetting stats." % (pluginId, carId, self.intervals[pluginId], avgInterval))
                            del self.cu_history[pluginId][carId]
