
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
# For features, TODO list and known issues, see the web page:
#   http://www.assettocorsa.net/forum/index.php?threads/wip-ptracker-v1-10-lap-and-race-tracker-including-deltas-also-mp-compatible-with-ac-0-22.13169/
#
# Changelog:
# Please see http://n-e-y-s.de/ptracker_doc for the version history
################################################################################

import functools
import time
import sys
import traceback
from ptracker_lib.helpers import *
from ptracker_lib.profiler import Profiler
from ptracker_lib import acsim

MODE_STANDALONE = 0
MODE_CLIENT = 1
MODE_SERVER = 2

mode = MODE_CLIENT

try:
    from ptracker_lib.executable import ptracker_executable
except ImportError:
    ptracker_executable = ["C:/vpython33/Scripts/pythonw.exe", "apps/python/ptracker/ptracker-server.py"]
    #ptracker_executable = ["C:/python33/pythonw.exe", "-m", "cProfile", "-o", "apps/python/ptracker/ptracker-server.prof", "apps/python/ptracker/ptracker-server.py"]
    #ptracker_executable = ["NOTEXISTING"]

# global variables
hotlaps = None
SimInfo = None

def acState():
    global SimInfo
    import acsys
    if SimInfo is None:
        import ptracker_lib.sim_info
        SimInfo = ptracker_lib.sim_info.SimInfo
    carsCount = acsim.ac.getCarsCount()
    simInfo = SimInfo()
    res = dict(
        simInfo = simInfo,
        trackName = acsim.ac.getTrackName(0),
        trackConfig = acsim.ac.getTrackConfiguration(0),
        carsCount = carsCount,
        driverNames = [acsim.ac.getDriverName(cid) for cid in range(carsCount)],
        carNames = [acsim.ac.getCarName(cid) for cid in range(carsCount)],
        csVel = [acsim.ac.getCarState(cid, acsys.CS.Velocity) for cid in range(carsCount)],
        csLapTime = [acsim.ac.getCarState(cid, acsys.CS.LapTime) for cid in range(carsCount)],
        csNormSplinePosition = [acsim.ac.getCarState(cid, acsys.CS.NormalizedSplinePosition) for cid in range(carsCount)],
        csLapCount = [acsim.ac.getCarState(cid, acsys.CS.LapCount) for cid in range(carsCount)],
        csLastLap = [acsim.ac.getCarState(cid, acsys.CS.LastLap) for cid in range(carsCount)],
        csBestLap = [acsim.ac.getCarState(cid, acsys.CS.BestLap) for cid in range(carsCount)],
        csWorldPosition = [acsim.ac.getCarState(cid, acsys.CS.WorldPosition) for cid in range(carsCount)],
        currentSplits = [acsim.ac.getCurrentSplits(cid) for cid in range(carsCount)],
        isCarInPitlane = [acsim.ac.isCarInPitline(cid) for cid in range(carsCount)],
        isCarInPit = [acsim.ac.isCarInPit(cid) for cid in range(carsCount)],
        isConnected = [acsim.ac.isConnected(cid) for cid in range(carsCount)],
        getCarBallast = [acsim.ac.getCarBallast(cid) for cid in range(carsCount)],
        getFocusedCar = acsim.ac.getFocusedCar(),
        getServerIP = acsim.ac.getServerIP(),
        getServerHttpPort = acsim.ac.getServerHttpPort(),
        getServerName = acsim.ac.getServerName(),
    )
    return res

hookdll = None

@callbackDecorator
def createFileObserver(logfile, lf_filter):
    global hookdll
    if hookdll is None:
        import ctypes
        import platform
        import os.path
        if platform.architecture()[0] == "64bit":
            dllpath = os.path.dirname(__file__)+'/ptracker_lib/stdlib64'
        else:
            dllpath = os.path.dirname(__file__)+'/ptracker_lib/stdlib'
        try:
            hookdll = ctypes.CDLL(os.path.join(dllpath, "CreateFileHook.dll"))
        except OSError:
            acerror("Microsoft Redistributables 2015 must be installed for being able to share setups.")
    if not hookdll is None:
        hookdll.StartLogging(logfile, lf_filter)
        acinfo("fileobserver created successfully (%s, %s).", logfile, lf_filter)
        return True
    return False


