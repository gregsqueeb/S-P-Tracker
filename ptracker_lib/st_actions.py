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
from ptracker_lib.message_types import *
from ptracker_lib import acsim
from ptracker_lib.ps_protocol import ProtocolHandler

class StActKickBanDriver:
    def __init__(self, ptracker):
        self.ptracker = ptracker

    def available(self, carId):
        return self.ptracker.isStrackerAdmin() and not self.ptracker.localIdToGuid(carId) is None

    def commit(self, carId, numDays):
        if self.available(carId):
            acsim.ac.sendChatMessage("/st kickban guid %s %d" % (self.ptracker.localIdToGuid(carId), numDays))
            if numDays == 0:
                message = "Driver %s kicked from server" % (acsim.ac.getDriverName(carId))
            else:
                message = "Driver %s banned for %d days" % (acsim.ac.getDriverName(carId), numDays)
            self.ptracker.addMessage(text=message,
                                     color=(1.0,1.0,1.0,1.0),
                                     mtype=MTYPE_LOCAL_FEEDBACK)
        else:
            message = "Cannot ban driver (need to be in stracker 'admins' group)"
        self.ptracker.addMessage(text=message,
                                 color=(1.0,1.0,1.0,1.0),
                                 mtype=MTYPE_LOCAL_FEEDBACK)

class StActSendSetup:
    def __init__(self, ptracker):
        self.ptracker = ptracker

    def available(self, carId):
        ptc = self.ptracker.ptClient
        return not ptc is None and (ptc.capabilities() & ProtocolHandler.CAP_SEND_SETUP) != 0 and not self.ptracker.localIdToGuid(carId) is None

    def commit(self, carId):
        ptc = self.ptracker.ptClient
        if self.available(carId):
            setup = self.ptracker.acLogParser.getCurrentSetup()
            if not setup is None:
                stype, trackname, carname = self.ptracker.lastSessionType
                acdebug("send setup activated %d", carId)
                self.ptracker.ptClient.send_setup(self.ptracker.localIdToGuid(carId), setup, carname)
                receiver = acsim.ac.getDriverName(carId)
                message = "Setup sent to %s" % receiver
            else:
                message = "No setup available (check http://n-e-y-s.de/stracker_doc FAQ section)"
        else:
            message = "Setup sending is not available for this player"
        self.ptracker.addMessage(text=message,
                                 color=(1.0,1.0,1.0,1.0),
                                 mtype=MTYPE_LOCAL_FEEDBACK)

