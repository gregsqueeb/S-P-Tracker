
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
import sys
import traceback
import zipfile
import winreg

sys.path.append("..")
import ptracker_lib
from ptracker_lib import expand_ac
from ptracker_lib.read_ui_data import *

def ac_install_dir():
    try:
        k = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam")
        v = winreg.QueryValueEx(k, "SteamPath")
        res = os.path.join(v[0], "SteamApps","common","assettocorsa")
        if os.path.isdir(res) and os.path.isfile(os.path.join(res, 'AssettoCorsa.exe')):
            print("Found using HKEY_CURRENT_USER/Software/Valve/Steam/SteamPath")
            return res
        print("Not found using HKEY_CURRENT_USER/Software/Valve/Steam/SteamPath")
    except Exception as e:
        print("Could not query HKEY_CURRENT_USER/Software/Valve/Steam/SteamPath:", str(e))
    try:
        k = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Wow6432Node\Microsoft\Windows\CurrentVersion\Uninstall\Steam App 244210")
        res = winreg.QueryValueEx(k, "InstallLocation")[0]
        if os.path.isdir(res) and os.path.isfile(os.path.join(res, 'AssettoCorsa.exe')):
            print("Found using HKEY_LOCAL_MACHINE/SOFTWARE/Wow6432Node/Microsoft/Windows/CurrentVersion/Uninstall/Steam App 244210")
            return res
        print("Not found using HKEY_LOCAL_MACHINE/SOFTWARE/Wow6432Node/Microsoft/Windows/CurrentVersion/Uninstall/Steam App 244210")
    except Exception as e:
        print("Could not query HKEY_LOCAL_MACHINE/SOFTWARE/Wow6432Node/Microsoft/Windows/CurrentVersion/Uninstall/Steam App 244210:", str(e))
    try:
        k = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\Steam App 244210")
        res = winreg.QueryValueEx(k, "InstallLocation")[0]
        if os.path.isdir(res) and os.path.isfile(os.path.join(res, 'AssettoCorsa.exe')):
            print("Found using HKEY_LOCAL_MACHINE/SOFTWARE/Microsoft/Windows/CurrentVersion/Uninstall/Steam App 244210")
            return res
        print("Not found using HKEY_LOCAL_MACHINE/SOFTWARE/Microsoft/Windows/CurrentVersion/Uninstall/Steam App 244210")
    except Exception as e:
        print("Could not query HKEY_LOCAL_MACHINE/SOFTWARE/Microsoft/Windows/CurrentVersion/Uninstall/Steam App 244210:", str(e))
    return r"C:\Program Files (x86)\Steam\SteamApps\common\assettocorsa"

def main():
    cok = 0
    cnok = 0
    r = zipfile.ZipFile("stracker-package.zip", "w")
    if len(sys.argv) <= 1:
        ac_dir = ac_install_dir()
        print("Assuming AC installation directory: ",ac_dir)
        print("This directory was obtained from the registry keys")
        print(r"  HKEY_CURRENT_USER\Software\Valve\Steam\SteamPath")
        print(r"  HKEY_CURRENT_USER\SOFTWARE\Wow6432Node\Microsoft\Windows\CurrentVersion\Uninstall\Steam App 244210\InstallLocation")
        print(r"  HKEY_CURRENT_USER\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\Steam App 244210\InstallLocation")
        print("If this is wrong, please start this script from a command line (cmd.exe) with")
        print("the real installation directory as argument. Example:")
        print('stracker-packager.exe "C:\Program Files (x86)\Steam\SteamApps\common\assettocorsa"')
    else:
        ac_dir = sys.argv[1]
        print("Assuming AC installation directory: ",ac_dir)
        print("This is the directory given at the command line.")
    car_dir = os.path.join(ac_dir, "content", "cars")
    for c in os.listdir(car_dir):
        try:
            jsf, badge = car_files(c, ac_dir)
            r.write(jsf, os.path.join("cars", c, "ui_car.json"))
            r.write(badge, os.path.join("cars", c, "badge.png"))
            cok += 1
            print(c, " ... successfully added")
        except:
            cnok += 1
            print(c, " ... error")
    track_dir = os.path.join(ac_dir, "content", "tracks")
    for t in os.listdir(track_dir):
        cntw = 0
        try:
            jsf, mpng, mini = track_files(t, ac_dir)
            r.write(jsf, os.path.join("tracks", t, "ui_track.json"))
            r.write(mpng, os.path.join("tracks", t, "map.png"))
            r.write(mini, os.path.join("tracks", t, "map.ini"))
            cntw += 1
            print(t, " ... successfully added")
        except:
            pass
        # this might (also) be a config track
        config_dir = os.path.join(track_dir, t)
        try:
            for c in os.listdir(os.path.join(config_dir, "ui")):
                try:
                    jsf, mpng, mini = track_files(t + "-" + c, ac_dir)
                    r.write(jsf, os.path.join("tracks", t+"-"+c, "ui_track.json"))
                    r.write(mpng, os.path.join("tracks", t+"-"+c, "map.png"))
                    r.write(mini, os.path.join("tracks", t+"-"+c, "map.ini"))
                    cntw += 1
                    print(t+"-"+c, " ... successfully added")
                except:
                    pass
        except:
            pass
        if cntw > 0:
            cok += 1
        else:
            cnok += 1
            print("Could not convert track %s" % t)
    return (cok, cnok)

if __name__ == "__main__":
    try:
        a=main()
        print()
        print("stracker-packager has packaged %d / %d content directories." % (a[0], a[0]+a[1]))
        print("You can send the package 'stracker-package.zip' to stracker")
        print("by logging in as admin to your stracker http server on")
        print("the 'General Admin' page.")
        print()
    except:
        print("Error occured: %s" % traceback.format_exc())
    print("Press return to finish process")
    sys.stdin.readline()