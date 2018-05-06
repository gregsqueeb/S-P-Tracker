
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
import traceback
from threading import RLock, Thread

from ptracker_lib.helpers import *
from stracker_lib import stracker_shm
from acplugins4python.ac_server_helpers import *

class CarPosition(GenericPacket):
    packetId = 1
    _content = (
        ('x', Float),
        ('y', Float),
        ('guid', Ascii),
    )

class CarClassification(GenericPacket):
    packetId = 2
    _content = (
        ('pos', Uint8),
        ('guid', Ascii),
        ('name', UTF32),
        ('bestLapTime', Uint32),
        ('lapCount', Uint16),
        ('sumLapTimes', Uint32),
        ('finished', Uint8),
        ('car', Ascii),
        ('connected', Uint8),
    )

class SessionInfo(GenericPacket):
    packetId = 3
    _content = (
        ('session_type', Uint8),
        ('session_duration', Int32),
        ('session_laps', Uint16),
        ('track', Ascii),
        ('elapsedMS', Int32),
    )

ranking = []
chat = [] # (timestamp, name, message)
sessionInfo = SessionInfo(session_type=0, session_duration=0, session_laps=0, track="", elapsedMS=0)
commandHandler = None

lock = RLock()

def locked(f):
    @functools.wraps(f)
    def _(*args, **kw):
        #acdebug("wait %s", str(f))
        with lock:
            #acdebug("enter %s", str(f))
            res = f(*args, **kw)
            #acdebug("exit %s", str(f))
            return res
    return _

@locked
def update_ranking(driverList):
    global ranking
    ranking = driverList

@locked
def update_chat(name, message):
    chat.append( (time.time(), name, message) )

@locked
def resetSession(session):
    ranking.clear()
    track = session.track
    if session.track_config != "":
        track += "-" + session.track_config
    sessionInfo.track = track
    sessionInfo.session_duration = session.sessionTime
    sessionInfo.session_type = session.sessionType
    sessionInfo.session_laps = session.laps
    sessionInfo.elapsedMS = session.elapsedMS

@locked
def updateSession(session):
    sessionInfo.elapsedMS = session.elapsedMS

@locked
def setCommandHandler(callback):
    global commandHandler
    commandHandler = callback

def periodic_update():
    while 1:
        with lock:
            _update()
        time.sleep(0.1)

@locked
def _update():
    stracker_shm.set('car_positions', _genLiveInfo())
    stracker_shm.set('session_info', _genSessionInfo())
    stracker_shm.set('classification', _genClassification())
    stracker_shm.set('chat_messages', _genChat())
    try:
        cmd = stracker_shm.get(None, 'command_from_http')
    except stracker_shm.ServerError:
        cmd = ''
        stracker_shm.set('command_from_http', '')
    if cmd != '':
        stracker_shm.set('command_from_http', '')
        acdebug("executing command request from http: %s", cmd)
        commandHandler(cmd)

def _genLiveInfo():
    res = []
    for d in ranking:
        cc = CarPosition(guid=guidhasher(d.guid), x=d.p3d[0], y=d.p3d[2])
        res.append(cc.to_buffer())
    return tuple(res)

def _genClassification():
    res = []
    for p,d in enumerate(ranking):
        pos = p+1
        cc = CarClassification(pos=pos, guid=guidhasher(d.guid), name=d.name, bestLapTime=d.bestTime() or 0, lapCount=d.lapCount(), sumLapTimes=d.totalTime() or 0, finished=d.raceFinished, car=d.car, connected=d.carId != -1)
        res.append(cc.to_buffer())
    return tuple(res)

def _genSessionInfo():
    return sessionInfo.to_buffer()

def _genChat():
    global chat
    tStart = time.time() - 20
    chat_new = list(filter(lambda x: x[0] >= tStart, chat))
    if len(chat_new) > 20:
        chat_new = chat_new[-20:]
    chat = chat_new
    return chat_new

updateThread = Thread(target=periodic_update, daemon=True)
updateThread.start()
