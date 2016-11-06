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

import configparser
import traceback
import os.path
from ptracker_lib import acsim
from ptracker_lib.expand_ac import expand_ac
from ptracker_lib.helpers import *

class BaseACIniFile:
    def __init__(self, filename):
        self._ini_path = expand_ac(os.path.join('Assetto Corsa','cfg',filename))
        self._parser = configparser.ConfigParser(strict=False, interpolation=None, allow_no_value=True, inline_comment_prefixes=(';',))
        try:
            try:
                self._parser.read(self._ini_path)
            except UnicodeError as e:
                acwarning("Cannot read %s, trying with utf-8 encoding", self._ini_path)
                self._parser.read(self._ini_path, encoding='utf-8')
        except Exception as e:
            try:
                error_text = str(e)
            except:
                error_text = traceback.format_exc()
            acwarning("Error while reading file '%s': %s", self._ini_path, error_text)
            acwarning("Error is ignored, but ptracker may behave unexpected.")

class RaceIniFile(BaseACIniFile):
    def __init__(self):
        BaseACIniFile.__init__(self,'race.ini')

    def guid(self):
        res = self._parser.get('REMOTE', 'GUID', fallback=None)
        if res is None or res == "":
            res = None
        return res

    def serverPort(self):
        if acsim.ac.getServerIP() == '':
            return 0
        else:
            return self._parser.getint('REMOTE', 'SERVER_PORT', fallback=0)

    def penalties(self):
        return {'penalties': self._parser.getint('RACE', 'PENALTIES', fallback=None),
                'allowedTyresOut': self._parser.getint('LAP_INVALIDATOR', 'ALLOWED_TYRES_OUT', fallback=None),
                }

class ControlsIniFile(BaseACIniFile):
    def __init__(self):
        BaseACIniFile.__init__(self,'controls.ini')

    def controls_used(self):
        input_method = self._parser.get('HEADER', 'INPUT_METHOD', fallback=None)
        if type(input_method) == type(""): input_method = input_method.lower()
        shifter = self._parser.getint('SHIFTER', 'ACTIVE', fallback=None)
        shifter_joy = self._parser.getint('SHIFTER', 'JOY', fallback=None)
        if shifter and shifter_joy: shifter = 2
        return {'input_method':input_method,
                'shifter':shifter}

class AssistsIniFile(BaseACIniFile):
    def __init__(self):
        BaseACIniFile.__init__(self,'assists.ini')

    def assists(self):
        res = dict(
            autoBrake = self._parser.getint('ASSISTS', 'AUTO_BRAKE', fallback=None),
            ABS = self._parser.getint('ASSISTS', 'ABS', fallback=None),
            tractionControl = self._parser.getint('ASSISTS', 'TRACTION_CONTROL', fallback=None),
            visualDamage = self._parser.getint('ASSISTS', 'VISUALDAMAGE', fallback=None),
            slipStream = self._parser.getint('ASSISTS', 'SLIPSTREAM', fallback=None),
        )
        if not res['ABS'] is None:
            # mapping of ABS and TC is as follows:
            #   -1: ABS is turned off completely ("Off")
            #   0: ABS is set to "Factory"
            #   1: ABS is set to "On", regardless of ABS is present in the current car
            res['ABS'] -=  1
        if not res['tractionControl'] is None:
            res['tractionControl'] -= 1
        return res

class VideoIniFile(BaseACIniFile):
    def __init__(self):
        BaseACIniFile.__init__(self,'video.ini')

    def resolution(self):
        res = dict(width=self._parser.getint('VIDEO', 'WIDTH', fallback=1920),
                   height=self._parser.getint('VIDEO', 'HEIGHT', fallback=1080),
                   triple=self._parser.get('CAMERA', 'MODE', fallback=None).lower() == "triple")
        if res['triple']: res['width'] *= 3
        return res

class GamePlayIniFile(BaseACIniFile):
    def __init__(self):
        BaseACIniFile.__init__(self,'gameplay.ini')

    def allowAppsOverlapping(self):
        try:
            res = self._parser.getint('GUI', 'ALLOW_OVERLAPPING_FORMS')
        except:
            acerror("Cannot read apps overlapping setting. Returning None")
            acerror(traceback.format_exc())
            res = None
        return res
