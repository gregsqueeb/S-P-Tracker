
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

import sys
import os, os.path
import time
import random
import shutil
import configparser
localp = os.path.split(__file__)[0]
if localp == "": localp = "."
sys.path.append(localp + "/../stracker")
sys.path.append(localp + "/..")
sys.path.append(localp + "/../stracker/externals")
import virtual_ac_server

time_factor = 10.

oldTime = time.time
def newTime():
    return oldTime()*time_factor

oldSleep = time.sleep
def newSleep(t):
    return oldSleep(t/time_factor)

time.time = newTime
time.sleep = newSleep

if __name__ == "__main__":
    #random.seed(7)
    vs = virtual_ac_server.VirtualServer()
    server_cfg = os.path.abspath(localp + "/fake_server_cfg.ini")
    stracker_ini = os.path.abspath(localp + "/fake_stracker.ini")
    log_file = os.path.abspath(localp + "/fake_stracker.log")
    open(server_cfg, "w").write(vs.getFakeConfig())
    shutil.copy(localp + "/../stracker/stracker-default.ini", stracker_ini)
    cp = configparser.ConfigParser(strict=False, allow_no_value=True)
    cp.read(stracker_ini)
    cp['STRACKER_CONFIG']['ac_server_cfg_ini'] = server_cfg
    cp['STRACKER_CONFIG']['log_file'] = log_file
    cp['STRACKER_CONFIG']['log_timestamps'] = 'True'
    cp['HTTP_CONFIG']['admin_username'] = 'a'
    cp['HTTP_CONFIG']['admin_password'] = 'a'
    cp['HTTP_CONFIG']['enabled'] = 'True'
    dbfile = os.path.abspath(localp + "/fake_starcker.db3")
    if os.path.exists(dbfile): os.remove(dbfile)
    cp['DATABASE']['database_file'] = dbfile
    cp.write(open(stracker_ini, "w"))
    print(sys.executable)
    pwd = os.getcwd()
    os.chdir(localp+"/../stracker")
    stracker_proc = os.spawnl(os.P_NOWAIT, sys.executable, sys.executable, "stracker.py", "--stracker_ini", stracker_ini)
    os.chdir(pwd)
    vs.start()
    while not vs.stopped:
        time.sleep(1)
