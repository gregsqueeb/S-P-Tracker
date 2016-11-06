
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
import shutil
import sys
import traceback
import zipfile
import winreg
import argparse
import tempfile
import shutil
import zipfile
import configparser
import subprocess
import atexit
import time

sys.path.append("../..")
import ptracker_lib
from ptracker_lib import expand_ac

def ac_install_dir():
    k = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam")
    v = winreg.QueryValueEx(k, "SteamPath")
    res = os.path.join(v[0], "SteamApps","common","assettocorsa")
    if os.path.isdir(res):
        return res
    k = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Wow6432Node\Microsoft\Windows\CurrentVersion\Uninstall\Steam App 244210")
    res = winreg.QueryValueEx(k, "InstallLocation")
    return res[0]

def cfg_replace(file, *args):
    cp = configparser.ConfigParser(interpolation=None)
    cp.optionxform=str
    cp.read(file)
    for section,key,value in args:
        cp[section][key] = value
    cp.write(open(file, "w+"), space_around_delimiters=False)

class TestClass:
    def __init__(self, num_servers, src, work):
        self.spawned = []
        self.cleanup_workdir = work is None
        atexit.register(self.cleanup)
        if work is None:
            self.wdir = tempfile.mkdtemp(prefix='stracker_test_')
            wdir = self.wdir
        else:
            self.wdir = os.path.abspath(work)
            wdir = self.wdir
            if not os.path.exists(wdir):
                os.mkdir(wdir)
        print("working dir: %s" % wdir)
        acdir = ac_install_dir()
        pwd = os.getcwd()
        os.chdir(acdir + "/server")
        subprocess.check_call(["acServerManager.exe", "/pack", "/nomsg"])
        os.chdir(pwd)
        acsdir = wdir + "/acserver"
        if os.path.exists(acsdir): shutil.rmtree(acsdir)
        shutil.copytree(acdir + "/server", acsdir)
        if src != ".":
            stdir = wdir + "/stracker"
            if os.path.exists(stdir): shutil.rmtree(stdir)
            os.mkdir(stdir)
            z = zipfile.ZipFile(open(src, "rb"))
            z.extractall(stdir)
            stracker_bin = [stdir + "/stracker.exe"]
        else:
            stdir = os.path.split(os.path.abspath(__file__))[0] + "/.."
            stracker_bin = [sys.executable, stdir + "/stracker.py"]
            os.environ["PYTHONPATH"] = stdir + "/..;" + stdir + "/externals;" + stdir
            try:
                os.remove("%s/stracker-default.ini"%stdir)
            except OSError:
                pass
            try:
                subprocess.check_call(stracker_bin+ ["--stracker_ini=%s/stracker-default.ini"%stdir])
            except subprocess.CalledProcessError:
                pass
        tracks = [("nurburgring-sprint",""), ("vallelunga", "club_circuit"), ("silverstone-national", "")]
        cars = [("bmw_1m_s3","bmw_m3_e30_gra"), ("ferrari_458","p4-5_2011")]
        for i in range(num_servers):
            cfgdir = wdir + "/cfg%d" % i
            if os.path.exists(cfgdir): shutil.rmtree(cfgdir)
            os.mkdir(cfgdir)
            shutil.copy(acdir + "/server/cfg/server_cfg.ini", cfgdir)
            cfg_replace(cfgdir + "/server_cfg.ini",
                        ("SERVER", "ADMIN_PASSWORD", "a"),
                        ("SERVER", "REGISTER_TO_LOBBY", "0"),
                        ("SERVER", "UDP_PORT", "%d"%(9600+i+10)),
                        ("SERVER", "TCP_PORT", "%d"%(9600+i+10)),
                        ("SERVER", "HTTP_PORT", "%d"%(8081+i+10)),
                        ("SERVER", "UDP_PLUGIN_LOCAL_PORT", "%d"%(11000+i+10)),
                        ("SERVER", "UDP_PLUGIN_ADDRESS", "127.0.0.1:%d"%(12000+i+10)),
                        ("SERVER", "NAME", "stracker-test-server %d" % i),
                        ("SERVER", "TRACK", tracks[i%len(tracks)][0]),
                        ("SERVER", "CONFIG_TRACK", tracks[i%len(tracks)][1]),
                        ("SERVER", "CARS", ";".join(cars[i%len(cars)])),
                        ("SERVER", "MAX_CLIENTS", "3"),
                        )
            repl = []
            for j in range(3):
                cl = cars[i%len(cars)]
                repl.append( ("CAR_%d" % j, "MODEL", cl[j%len(cl)]) )
            shutil.copy(acdir + "/server/cfg/entry_list.ini", cfgdir)
            cfg_replace(cfgdir + "/entry_list.ini", *repl)

            shutil.copy(stdir + "/stracker-default.ini", cfgdir + "/stracker.ini")
            cfg_replace(cfgdir + "/stracker.ini",
                        ("STRACKER_CONFIG", "ac_server_cfg_ini", cfgdir + "/server_cfg.ini"),
                        ("STRACKER_CONFIG", "listening_port", "%d"%(9642+i+10)),
                        ("STRACKER_CONFIG", "log_file", wdir + "/stracker%d.log"%i),
                        ("STRACKER_CONFIG", "log_level", "debug"),
                        ("STRACKER_CONFIG", "log_timestamps", "True"),
                        ("STRACKER_CONFIG", "server_name", "testserver%d"%i),
                        ("STRACKER_CONFIG", "tee_to_stdout", "False"),
                        ("SESSION_MANAGEMENT", "race_over_strategy", "skip"),
                        ("DATABASE", "database_file", wdir + "/stracker.db3"),
                        ("HTTP_CONFIG", "admin_password", "a"),
                        ("HTTP_CONFIG", "admin_username", "a"),
                        ("HTTP_CONFIG", "enabled", "True" if i == 0 else "False"),
                        )
        for i in range(num_servers):
            cfgdir = wdir + "/cfg%d" % i
            acs_stdout = wdir + "/acserver%d.log" % i
            os.chdir(acsdir)
            scfg = ("%s/server_cfg.ini" % cfgdir).replace("/", "\\")
            ecfg = ("%s/entry_list.ini" % cfgdir).replace("/", "\\")
            self.spawned.append(subprocess.Popen(["./acServer.exe", "-c=%s"%scfg, "-e=%s"%ecfg], stderr=subprocess.STDOUT, stdout=open(acs_stdout,"w")))
            os.chdir(pwd)
            self.spawned.append(subprocess.Popen(stracker_bin + ["--stracker_ini=%s/stracker.ini" % cfgdir]))

    def cleanup(self):
        print("killing tasks ...")
        for p in self.spawned:
            if p.poll() is None:
                p.kill()
        print("wait for processes to finish ...")
        time.sleep(1)
        if self.cleanup_workdir:
            print("cleaning up")
            shutil.rmtree(self.wdir, ignore_errors=True)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Spawn a test of stracker together with attached acServer process')
    parser.add_argument("--num_servers", required=True, help='number of acServer processes to be created.')
    parser.add_argument("--src", required=True, help='zip file containing stracker.')
    parser.add_argument("--work", required=False, default="", help='working directory. default create new temporary dir.')
    args = parser.parse_args()
    t = TestClass(int(args.num_servers), args.src, args.work if not args.work is None else None)
    while 1:
        #wait forever
        time.sleep(1)