@callbackDecorator
def doMain(*args):
    global hotlaps
    import sys
    import ptracker_lib
    acinfo("Never Eat Yellow Snow APPS (ptracker %s) python version %s", ptracker_lib.version, sys.version)
    if mode in [MODE_STANDALONE, MODE_SERVER]:
        if mode == MODE_SERVER:
            acsim.setState(args[0])
        else:
            if not acsim.offline():
                import sys
                import os
                import os.path
                import platform
                if platform.architecture()[0] == "64bit":
                    sysdir=os.path.dirname(__file__)+'/ptracker_lib/stdlib64'
                else:
                    sysdir=os.path.dirname(__file__)+'/ptracker_lib/stdlib'
                sys.path.insert(0, sysdir)
                os.environ['PATH'] = os.environ['PATH'] + ";."
            acState() # call to get all the data...
        from ptracker_lib.main import PersonalHotlaps
        appWindow = acsim.ac.newApp("ptracker")
        acsim.ac.setSize(appWindow, 100, 20)
        acsim.ac.setTitle(appWindow, "")
        acsim.ac.setIconPosition(appWindow, 0, -9000)
        hotlaps = PersonalHotlaps(appWindow)
        acsim.ac.addRenderCallback(appWindow, render_callback)
    else:
        # client
        import sys
        import os
        import os.path
        import platform
        if platform.architecture()[0] == "64bit":
            sysdir=os.path.dirname(__file__)+'/ptracker_lib/stdlib64'
        else:
            sysdir=os.path.dirname(__file__)+'/ptracker_lib/stdlib'
        sys.path.insert(0, sysdir)
        os.environ['PATH'] = os.environ['PATH'] + ";."
        from ptracker_lib.client_server import ac_client_server, client_server, client_server_impl
        client_server.PRINT = lambda *args: acinfo(" ".join(map(str, args)))
        client_server_impl.PRINT = client_server.PRINT
        try:
            hotlaps = ac_client_server.create_ac_client_server(ptracker_executable)
            hotlaps.addFunction("addRenderCallback", ('i', hotlaps.ARG_CALLBACK(hotlaps.ARG_PICKLE)), None, addRenderCallbackImpl)
            hotlaps.addFunction("setFpsMode", ('i',), None, setFpsMode)
            hotlaps.addFunction("eval", hotlaps.ARG_PICKLE, hotlaps.ARG_PICKLE, lambda x: eval(x))
            hotlaps.addFunction("createFileObserver", hotlaps.ARG_PICKLE, hotlaps.ARG_PICKLE, createFileObserver)
            hotlaps.remote.acMain(acState())
            hotlaps.commit()
        except Exception as e:
            # error while creating the server. provide a basic feedback window
            # with information about what could have gone wrong
            hotlaps = None
            appWindow = acsim.ac.newApp("ptracker")
            acsim.ac.setSize(appWindow, 700, 400)

            messages = [
                "There was an error while starting ptracker.exe.",
                "Error message: %s" % str(e),
                "Possible reasons:",
                "    * ptracker was not installed correctly. ",
                "      -> Try to remove the directory apps/python/ptracker and install it again.",
                "    * your anti virus SW blocks the execution of ptracker.exe.",
                "      -> Verify that the file apps/python/ptracker/dist/ptracker.exe is existing",
                "      -> Add an exception to your virus scanner",
                "      -> For more information visit http://n-e-y-s.de",
                "    * ptracker failed for other reasons",
                "      -> Consult the files <documents>/Assetto Corsa/logs/py_log.txt and ptracker-exe-stdout.txt",
                "         for more information.",
                "      -> Visit http://n-e-y-s.de for troubleshooting.",
                "      -> Ask for support at the Assetto Corsa support forum or at www.racedepartment.com",
                "         PLEASE ADD YOUR LOGS TO YOUR POST!",
                ]

            for cnt,msg in enumerate(messages):
                label = acsim.ac.addLabel(appWindow, "label-%d"%cnt)
                acsim.ac.setFontColor(label, 1.0, 0.3, 0.3, 1.0)
                acsim.ac.setPosition(label, 5, cnt*20+20)
                acsim.ac.setText(label, msg )
    return "ptracker"

