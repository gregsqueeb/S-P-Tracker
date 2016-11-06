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

import os, os.path
import io
from configparser import ConfigParser
import simplejson as json

from ptracker_lib.helpers import *

def car_files(car, ac_dir):
    car_dir = os.path.join(ac_dir, "content", "cars", car)
    jsf = os.path.join(car_dir, "ui", "ui_car.json")
    badge = os.path.join(car_dir, "ui", "badge.png")
    if os.path.isfile(jsf) and os.path.isfile(badge):
        return jsf, badge
    acdebug("no info for car %s in dir %s (%s %s)", car, ac_dir, jsf, badge)
    raise AssertionError

def track_files(track, ac_dir):
    track_dir = os.path.join(ac_dir, "content", "tracks")
    t_parts = track.split("-")
    for i in range(len(t_parts)):
        t = "-".join(t_parts[:i+1])
        c = "-".join(t_parts[i+1:])
        if c == '':
            uidir = os.path.join(track_dir, t, 'ui')
            tdir = os.path.join(track_dir, t)
        else:
            uidir = os.path.join(track_dir, t, 'ui', c)
            tdir = os.path.join(track_dir, t, c)
        jsf = os.path.join(uidir, "ui_track.json")
        mpng = os.path.join(tdir, "map.png")
        mini = os.path.join(tdir, "data", "map.ini")
        if os.path.isfile(jsf) and os.path.isfile(mpng) and os.path.isfile(mini):
            return jsf, mpng, mini
    acdebug("no info for track %s in dir %s", track, ac_dir)
    raise AssertionError

class JSONDecodeError(RuntimeError):
    pass

def _interpret_json(cont):
    if type(cont) == str:
        scont = cont
    else:
        try:
            scont = str(cont, encoding="utf-8")
        except UnicodeDecodeError:
            try:
                scont = str(cont, encoding="windows-1252")
            except:
                scont = str(cont, encoding="windows-1252", errors='ignore')
    try:
        return json.loads(scont, strict=False)
    except:
        raise JSONDecodeError()

def _rec_update(tod, fromd):
    for k in fromd.keys():
        if not k in tod:
            tod[k] = fromd[k]
        else:
            _rec_update(tod[k], fromd[k])
    return tod

def read_ui_file(filename, file_ptr, odata):
    fn = filename.replace('\\', '/')
    parts = fn.split("/")
    if parts[-1].lower() == "ui_car.json":
        carsidx = parts.index("cars")
        acname = parts[carsidx + 1].lower()
        cj = _interpret_json(file_ptr.read())
        return _rec_update(odata, {'cars': {acname : {'uiname' : cj["name"], 'brand' : cj["brand"]}}})
    if parts[-1].lower() == "badge.png":
        carsidx = parts.index("cars")
        acname = parts[carsidx + 1].lower()
        content = file_ptr.read()
        return _rec_update(odata, {'cars': {acname : {'badge' : content}}})
    if parts[-1].lower() == "ui_track.json":
        tracksidx = parts.index("tracks")
        acname = parts[tracksidx + 1]
        if len(parts) > tracksidx + 4:
            acname += "-" + parts[tracksidx + 3]
        tj = _interpret_json(file_ptr.read())
        try:
            l = tj["length"]
            if l[-2:] == "km":
                l = float(l[:-2])*1000.
            elif l[-1:] == "m":
                l = float(l[:-1])
            else:
                try:
                    l = float(l)
                except:
                    l = None
            if l < 20:
                l = l*1000. # probably a bug in a mod
        except:
            l = None
        return _rec_update(odata, {'tracks': {acname : {'uiname' : tj["name"], 'length' : l, 'tags' : tj["tags"]}}})
    if parts[-1].lower() == "map.png":
        tracksidx = parts.index("tracks")
        acname = "-".join(parts[tracksidx + 1:-1])
        content = file_ptr.read()
        return _rec_update(odata, {'tracks': {acname : {'mpng' : content}}})
    if parts[-1].lower() == "map.ini":
        tracksidx = parts.index("tracks")
        acname = parts[tracksidx + 1]
        if len(parts) > tracksidx + 3:
            acname += "-" + parts[tracksidx + 2]
        cp = ConfigParser(strict=False, allow_no_value=True)
        cp.read_file(io.TextIOWrapper(file_ptr))

        return _rec_update(odata, {'tracks': {acname : {'mini' :
            dict(width=cp['PARAMETERS']['WIDTH'],
                 height=cp['PARAMETERS']['HEIGHT'],
                 scale=cp['PARAMETERS']['SCALE_FACTOR'],
                 xoffset=cp['PARAMETERS']['X_OFFSET'],
                 zoffset=cp['PARAMETERS']['Z_OFFSET'])
        }}})
    return odata


