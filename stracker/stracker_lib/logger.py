
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

import functools
import sys
import datetime

LOG_LEVEL_INFO = 0
LOG_LEVEL_DEBUG = 1
LOG_LEVEL_DUMP = 2

class Logger:
    def __init__(self):
        self.log_file_obj = sys.stdout
        self.log_level = LOG_LEVEL_INFO
        self.log_timestamps = False

    def setLogLevel(self, logLevel):
        self.log_level = logLevel

    def log(self, msg, *args, **kw):
        prefix = ""
        if 'prefix' in kw:
            prefix = kw['prefix']
            del kw['prefix']
        if self.log_timestamps:
            ts = "{%s}" % (str(datetime.datetime.now())[:-7])
            if prefix == "":
                prefix = ts
            else:
                prefix = ts + ": " + prefix
        if prefix != "":
            msg = "%s: %s" % (prefix, msg)
        if 'loglevel' in kw:
            if kw['loglevel'] > self.log_level:
                return
            del kw['loglevel']
        try:
            if len(args): msg = msg % args
            if len(kw): msg = msg % kw
        except TypeError:
            pass
        try:
            print(msg,file=self.log_file_obj)
        except UnicodeEncodeError:
            msg = msg.encode('ascii', 'replace').decode('ascii')
            print(msg, file=self.log_file_obj)
        self.log_file_obj.flush()

logger_obj = Logger()
dump    = acdump    = functools.partial(logger_obj.log, prefix='stracker[DUMP ]', loglevel=LOG_LEVEL_DUMP)
debug   = acdebug   = functools.partial(logger_obj.log, prefix='stracker[DEBUG]', loglevel=LOG_LEVEL_DEBUG)
info    = acinfo    = functools.partial(logger_obj.log, prefix='stracker[INFO ]', loglevel=LOG_LEVEL_INFO)
warning = acwarning = functools.partial(logger_obj.log, prefix='stracker[WARN ]', loglevel=LOG_LEVEL_INFO)
error   = acerror   = functools.partial(logger_obj.log, prefix='stracker[ERROR]', loglevel=LOG_LEVEL_INFO)
log     =             functools.partial(logger_obj.log, loglevel=LOG_LEVEL_INFO)


def open_log_file():
    from stracker_lib.config import config
    if config.STRACKER_CONFIG.append_log_file:
        log_file_mode = "a"
    else:
        log_file_mode = "w"
    log_file_obj = open(config.STRACKER_CONFIG.log_file, log_file_mode, encoding='utf-8')
    if config.STRACKER_CONFIG.append_log_file:
        log_file_obj.write("""\
---------------------------------------------------------------
Restart
---------------------------------------------------------------
""")
    acinfo("Logging to %s", config.STRACKER_CONFIG.log_file)
    if config.STRACKER_CONFIG.tee_to_stdout:
        class Tee:
            def __init__(self,*files):
                self._files = files

            def write(self, *args, **kw):
                for f in self._files:
                    f.write(*args, **kw)

            def flush(self):
                for f in self._files:
                    f.flush()

        log_file_obj = Tee(log_file_obj, sys.stdout)
    logger_obj.log_file_obj = log_file_obj
    logger_obj.log_timestamps = config.STRACKER_CONFIG.log_timestamps