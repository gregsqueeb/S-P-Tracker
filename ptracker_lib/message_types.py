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

from ptracker_lib.helpers import *

# message types
MTYPE_UNKNOWN = -1
MTYPE_ENTER_LEAVE = 0
MTYPE_BEST_LAP = 1
MTYPE_CHECKSUM_ERRORS = 2
MTYPE_WELCOME = 3
MTYPE_LOCAL_FEEDBACK = 4
MTYPE_LOCAL_PB = 5
MTYPE_SETUP_RECEIVED = 6
MTYPE_SETUP_SAVED = 7
MTYPE_RACE_FINISHED = 8
MTYPE_CHAT = 9
MTYPE_COLLISION = 10

def messageToString(mtype):
    # message strings must be python identifiers
    m2s = {
        MTYPE_ENTER_LEAVE       : "enter_leave",
        MTYPE_BEST_LAP          : "best_lap",
        MTYPE_CHECKSUM_ERRORS   : "checksum_errors",
        MTYPE_WELCOME           : "welcome",
        MTYPE_LOCAL_FEEDBACK    : "local_feedback",
        MTYPE_LOCAL_PB          : "local_pb",
        MTYPE_SETUP_RECEIVED    : "setup_rcv",
        MTYPE_SETUP_SAVED       : "setup_saved",
        MTYPE_RACE_FINISHED     : "race_finished",
        MTYPE_CHAT              : "chat",
        MTYPE_COLLISION         : "collision",
    }
    res = m2s.get(mtype, None)
    if res is None:
        acdebug("mtype=%s, not found in dict %s", mtype, m2s)
        res = 'unknown'
    return res

def messageColorToType(color):
    if color == (1.0,0.0,0.0,1.0):
        return MTYPE_CHECKSUM_ERRORS
    if color == (1.0,1.0,1.0,1.0):
        return MTYPE_ENTER_LEAVE
    if color == (1.0, 0.5, 1.0, 1.0):
        return MTYPE_BEST_LAP
    if color == (0.0, 1.0, 0.0, 1.0):
        return MTYPE_BEST_LAP
    return MTYPE_UNKNOWN

