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

"""
Copyright (c) 2015, NeverEatYellowSnow (NEYS)
All rights reserved.

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are met:
1. Redistributions of source code must retain the above copyright
   notice, this list of conditions and the following disclaimer.
2. Redistributions in binary form must reproduce the above copyright
   notice, this list of conditions and the following disclaimer in the
   documentation and/or other materials provided with the distribution.
3. All advertising materials mentioning features or use of this software
   must display the following acknowledgement:
   This product includes software developed from NeverEatYellowSnow (NEYS).
4. Neither the name of NeverEatYellowSnow (NEYS) nor the
   names of its contributors may be used to endorse or promote products
   derived from this software without specific prior written permission.

THIS SOFTWARE IS PROVIDED BY <COPYRIGHT HOLDER> ''AS IS'' AND ANY
EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
DISCLAIMED. IN NO EVENT SHALL <COPYRIGHT HOLDER> BE LIABLE FOR ANY
DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES
(INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES;
LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND
ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
(INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
"""

from .ac_server_helpers import *

__all__ = [
    "ProtocolVersionMismatch",
    "NewSession",
    "SessionInfo",
    "EndSession",
    "CollisionEnv",
    "CollisionCar",
    "CarInfo",
    "CarUpdate",
    "NewConnection",
    "ConnectionClosed",
    "LapCompleted",
    "ProtocolVersion",
    "ChatEvent",
    "ClientLoaded",
    "ProtocolError",
    "GetSessionInfo",
    "SetSessionInfo",
    "KickUser",
    "SESST_PRACTICE",
    "SESST_QUALIFY",
    "SESST_RACE",
    "SESST_DRAG",
    "SESST_DRIFT",
    ]

PROTOCOL_VERSION = 4

ACSP_NEW_SESSION = 50
ACSP_NEW_CONNECTION = 51
ACSP_CONNECTION_CLOSED = 52
ACSP_CAR_UPDATE = 53
ACSP_CAR_INFO = 54 # Sent as response to ACSP_GET_CAR_INFO command
ACSP_END_SESSION = 55
ACSP_LAP_COMPLETED = 73
ACSP_VERSION = 56
ACSP_CHAT = 57
ACSP_CLIENT_LOADED = 58
ACSP_SESSION_INFO = 59
ACSP_ERROR = 60

ACSP_CLIENT_EVENT = 130

ACSP_CE_COLLISION_WITH_CAR = 10
ACSP_CE_COLLISION_WITH_ENV = 11

ACSP_REALTIMEPOS_INTERVAL = 200
ACSP_GET_CAR_INFO = 201
ACSP_SEND_CHAT = 202 # Sends chat to one car
ACSP_BROADCAST_CHAT = 203 # Sends chat to everybody
ACSP_GET_SESSION_INFO = 204
ACSP_SET_SESSION_INFO = 205
ACSP_KICK_USER = 206
ACSP_NEXT_SESSION = 207
ACSP_RESTART_SESSION = 208
ACSP_ADMIN_COMMAND = 209

# enum for session type
SESST_PRACTICE = 1
SESST_QUALIFY = 2
SESST_RACE = 3
SESST_DRAG = 4
SESST_DRIFT = 5

class ProtocolVersionMismatch(RuntimeError):
    pass

class NewSession(GenericPacket):
    packetId = ACSP_NEW_SESSION
    _content = (
        ('version', Uint8),
        ('sessionIndex', Uint8), # the index of the session this packet belongs to
        ('currSessionIndex', Uint8), # the index of the current session of the server
        ('sessionCount', Uint8),
        ('serverName', UTF32),
        ('track', Ascii),
        ('track_config', Ascii),
        ('name', Ascii),
        ('sessionType', Uint8),
        ('sessionTime', Uint16),
        ('laps', Uint16),
        ('waittime', Uint16),
        ('ambientTemp', Uint8),
        ('roadTemp', Uint8),
        ('wheather', Ascii),
        ('elapsedMS', Int32),
    )

class SessionInfo(NewSession):
    packetId = ACSP_SESSION_INFO

class CollisionEnv(GenericPacket):
    packetId = ACSP_CLIENT_EVENT
    _content = (
        ('carId', Uint8),
        ('impactSpeed', Float),
        ('worldPos', Vector3f),
        ('relPos', Vector3f),
    )

class CollisionCar(GenericPacket):
    packetId = ACSP_CLIENT_EVENT
    _content = (
        ('car1_id', Uint8),
        ('car2_id', Uint8),
        ('impactSpeed', Float),
        ('worldPos', Vector3f),
        ('relPos', Vector3f),
    )

class ClientEvent:
    packetId = ACSP_CLIENT_EVENT
    def from_buffer(self, buffer, idx):
        evtype,idx = Uint8.get(buffer, idx)
        if evtype == ACSP_CE_COLLISION_WITH_CAR:
            return CollisionCar().from_buffer(buffer, idx)
        elif evtype == ACSP_CE_COLLISION_WITH_ENV:
            return CollisionEnv().from_buffer(buffer, idx)

class CarInfo(GenericPacket):
    packetId = ACSP_CAR_INFO
    _content = (
        ('carId', Uint8),
        ('isConnected', Bool),
        ('carModel', UTF32),
        ('carSkin', UTF32),
        ('driverName', UTF32),
        ('driverTeam', UTF32),
        ('driverGuid', UTF32),
    )

class EndSession(GenericPacket):
    packetId = ACSP_END_SESSION
    _content = (
        ('filename', UTF32),
    )

