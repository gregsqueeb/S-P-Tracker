
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

import sys
import os
import ptracker_lib.expand_ac

if "/check_install" == sys.argv[1]:
    try:
        import ptracker_lib
        import PySide.QtGui
        open(ptracker_lib.expand_ac.expand_ac("Assetto Corsa","logs","log.txt"), "r")
        print("Installation seems to be ok")
        os._exit(7)
    except:
        import traceback
        print(traceback.format_exc())
        os._exit(3)

_log_path = ptracker_lib.expand_ac.expand_ac('Assetto Corsa/logs/ptracker-exe-stdout.txt')

sys.stdout = open(_log_path, "w", buffering=1)
sys.stderr = sys.stdout

from threading import Thread
import functools
import time
import traceback
import hashlib
import struct

import win32api

sys.path.append('apps/python/system')
import acsys

from ptracker_lib.client_server.client_server import *
import ptracker_lib.client_server.client_server_impl

from PySide import QtGui

#ptracker_lib.client_server.client_server_impl.debug_protocol = 1

class DummyAcsim:
    def __init__(self, server):
        self.server = server
        class Ac:
            def __init__(self, parent):
                self.stateMap = {
                    acsys.CS.Velocity: 'csVel',
                    acsys.CS.LapTime: 'csLapTime',
                    acsys.CS.NormalizedSplinePosition: 'csNormSplinePosition',
                    acsys.CS.LapCount: 'csLapCount',
                    acsys.CS.WorldPosition: 'csWorldPosition',
                    acsys.CS.LastLap: 'csLastLap',
                    acsys.CS.BestLap: 'csBestLap',
                    acsys.CS.RaceFinished: 'csRaceFinished',
                }
                self.DEBUG = 0
                self.parent = parent

            def debugcall(self, f, name):
                def new_f(*args, self=self):
                    if self.DEBUG: self.log("Calling %s (%s)" % (name, str(args)))
                    return f(*args)
                return new_f

            def __getattr__(self, attr):
                res = None
                if attr in self.parent.server.remote.__dict__:
                    res = getattr(self.parent.server.remote,attr)
                if not res is None:
                    if attr != "log":
                        res = self.debugcall(res, attr)
                    self.__dict__[attr] = res
                return self.__dict__[attr]

            def getCarsCount(self): return self.parent.state['carsCount']
            def getTrackName(self, cid): return self.parent.state['trackName']
            def getTrackConfiguration(self, cid): return self.parent.state['trackConfig']
            def getDriverName(self, cid): return self.parent.state['driverNames'][cid]
            def getCarName(self, cid): return self.parent.state['carNames'][cid]
            def getCarState(self, cid, csid): return self.parent.state[self.stateMap[csid]][cid]
            def getCurrentSplits(self, cid): return self.parent.state['currentSplits'][cid]
            def isCarInPitlane(self, cid): return self.parent.state['isCarInPitlane'][cid]
            def isCarInPit(self, cid): return self.parent.state['isCarInPit'][cid]
            def isConnected(self, cid): return self.parent.state['isConnected'][cid]
            def getCarBallast(self, cid): return self.parent.state['getCarBallast'][cid]
            def getCarTyreCompound(self, cid): return self.parent.state['getCarTyreCompound'][cid]
            def getFocusedCar(self): return self.parent.state['getFocusedCar']
            def getServerIP(self): return self.parent.state['getServerIP']
            def getServerHttpPort(self): return self.parent.state['getServerHttpPort']
            def getServerName(self): return self.parent.state['getServerName']


            def isRecording(self):
                return False

            def save(self):
                pass

            def newCallback(self, *args):
                pass

            def getACPid(self):
                return int(sys.argv[1])

        self.ac = Ac(self)

    def offline(self):
        return False

    def add_watched_module(self, module_name):
        if module_name == "ptracker_lib.sim_info":
            return self

    def setState(self, state):
        self.state = state

    def SimInfo(self):
        return self.state['simInfo']

def debugcalls(f, name):
    def new_f(*args):
        #print("Calling ",name)
        return f(*args)
    return new_f

alive = True
lastUpdateCall = time.time()
def funcWrapper(func, *args):
    global lastUpdateCall
    lastUpdateCall = time.time()
    func(*args)

