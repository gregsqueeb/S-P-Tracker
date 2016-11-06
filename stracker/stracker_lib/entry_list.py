
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
import os.path
from stracker_lib import config
from ptracker_lib.helpers import *

def generate_entry_list(session_details):
    # read the original entry list
    cp = configparser.ConfigParser(allow_no_value=False, strict=False, interpolation=None)
    ac_server_cfg = config.config.STRACKER_CONFIG.ac_server_cfg_ini
    entry_list = os.path.join(os.path.dirname(ac_server_cfg), "entry_list.ini")
    cp.read(entry_list, encoding="utf-8")

    carIdsToValues = {}
    guidToCarId = {}
    unassignedCars = {}

    carId = 0
    while 1:
        section = "CAR_%d"%carId
        name = cp.get(section, "DRIVERNAME", fallback=None)
        team = cp.get(section, "TEAM", fallback=None)
        car = cp.get(section, "MODEL", fallback=None)
        skin = cp.get(section, "SKIN", fallback=None)
        guid = cp.get(section, "GUID", fallback=None)
        spec = cp.getint(section, "SPECTATOR_MODE", fallback=0)
        carIdsToValues[carId] = dict(name=name,team=team,car=car,skin=skin,guid=guid,spec=spec)
        acinfo("carIdsToValues[%d]=%s", carId, carIdsToValues[carId])
        if spec == 0 and not car in ["", None]:
            if not guid == "":
                myassert (not guid in guidToCarId)
                guidToCarId[guid] = carId
            else:
                if not car in unassignedCars:
                    unassignedCars[car] = []
                unassignedCars[car].append(carId)
        elif name is None:
            numCars = carId
            break
        carId += 1

    result = ""
    carIdsProcessed = set()
    classification = session_details['classification']
    for idx,p in enumerate(classification):
        guid = p['guid']
        name = p['name']
        car = p['car']
        if guid in guidToCarId:
            carIdOrig = guidToCarId[guid]
            del guidToCarId[guid]
        else:
            carIdOrig = unassignedCars[car][0]
            unassignedCars[car] = unassignedCars[car][1:]
        carIdsProcessed.add(carIdOrig)
        ei = carIdsToValues[carIdOrig]
        team = ei['team'] or ""
        skin = ei['skin'] or ""
        result += """[CAR_%(idx)d]
DRIVERNAME=%(name)s
MODEL=%(car)s
TEAM=%(team)s
SKIN=%(skin)s
GUID=%(guid)s
SPECTATOR_MODE=0

""" % locals()

    for carId in range(numCars):
        if not carId in carIdsProcessed:
            idx = len(carIdsProcessed)
            carIdsProcessed.add(carId)
            ei = carIdsToValues[carIdOrig]
            name=ei['name'] or ""
            team=ei['team'] or ""
            car=ei['car'] or ""
            skin=ei['skin'] or ""
            guid=ei['guid'] or ""
            spec=ei['spec'] or 0
            result += """[CAR_%(idx)d]
DRIVERNAME=%(name)s
MODEL=%(car)s
TEAM=%(team)s
SKIN=%(skin)s
GUID=%(guid)s
SPECTATOR_MODE=%(spec)d

""" % locals()

    return "<code>" + result.replace("\n", "<br>\n") + "</code>"