# ac callbacks
def acMain(*args):
    return doMain(*args)

render_callbacks = [] # [windowId, callback, updateDt]
@callbackDecorator
def addRenderCallbackImpl(windowId, callback):
    func = genericAcCallback( functools.partial(genericRenderCallback, windowId) )
    render_callbacks.append([windowId, callback, 0.0])
    acsim.ac.addRenderCallback(windowId, func)

@callbackDecorator
def genericRenderCallback(windowId, dt, *args):
    for cbDesc in render_callbacks:
        if cbDesc[0] == windowId:
            cbDesc[2] += dt

updateDt = 0.0
updateProfilers = dict(
    total = Profiler("total"),
    acapi = Profiler("acapi"),
    cwait = Profiler("cwait"),
    cproc = Profiler("cproc"),
    ccall = Profiler("ccall"),
    ccomm = Profiler("ccomm"),
)

FPS_MODE_PREFER_ACCURACY = 0
FPS_MODE_PREFER_HIGH_FPS = 1
fpsMode = FPS_MODE_PREFER_HIGH_FPS
def setFpsMode(newFpsMode):
    global fpsMode
    fpsMode = newFpsMode

CLIENT_STATE_WAIT = 0
CLIENT_STATE_PROC = 1
CLIENT_STATE_CALL = 2
clientState = CLIENT_STATE_WAIT

@callbackDecorator
def acUpdate(dt, *args):
    global fpsMode
    with updateProfilers['total']:
        if mode == MODE_STANDALONE:
            acsim.ac.newCallback("acUpdate", (dt,))
            hotlaps.update(dt)
        elif mode == MODE_CLIENT:
            global updateDt, clientState
            updateDt += dt
            while 1:
                if clientState == CLIENT_STATE_WAIT:
                    with updateProfilers['cwait']:
                        try:
                            hotlaps.wait(timeout=0.0, autoCallFuncs=False)
                            clientState = CLIENT_STATE_PROC
                        except hotlaps.TimeoutError:
                            if updateDt > 5.0 and updateDt < 6.0:
                                acwarning("timeouts ... ptracker down?")
                elif clientState == CLIENT_STATE_PROC:
                    with updateProfilers['cproc']:
                        clientState = CLIENT_STATE_CALL
                        hotlaps.performRemoteCallRequests()
                elif clientState == CLIENT_STATE_CALL:
                    clientState = CLIENT_STATE_WAIT
                    with updateProfilers['acapi']:
                        state = acState()
                    with updateProfilers['ccall']:
                        hotlaps.remote.acUpdate(updateDt, state)
                        updateDt = 0.0
                        for cbDesc in render_callbacks:
                            if cbDesc[2] > 0.0:
                                #acinfo("rendering %s", cbDesc)
                                cbDesc[1](cbDesc[2])
                                cbDesc[2] = 0.0
                    with updateProfilers['ccomm']:
                        hotlaps.commit()
                if fpsMode == FPS_MODE_PREFER_HIGH_FPS or clientState == CLIENT_STATE_WAIT:
                    break
        elif mode == MODE_SERVER:
            state = args[0]
            acsim.setState(args[0])
            hotlaps.update(dt)
            fpsMode = hotlaps.fpsMode

@callbackDecorator
def acShutdown(*args):
    acsim.ac.newCallback("acShutdown", args)
    for p in ['total', 'acapi', 'cwait', 'cproc', 'ccall', 'ccomm']:
        acinfo(updateProfilers[p].logProfileInfo())
    if hasattr(hotlaps, "statistics"):
        acinfo(hotlaps.statistics())
    if mode in [MODE_STANDALONE, MODE_SERVER]:
        hotlaps.shutdown()
    acsim.ac.save()

@callbackDecorator
def render_callback(*args):
    dt = args[0]
    acsim.ac.newCallback("render_callback", args)
    hotlaps.render(dt)

