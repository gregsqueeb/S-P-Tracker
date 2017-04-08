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
import os.path
from threading import Thread, RLock
import traceback
import time

from ptracker_lib import expand_ac
from ptracker_lib.helpers import *

class ACLogParser:

    def __init__(self, path = None):
        if path is None:
            self._log_path = expand_ac.expand_ac('Assetto Corsa/logs/log.txt')
        else:
            self._log_path = path
        try:
            _log_f = open(self._log_path, 'r', encoding='utf-8', errors='replace')
            # try to read steam guid from logs
            self._steam_guid_regex = re.compile(r'^Steam Community ID:\s*([0-9]+)')
            self._guid = None
            for line_num in range(20):
                line = _log_f.readline()
                M = self._steam_guid_regex.match(line)
                if not M is None:
                    self._guid = M.group(1)
                    break
        except:
            self._guid = None
        if not self._guid is None:
            acinfo("Acquired steam guid from AC log file: '%s'", self._guid)
        else:
            acwarning("Cannot acquire steam guid from AC log file.")
        self._log_path = expand_ac.expand_ac('Assetto Corsa/logs/ptracker_fileobserver.txt')
        self._setup_path = expand_ac.expand_ac('Assetto Corsa/setups')
        self._read_regex  = re.compile(r'^r: (' + re.escape(self._setup_path.replace('/','\\')) + r'.*\.ini$)')
        self._write_regex = re.compile(r'^w: (' + re.escape(self._setup_path.replace('/','\\')) + r'.*\.ini$)')
        self._current_setup = None
        self._current_name = None
        self._lock = RLock()
        self._finished = False
        self._thread = Thread(target=self.run)
        self._thread.setDaemon(True)
        self._thread.start()

    def shutdown(self):
        self._finished = True
        if not self._thread is None:
            self._thread.join()

    def guid(self):
        return self._guid

    def setupChanged(self, newset):
        with self._lock:
            try:
                content = open(newset, "rb").read()
                self._current_setup = content
                self._current_name = os.path.splitext(os.path.basename(newset))[0]
                acinfo("new set: %s", newset)
            except:
                acwarning("cannot read setup %s", newset)
                acwarning(traceback.format_exc())

    def getCurrentSetup(self, with_name = False):
        with self._lock:
            if with_name:
                return self._current_setup, self._current_name
            return self._current_setup

    def run(self):
        acinfo("Log file parser started.")
        self._log_f = None
        for i in range(5):
            try:
                self._log_f = open(self._log_path, 'r', encoding='utf-8', errors='replace')
                break
            except:
                self._log_f = None
                time.sleep(1)
        if self._log_f is None:
            acerror("Cannot open log file")
        else:
            linesRead = 0
            try:
                lastL = None
                while not self._finished:
                    where = self._log_f.tell()
                    line = self._log_f.readline()
                    if not line or line[-1] != "\n":
                        time.sleep(1)
                        self._log_f.seek(where)
                    else:
                        linesRead += 1
                        Mr = self._read_regex.match(line)
                        if not Mr is None:
                            self.setupChanged(Mr.group(1))
                        Mw = self._write_regex.match(line)
                        if not Mw is None:
                            self.setupChanged(Mw.group(1))
                        if not Mr and not Mw:
                            acdebug("logparser, got non-matching line: %s", line.strip())
            except:
                acerror("Error while parsing ac log file.")
                acerror(traceback.format_exc())
        acinfo("Log file parser finished (read %d lines).", linesRead)

if __name__ == "__main__":
    aclp = ACLogParser("C:/temp/log_KommyKT.txt")
    time.sleep(5)
    aclp.shutdown()