class CarUpdate(GenericPacket):
    packetId = ACSP_CAR_UPDATE
    _content = (
        ('carId', Uint8),
        ('worldPos', Vector3f),
        ('velocity', Vector3f),
        ('gear', Uint8),
        ('engineRPM', Uint16),
        ('normalizedSplinePos', Float),
    )

class NewConnection(GenericPacket):
    packetId = ACSP_NEW_CONNECTION
    _content = (
        ('driverName', UTF32),
        ('driverGuid', UTF32),
        ('carId', Uint8),
        ('carModel', Ascii), # this is different type than CarInfo
        ('carSkin', Ascii),  # this is different type than CarInfo
    )

class ConnectionClosed(GenericPacket):
    packetId = ACSP_CONNECTION_CLOSED
    _content = (
        ('driverName', UTF32),
        ('driverGuid', UTF32),
        ('carId', Uint8),
        ('carModel', Ascii), # this is different type than CarInfo
        ('carSkin', Ascii),  # this is different type than CarInfo
    )

class LeaderboardEntry(GenericPacket):
    packetId = ACSP_LAP_COMPLETED
    _content = (
        ('carId', Uint8),
        ('lapTime', Uint32),
        ('laps', Uint16),
        ('completed', Uint8),
    )

leSize = LeaderboardEntry().size()
Leaderboard = GenericArrayParser('B', leSize,
    lambda x: tuple(LeaderboardEntry().from_buffer(x[(i*leSize):((i+1)*leSize)], 0)[1] for i in range(len(x)//leSize)),
    lambda x: b"".join([lbe.to_buffer()[:leSize] for lbe in x]),
)
class LapCompleted(GenericPacket):
    packetId = ACSP_LAP_COMPLETED
    _content = (
        ('carId', Uint8),
        ('lapTime', Uint32),
        ('cuts', Uint8),
        ('leaderboard', Leaderboard),
        ('gripLevel', Float),
    )

class ProtocolVersion(GenericPacket):
    packetId = ACSP_VERSION
    _content = (
        ('version', Uint8),
    )

class ChatEvent(GenericPacket):
    packetId = ACSP_CHAT
    _content = (
        ('carId', Uint8),
        ('message', UTF32),
    )

class ClientLoaded(GenericPacket):
    packetId = ACSP_CLIENT_LOADED
    _content = (
        ('carId', Uint8),
    )

class ProtocolError(GenericPacket):
    packetId = ACSP_ERROR
    _content = (
        ('message', UTF32),
    )

class GetCarInfo(GenericPacket):
    packetId = ACSP_GET_CAR_INFO
    _content = (
        ('carId', Uint8),
    )

class EnableRealtimeReport(GenericPacket):
    packetId = ACSP_REALTIMEPOS_INTERVAL
    _content = (
        ('intervalMS', Uint16),
    )

class SendChat(GenericPacket):
    packetId = ACSP_SEND_CHAT
    _content = (
        ('carId', Uint8),
        ('message', UTF32),
    )

class BroadcastChat(GenericPacket):
    packetId = ACSP_BROADCAST_CHAT
    _content = (
        ('message', UTF32),
    )

class GetSessionInfo(GenericPacket):
    packetId = ACSP_GET_SESSION_INFO
    _content = (
        ('sessionIndex', Int16),
    )

class SetSessionInfo(GenericPacket):
    packetId = ACSP_SET_SESSION_INFO
    _content = (
        ('sessionIndex', Uint8),
        ('sessionName', UTF32),
        ('sessionType', Uint8),
        ('laps', Uint32),
        ('timeSeconds', Uint32),
        ('waitTimeSeconds', Uint32),
    )

class KickUser(GenericPacket):
    packetId = ACSP_KICK_USER
    _content = (
        ('carId', Uint8),
    )

class NextSession(GenericPacket):
    packetId = ACSP_NEXT_SESSION
    _content = ()

class RestartSession(GenericPacket):
    packetId = ACSP_RESTART_SESSION
    _content = ()

class AdminCommand(GenericPacket):
    packetId = ACSP_ADMIN_COMMAND
    _content = (
        ('command', UTF32),
    )

eventMap = {
}
for e in [NewSession,
          SessionInfo,
          EndSession,
          ClientEvent,
          CarInfo,
          CarUpdate,
          NewConnection,
          ConnectionClosed,
          LapCompleted,
          ProtocolVersion,
          ChatEvent,
          ClientLoaded,
          ProtocolError,
          EnableRealtimeReport, # we need to parse this requests due to proxy
          GetCarInfo,           # we need to parse this requests due to proxy
          GetSessionInfo,       # we need to parse this requests due to proxy
          ]:
    eventMap[e.packetId] = e

def parse(buffer):
    eID,idx = Uint8.get(buffer,0)
    if eID in eventMap:
        r = eventMap[eID]()
        try:
            idx,r = r.from_buffer(buffer, idx)
        except Exception as exc:
            raise RuntimeError("Error while processing eID=%d : %s" % (eID, str(exc)))
        if type(r) in (ProtocolVersion,SessionInfo,NewSession):
            if r.version != PROTOCOL_VERSION:
                raise ProtocolVersionMismatch("Expected version %d, got version %d" % (PROTOCOL_VERSION,r.version))
        if idx != len(buffer):
            log_err("PacketId=%d: bytes left after parsing. Parsed %d bytes, got %d bytes. Packet: %s" % (eID, idx, len(buffer), str(r)))
        return r
    return None
