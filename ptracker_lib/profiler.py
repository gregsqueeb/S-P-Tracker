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
import array
from ptracker_lib.helpers import *

class Histogram:
    def __init__(self, acc, vmin, vmax):
        self.acc = acc
        self.vmin = vmin
        self.vmax = vmax
        self.nhisto = int( (self.vmax - self.vmin)/self.acc )
        self.reset()

    def reset(self):
        self.count = 0
        self.min = float("inf")
        self.max = float("-inf")
        self.cum = 0.
        self.histogram = array.array('L', [0]*self.nhisto)

    def quantile(self, q):
        ch = 0.0
        i = 0
        minS = q*self.count
        while i < len(self.histogram) and ch < minS:
            ch += self.histogram[i]
            i += 1
        return i * self.acc + self.vmin

    def addValue(self, v):
        self.count += 1
        self.min = min(self.min, v)
        self.max = max(self.max, v)
        self.cum += v
        histoIdx = int((v-self.vmin)/self.acc)
        histoIdx = min(len(self.histogram)-1, max(0, histoIdx))
        self.histogram[histoIdx] += 1

class Profiler:
    def __init__(self, name):
        self.name = name
        self.histo = Histogram(0.1e-3, 0.0, 0.02)
        self.reset()

    def reset(self):
        self.resetTime = time.time()
        self.histo.reset()

    def logProfileInfo(self):
        period = time.time() - self.resetTime
        if self.histo.count >= 1:
            res = ("%s: calls per second: %5.1f execution times [ms]: min=%6.2f, max=%6.2f, avg=%6.2f, median=%5.1f, Q(95%%)=%5.1f, Q(99%%)=%5.1f, Q(99.9%%)=%5.1f, Q(99.99%%)=%5.1f Q(99.999%%)=%5.1f (# >= %.0f ms: %7d/%7d)" % (
                    self.name,
                    self.histo.count/period,
                    self.histo.min*1000.,
                    self.histo.max*1000.,
                    self.histo.cum*1000./max(1,self.histo.count),
                    self.histo.quantile(0.5)*1000.,
                    self.histo.quantile(0.95)*1000.,
                    self.histo.quantile(0.99)*1000.,
                    self.histo.quantile(0.999)*1000.,
                    self.histo.quantile(0.9999)*1000.,
                    self.histo.quantile(0.99999)*1000.,
                    len(self.histo.histogram)*self.histo.acc * 1000.,
                    self.histo.histogram[-1], self.histo.count,
                    ))
            self.reset()
        else:
            res = ("%s: not called." % self.name)
        return res

    def register_prof_time(self, t):
        self.histo.addValue(t)

    def __enter__(self):
        self.lastStart = time.time()

    def __exit__(self, exc_type, exc_value, traceback):
        self.register_prof_time(time.time()-self.lastStart)
        del self.lastStart
