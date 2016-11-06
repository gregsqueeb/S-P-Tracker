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
from ptracker_lib.ac_ini_files import *
from ptracker_lib import acsim
import copy

class SessionStateTracker:
    def __init__(self):
        self.race_ini_file = RaceIniFile()

        if acsim.ac.getServerIP() != '':
            self.allowedTyresOut = None
        else:
            p = self.race_ini_file.penalties()
            self.allowedTyresOut = p['allowedTyresOut']
        self.penaltiesEnabled = None
        self.tyreWearFactor = None
        self.fuelRate = None
        self.damage = None
        self.lastLogged = None
        self.log()

    def update(self, serverData):
        if 'session_state' in serverData:
            session_state = serverData['session_state']
            if 'allowedTyresOut' in session_state: self.allowedTyresOut = session_state['allowedTyresOut']
        self.log()

    def update_from_sim_info(self, sim_info_obj):
        self.penaltiesEnabled = sim_info_obj.static.penaltiesEnabled
        self.tyreWearFactor = sim_info_obj.static.aidTireRate
        self.fuelRate = sim_info_obj.static.aidFuelRate
        self.damage = sim_info_obj.static.aidMechanicalDamage

    def staticSessionState(self):
        return dict(penaltiesEnabled=self.penaltiesEnabled,
                    allowedTyresOut=self.allowedTyresOut,
                    tyreWearFactor=self.tyreWearFactor,
                    fuelRate=self.fuelRate,
                    damage=self.damage)

    def log(self):
        if 0:
            logMsg = ""
            for a in ("penaltiesEnabled","allowedTyresOut", "tyreWearFactor", "fuelRate", "damage"):
                logMsg += "%s = %4s; " % (a, getattr(self, a))
            if logMsg != self.lastLogged:
                self.lastLogged = logMsg
                acinfo(logMsg)
                acsim.ac.console(logMsg)

class AssistanceTracker:
    def __init__(self):
        self.assists_ini_file = AssistsIniFile()
        self.controls_ini_file = ControlsIniFile()
        self.assists_static = self.assists_ini_file.assists()
        self.assists_static.update(self.controls_ini_file.controls_used())
        self.assists_static.update(dict(
            autoBlib = None,
            autoClutch = None,
            stabilityControl = None,
            tyreBlankets = None))
        self.resetDynamicAssists()
        self.lastLogged = None
        self.log()

    def resetDynamicAssists(self):
        self.assists_dynamic = {
            'ABS':0.0,
            'tractionControl':0.0,
            'idealLine': False,
            'autoShifter':False,
        }

    def update(self, sim_info_obj):
        self.assists_static['autoBlib'] = sim_info_obj.static.aidAutoBlib
        self.assists_static['autoClutch'] = sim_info_obj.static.aidAutoClutch
        self.assists_static['stabilityControl'] = sim_info_obj.static.aidStability
        self.assists_static['tyreBlankets'] = sim_info_obj.static.aidAllowTyreBlankets
        self.assists_dynamic['ABS'] = float(max(self.assists_dynamic['ABS'], float(sim_info_obj.physics.abs)))
        self.assists_dynamic['tractionControl'] = float(max(self.assists_dynamic['tractionControl'], float(sim_info_obj.physics.tc)))
        if sim_info_obj.graphics.idealLineOn: self.assists_dynamic['idealLine'] = True
        if sim_info_obj.physics.autoShifterOn: self.assists_dynamic['autoShifter'] = True
        self.assists_dynamic['ambientTemp'] = round(sim_info_obj.physics.airTemp)
        self.assists_dynamic['trackTemp'] = round(sim_info_obj.physics.roadTemp)
        self.log()

    def staticAssists(self):
        return copy.deepcopy(self.assists_static)

    def dynamicAssists(self):
        return copy.deepcopy(self.assists_dynamic.copy())

    def log(self, reason = "update"):
        if 0:
            logMsg = reason + ": "
            for a in [self.dynamicAssists(), self.staticAssists(),]:
                for k in sorted(a.keys()):
                    logMsg += "%s = %4s; " % (k, a[k])
                logMsg += "|"
            if logMsg != self.lastLogged:
                self.lastLogged = logMsg
                acinfo(logMsg)
                acsim.ac.console(logMsg)
