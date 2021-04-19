
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
import keyvalues

sys.path.append("..")
import ptracker_lib
from ptracker_lib import expand_ac
from ptracker_lib.read_ui_data import *


def is_ac_install_dir(directory):
    return os.path.isdir(directory) and os.path.isfile(os.path.join(directory, 'AssettoCorsa.exe'))

def try_standard_dir(steamapps):
    res = os.path.join(steamapps, "common", "assettocorsa")
    if is_ac_install_dir(res):
        return res
    return None

def try_library(steamapps):
    manifest = os.path.join(steamapps, "appmanifest_244210.acf")
    if os.path.isfile(manifest):
        kv = keyvalues.KeyValues(filename=manifest)
        installdir = os.path.join(steamapps, "common", kv['AppState']['installdir'])
        if is_ac_install_dir(installdir):
            print("Found using manifest")
            return installdir
    res = try_standard_dir(steamapps)
    if res is not None:
        print("Found using standard dir")
        return res
    return None

def try_steam_registry_key(hkey, skey, value):
    if hkey == winreg.HKEY_CURRENT_USER:
        hkeystr = "HKEY_CURRENT_USER"
    elif hkey == winreg.HKEY_LOCAL_MACHINE:
        hkeystr = "HKEY_LOCAL_MACHINE"
    try:
        k = winreg.OpenKey(hkey, skey)
        v = winreg.QueryValueEx(k, value)
        steamapps = os.path.join(v[0], "steamapps")
        res = try_library(steamapps)
        if res is not None:
            print(f"Found using {hkeystr}/{skey}/{value}")
            return res
        libraries = os.path.join(steamapps, "libraryfolders.vdf")
        if os.path.isfile(libraries):
            kv = keyvalues.KeyValues(filename=libraries)
            for key in kv['LibraryFolders']:
                library = kv['LibraryFolders'][key]
                library = library.replace(r"\\", "\\")
                steamapps = os.path.join(library, "steamapps")
                # there are values other than directories, filter them out with isdir
                if os.path.isdir(steamapps):
                    res = try_library(steamapps)
                    if res is not None:
                        print(f"Found using libraryfolders.vdf and {hkeystr}\\{skey}\\{value}")
                        return res

        print(f"Not found using {hkeystr}\\{skey}\\{value}")
    except Exception as e:
        print(f"Could not query {hkeystr}\\{skey}\\{value}:", str(e))
    return None

def try_uninstall_registry_key(skey):
    try:
        k = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, skey)
        res = winreg.QueryValueEx(k, "InstallLocation")[0]
        if is_ac_install_dir(installdir):
            print(f"Found using HKEY_LOCAL_MACHINE\\{skey}\\InstallLocation")
            return res
        print(f"Not found using HKEY_LOCAL_MACHINE\\{skey}\\InstallLocation")
    except Exception as e:
        print(f"Could not query HKEY_LOCAL_MACHINE\\{skey}\\InstallLocation:", str(e))
    return None

def ac_install_dir():
    res = try_steam_registry_key(winreg.HKEY_CURRENT_USER, r"SOFTWARE\Valve\Steam", "steampath")
    if res is not None:
        return res
    res = try_steam_registry_key(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam", "InstallPath")
    if res is not None:
        return res
    res = try_steam_registry_key(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Valve\Steam", "InstallPath")
    if res is not None:
        return res
    res = try_uninstall_registry_key(r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\Steam App 244210")
    if res is not None:
        return res
    res = try_uninstall_registry_key(r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\Steam App 244210")
    if res is not None:
        return res
    # Fall back to a reasonable default
    return r"C:\Program Files (x86)\Steam\SteamApps\common\assettocorsa"

def main():
    cok = 0
    cnok = 0
    r = zipfile.ZipFile("stracker-package.zip", "w")
    if len(sys.argv) <= 1:
        ac_dir = ac_install_dir()
        print("Assuming AC installation directory: ",ac_dir)
        print("This directory was obtained from the registry keys")
        print(r"  HKEY_CURRENT_USER\SOFTWARE\Valve\Steam\steampath")
        print(r"  HKEY_LOCAL_MACHINE\SOFTWARE\WOW6432Node\Valve\Steam\InstallPath")
        print(r"  HKEY_LOCAL_MACHINE\SOFTWARE\Valve\Steam\InstallPath")
        print(r"  HKEY_LOCAL_MACHINE\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\Steam App 244210\InstallLocation")
        print(r"  HKEY_LOCAL_MACHINE\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\Steam App 244210\InstallLocation")
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
        except Exception as e:
            cnok += 1
            print(c, " ... error")
            print(e)
    first_exception = None
    track_dir = os.path.join(ac_dir, "content", "tracks")
    for t in os.listdir(track_dir):
        cntw = 0
        try:
            jsf, mpng, mini, sections = track_files(t, ac_dir)
            r.write(jsf, os.path.join("tracks", t, "ui_track.json"))
            r.write(mpng, os.path.join("tracks", t, "map.png"))
            r.write(mini, os.path.join("tracks", t, "map.ini"))
            if sections is not None:
                r.write(sections, os.path.join("tracks", t, "sections.ini"))
            cntw += 1
            print(t, " ... successfully added")
        except Exception as e:
            first_exception = e
            pass
        # this might (also) be a config track
        config_dir = os.path.join(track_dir, t)
        try:
            for c in os.listdir(os.path.join(config_dir, "ui")):
                if os.path.isdir(os.path.join(config_dir, "ui", c)):
                    try:
                        jsf, mpng, mini, sections = track_files(t + "-" + c, ac_dir)
                        r.write(jsf, os.path.join("tracks", t+"-"+c, "ui_track.json"))
                        r.write(mpng, os.path.join("tracks", t+"-"+c, "map.png"))
                        r.write(mini, os.path.join("tracks", t+"-"+c, "map.ini"))
                        if sections is not None:
                            r.write(sections, os.path.join("tracks", t+"-"+c, "sections.ini"))
                        cntw += 1
                        print(t+"-"+c, " ... successfully added")
                    except Exception as e:
                        print(t+"-"+c, " ... error")
                        print(e)
                        pass
        except:
            pass
        if cntw > 0:
            cok += 1
        else:
            cnok += 1
            print("Could not convert track %s" % t)
            print(first_exception)
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