
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

import re
import traceback
from ptracker_lib.helpers import *
from stracker_lib import config
from stracker_lib import acauth

class BanListHandler:
    def __init__(self, db, acmonitor, udp_plugin):
        self.db = db
        self.acmonitor = acmonitor
        self.udp_plugin = udp_plugin
        self.blacklisted_guids = set()

    def available(self):
        return not self.blacklisted_guids is None

    def onCommand(self, command, dbGuidMapper):
        try:
            splitted = command.strip().split(" ")
            cmd = splitted[0]
            pid = splitted[1]
            if len(splitted) > 2:
                days = splitted[2]
            else:
                days = 0
            days = float(days)
            d = None
            if cmd == "guid":
                guid = dbGuidMapper.guid_orig(pid)
                d = self.acmonitor.allDrivers.byGuidActive(guid)
                pid = d.carId
            elif cmd == "id":
                pid= int(pid)
                d = acmonitor.allDrivers.byCarId(pid)
            if days == 0:
                admincmd = "/kick_id %d" % pid
            else:
                admincmd = "/ban_id %d" % pid
                acdebug("extending ban for %s to %d seconds",d.guid,60*60*24*days)
                self.db.modifyBlacklistEntry(__sync=True, importedGuid = d.guid, extendPeriod = 60*60*24*days)()
                acauth.AuthCache.singleton.rescanBlacklist()
            acinfo("issuing admin command: %s", admincmd)
            self.udp_plugin.acPlugin.adminCommand(admincmd)
            return "ok ("+admincmd+")"
        except:
            acwarning("Error while trying to kick/ban a player:")
            acwarning(traceback.format_exc())
            return False

    def helpCommands(self):
         return ["/st kickban guid <guid> [<daysToBan>]",
                 "/st kickban id <id> [<daysToBan>]"]