def work(pid):
    try:
        global alive
        lastFpsMode = None
        import ptracker
        ptracker.mode = ptracker.MODE_SERVER

        s.addFunction('acMain', s.ARG_PICKLE, None, debugcalls(ptracker.acMain, name="acMain"))
        s.addFunction('acUpdate', s.ARG_PICKLE, None, debugcalls(functools.partial(funcWrapper, ptracker.acUpdate), name="acUpdate"))
        s.addFunction('eval', s.ARG_PICKLE, s.ARG_PICKLE, debugcalls(lambda x: eval(x), name="eval"))

        import ptracker_lib
        logfile = ptracker_lib.expand_ac.expand_ac("Assetto Corsa/logs/ptracker_fileobserver.txt")
        if os.path.exists(logfile):
            try:
                open(logfile, "w").write('')
            except IOError:
                acwarning("Cannot truncate %s", logfile)
                acwarning(traceback.format_exc())

        cntCalls = 0
        tStart = time.time()
        ptracker_module = None

        fileObserverCreated = False
        fileObserverOK = None

        while alive:
            try:
                s.wait(timeout=1.)
                if not fileObserverCreated and "createFileObserver"  in s.remote.__dict__:
                    lf_filter = ptracker_lib.expand_ac.expand_ac("Assetto Corsa/setups")
                    fileObserverCreated = True
                    fileObserverOK = s.remote.createFileObserver(logfile, lf_filter)
                if not fileObserverOK is None and not ptracker.hotlaps is None:
                    try:
                        r = fileObserverOK()
                        if r == False:
                            import ptracker_lib.message_types
                            ptracker.hotlaps.addMessage(text = "Install MS Redistributable 2015 to enable setup sharing.",
                                                        color = (1., 0., 0., 1.),
                                                        mtype = ptracker_lib.message_types.MTYPE_LOCAL_FEEDBACK)
                            fileObserverOK = None
                        elif r == True:
                            fileObserverOK = None
                    except:
                        pass
                if ptracker.fpsMode != lastFpsMode:
                    if "setFpsMode" in s.remote.__dict__:
                        lastFpsMode = ptracker.fpsMode
                        s.remote.setFpsMode(ptracker.fpsMode)
                if ptracker_module is None and time.time() - tStart > 60.:
                    ptracker_module = s.remote.eval("[__file__, sys.modules['ptracker_lib.client_server.ac_client_server'].__file__]")
                if not ptracker_module is None:
                    try:
                        evalr = ptracker_module()
                        ptracker_file = evalr[0].replace("\\", "/")
                        accs_file = evalr[1].replace("\\", "/")
                        ptracker_expected = "apps/python/ptracker/ptracker.py"
                        accs_expected = "apps/python/ptracker/ptracker_lib/client_server/ac_client_server.py"
                        def cmp(x,y):
                            return x[-len(y):] == y
                        ok = cmp(ptracker_file, ptracker_expected) and cmp(accs_file, accs_expected)
                        if not ok:
                            print("Please do not change any of the ptracker source files.")
                            alive = False
                        ptracker_module = ok
                    except:
                        pass
                cntCalls += 1
                s.commit()
            except s.TimeoutError:
                print("Timeout...")
        tStop = time.time()
        print("Leaving server...")
        print("Number of server calls: %d" % cntCalls)
        print("Time spent            : %f s" % (tStop-tStart))
        print("Calls per second      : %.1f" % (cntCalls/(tStop-tStart)))
        print(s.statistics())
        acsim.ac.log = lambda *args: print(" ".join(map(str, args)))
        ptracker.acShutdown()
        sys.stdout.flush()
        QtGui.QApplication.exit(0)
        sys.exit(0)
    except:
        print("Fatal error in ptracker-server:")
        print(traceback.format_exc())

def waitForPidAndFinish(pid):
    global alive
    #sys.settrace(tracer)
    print("Waiting for", pid)
    try:
        handle = win32api.OpenProcess(0x100000, True, pid)
    except:
        print(traceback.format_exc())
        pass
    try:
        os.waitpid(handle.handle, 0)
    except PermissionError:
        pass # this error seems to be normal, waiting seems to work anyway
    finally:
        alive = False
        print("Parent process finished, finishing up.")
    time.sleep(20)
    os._exit(1)

def watchdog():
    global lastUpdateCall
    while 1:
        if time.time() - lastUpdateCall > 180:
            break
        time.sleep(10)
    print("Watchdog exception, finishing up.")
    os._exit(1)

def tracer(frame, event, arg):
    if event != 'call':
        return
    co = frame.f_code
    func_name = co.co_name
    if func_name == 'write':
        # Ignore write() calls from print statements
        return
    #func_line_no = frame.f_lineno
    #func_filename = co.co_filename
    traceback.print_stack(frame)
    print()

def check():
    def checksum(buffer):
        sign = buffer[:0x12] + buffer[(0x12+4):]
        hashfun = hashlib.sha1()
        hashfun.update(sign)
        digest = hashfun.digest()
        e1, = struct.unpack_from('B', digest)
        p = e1*(len(digest)-4)//255
        cs = digest[p:(p+4)]
        return cs
    try:
        prot
    except:
        print("python mode -> no cs test!")
        print(traceback.format_exc())
        return True
    b = open(sys.executable, 'rb').read()
    cs = b[0x12:(0x12+4)]
    e = checksum(b)
    ok = (cs == e)
    hashfun = hashlib.sha1()
    for f in files:
        hashfun.update(open("apps/python/ptracker/"+f, "rb").read())
    ok = ok and (hashfun.digest() == prot)
    return ok

if __name__ == "__main__":
    try:
        if not check():
            print("Please do not change any of the ptracker source files.")
            os._exit(1)
        pid = int(sys.argv[1])
        s = Server(IF_SHM, "ptracker-client-server-comm", pid, 15.)
        acsim = DummyAcsim(s)
        import ptracker_lib
        ptracker_lib.acsim = acsim
        import ptracker_lib.helpers
        ptracker_lib.helpers.restore_loggers(verbosity=ptracker_lib.helpers.acverbosity, prefix='ptracker-server')
        from ptracker_lib.qtbrowser_common import QtThread
        t1 = Thread(target=functools.partial(waitForPidAndFinish, pid))
        t1.daemon = True
        t1.start()
        t2 = Thread(target=functools.partial(work, pid))
        t2.daemon = True
        t2.start()
        t3 = Thread(target=watchdog)
        t3.daemon = True
        t3.start()
        QtThread()
    except:
        print("Fatal error in ptracker-server::__main__:")
        print(traceback.format_exc())
