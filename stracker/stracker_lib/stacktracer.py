
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

"""Stack tracer for multi-threaded applications.


Usage:

import stacktracer
stacktracer.start_trace("trace.html",interval=5,auto=True) # Set auto flag to always update file!
....
stacktracer.stop_trace()

Original source:
    http://code.activestate.com/recipes/577334-how-to-debug-deadlocked-multi-threaded-programs/
"""

import sys
import traceback
import os
import time
import threading
from ptracker_lib.helpers import *

 # Taken from http://bzimmer.ziclix.com/2008/12/17/python-thread-dumps/

def stacktraces(logfun = acdebug):
    code = []

    for threadId, stack in sys._current_frames().items():
        code.append("\n# ThreadID: %s" % threadId)
        for filename, lineno, name, line in traceback.extract_stack(stack):
            code.append('File: "%s", line %d, in %s' % (filename, lineno, name))
            if line:
                code.append("  %s" % (line.strip()))

    code = "\n".join(code)
    logfun("---------------------------------- Stack traces from tracer ----------------------")
    logfun(code)
    logfun("----------------------------------------------------------------------------------")

# This part was made by nagylzs
class TraceDumper(threading.Thread):
    """Dump stack traces into a given file periodically."""
    def __init__(self,interval):
        """
        @param fpath: File path to output HTML (stack trace file)
        @param auto: Set flag (True) to update trace continuously.
            Clear flag (False) to update only if file not exists.
            (Then delete the file to force update.)
        @param interval: In seconds: how often to update the trace file.
        """
        self.interval = interval
        self.stop_requested = threading.Event()
        threading.Thread.__init__(self)

    def run(self):
        while not self.stop_requested.isSet():
            time.sleep(self.interval)
            stacktraces()

    def stop(self):
        self.stop_requested.set()
        self.join()

_tracer = None
def trace_start(interval=60*60): # each hour
    """Start tracing into the given file."""
    global _tracer
    _tracer = TraceDumper(interval)
    _tracer.setDaemon(True)
    _tracer.start()

def trace_stop():
    """Stop tracing."""
    global _tracer
    if not _tracer is None:
        _tracer.stop()
        _tracer = None

from threading import RLock

class ShortlyLockedRLock:
    def __init__(self, timeout = 120):
        self.lock = RLock()
        self.timeout = timeout

    def acquire(self, blocking=True, timeout=-1):
        issuedWarning = False
        if blocking and timeout < 0:
            if not self.lock.acquire(timeout=self.timeout):
                issuedWarning = True
                acwarning("Possible deadlock.")
                stacktraces(acwarning)
            else:
                return True
        res = self.lock.acquire()
        if issuedWarning:
            acinfo("Previous deadlock warning was a duck.")
        return res

    def release(self):
        return self.lock.release()

    def __enter__(self):
        self.lock.acquire()

    def __exit__(self, type, value, tb):
        self.lock.release()