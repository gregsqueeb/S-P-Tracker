
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
# some modules needed by other modules. Help py2exe/pyinstaller by importing them
import encodings.idna
import csv

# if we'd do this, we will get a blast of deadlocks caused by cherrypy :/
if 0:
    # change the thread API, so unconstrained acquires fail after a "long"
    # period of time with a deadlock exception
    class DeadlockException(RuntimeError):
        pass
    import _thread
    old_allocate = _thread.allocate_lock
    def new_allocate(waitflag=1, timeout=-1):
        class LockWrapper:
            def __init__(self):
                self.lock = old_allocate()

            def acquire(self, waitflag=1, timeout=-1):
                if waitflag and timeout < 0:
                    unconstrained = True
                    timeout = 20.
                else:
                    unconstrained = False
                res = self.lock.acquire(waitflag, timeout)
                if not res and unconstrained:
                    raise DeadlockException
                return res

            def __getattr__(self, a):
                if a in self.__dict__:
                    return self.__dict__[a]
                return getattr(self.lock, a)

            def __enter__(self, *args, **kw):
                return self.lock.__enter__(*args, **kw)

            def __exit__(self, *args, **kw):
                return self.lock.__exit__(*args, **kw)

        return LockWrapper()

    _thread.allocate_lock = new_allocate

class UnicodeSafeWriter:
    def __init__(self, f):
        self.f = f

    def write(self, u):
        encoding = sys.stdout.encoding or "ascii"
        s = u.encode(encoding, errors="replace").decode(encoding)
        self.f.write(s)

    def __getattr__(self, a):
        return getattr(self.f, a)


sys.stdout = UnicodeSafeWriter(sys.stdout)
sys.stderr = UnicodeSafeWriter(sys.stderr)

import argparse
import os.path
import functools
sys.path.append("..")
sys.path.append("externals")
import ptracker_lib
import stracker_lib
from stracker_lib import config
from stracker_lib import logger
import pygal

def backend_factory():
    if config.config.DATABASE.database_type == config.config.DBTYPE_SQLITE3:
        dbBackend = functools.partial(SqliteBackend,
                                      dbname=config.config.DATABASE.database_file,
                                      perform_backups=config.config.DATABASE.perform_backups)
    else:
        dbBackend = functools.partial(PostgresqlBackend,
                                      user=config.config.DATABASE.postgres_user,
                                      password=config.config.DATABASE.postgres_pwd,
                                      database=config.config.DATABASE.postgres_db,
                                      host=config.config.DATABASE.postgres_host,
                                      perform_backups=config.config.DATABASE.perform_backups)
    return dbBackend

def main(stracker_ini):
    if config.config.STRACKER_CONFIG.lower_priority:
        try:
            try:
                import win32api,win32process,win32con
                pid = win32api.GetCurrentProcessId()
                handle = win32api.OpenProcess(win32con.PROCESS_ALL_ACCESS, True, pid)
                win32process.SetPriorityClass(handle, win32process.BELOW_NORMAL_PRIORITY_CLASS)
            except ImportError:
                import os
                os.nice(5)
            logger.acinfo("Lowered stracker priority.")
        except:
            logger.acwarning("Couldn't lower the stracker priority. Stack trace:")
            logger.acwarning(traceback.format_exc())
    dbBackend = backend_factory()
    ac_monitor.run(dbBackend)

def replace_passwords(x):
    import re
    res,c = re.subn(r'([^=\n]*((PASSWORD)|(_PWD)|(_USER)|(LOGIN))[^=\n]*)=([^\n]*)', r'\1 = XXX', x, flags=re.IGNORECASE)
    return res

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Start stracker (%s), a tracking service for assetto corsa.' % stracker_lib.version)
    parser.add_argument("--stracker_ini", required=True, help='location of stracker ini file, if not existing it will be created.')
    parser.add_argument("--migrate_from_sqlite3", action="store_true", required=False, help='migrate from the sqlite database to the postgresql database. The postgresql db must be empty for that process.')
    parser.add_argument("--migrate_from_postgres", action="store_true", required=False, help='migrate from the postgresql database to the sqlite database. The sqlite db must be empty (non existing) for that process.')
    parser.add_argument("--perform_backup", required=False, help='perform a database backup to the specified file (backup will be stored as sqlite db).')
    args = parser.parse_args()

    migrate = args.migrate_from_sqlite3 or args.migrate_from_postgres
    backup = not args.perform_backup is None
    config.create_config(args.stracker_ini, logger)
    logger.open_log_file()
    logger.logger_obj.setLogLevel(config.config.STRACKER_CONFIG.log_level)
    logger.acinfo("Created log file (log_level=%d).", logger.logger_obj.log_level)
    logger.acinfo("%s loglevel=%d", logger.logger_obj, logger.logger_obj.log_level)
    logger.acinfo("Stracker version %s", stracker_lib.version)
    try:
        stracker_ini_contents = open(args.stracker_ini, "r", encoding='ascii', errors='replace').read()
    except:
        stracker_ini_contents = "<unable to read stracker_ini>"
    try:
        server_cfg_contents = open(config.config.STRACKER_CONFIG.ac_server_cfg_ini, "r", encoding='ascii', errors='replace').read()
    except:
        server_cfg_contents = "<unable to read server_cfg>"
    logger.acinfo(("Dump of stracker configuration (%s):\n" % args.stracker_ini) + replace_passwords(stracker_ini_contents) + "\n")
    logger.acinfo(("Dump of ac server configuration (%s):\n" % config.config.STRACKER_CONFIG.ac_server_cfg_ini) + replace_passwords(server_cfg_contents) + "\n")

    class RedirectStreamToLog:
        def __init__(self, f, log_func):
            self.f = f
            self.log_func = log_func
            self.buffer = ""

        def write(self, s):
            self.f.write(s)
            self.buffer += s
            lines = self.buffer.split("\n")
            for l in lines[:-1]:
                self.log_func(l)
            self.buffer = lines[-1]

        def __getattr__(self, a):
            return getattr(self.f, a)

    sys.stdout = RedirectStreamToLog(sys.stdout, lambda x: logger.log(x, prefix='stracker[STDOUT]', loglevel=logger.LOG_LEVEL_INFO))
    sys.stderr = RedirectStreamToLog(sys.stderr, lambda x: logger.log(x, prefix='stracker[STDERR]', loglevel=logger.LOG_LEVEL_INFO))

    # fix the usage of ac module in ptracker package
    class Acsim:
        def offline(self):
            return False
    class ac:
        pass
    ptracker_lib.acsim = Acsim()
    ptracker_lib.acsim.ac = ac()
    ptracker_lib.acsim.ac.log = logger.log

    from ptracker_lib import helpers
    helpers.restore_loggers(config.config.STRACKER_CONFIG.log_level+2, prefix="stracker")

    # ptracker modules can be imported from here...
    from stracker_lib import ac_monitor
    from ptracker_lib.dbapsw import SqliteBackend
    from ptracker_lib.dbpostgres import PostgresqlBackend
    from stracker_lib.stacktracer import trace_start

    if logger.logger_obj.log_level >= logger.LOG_LEVEL_DEBUG:
        logger.acinfo("Starting tracer with 1 hour interval.")
        trace_start()

    if backup:
        print("Performing the requested backup. Please wait ...")
        dbToBeCopied = backend_factory()(None)
        dbBackup = SqliteBackend(None, dbname=args.perform_backup, perform_backups = False)
        dbBackup.populate(dbToBeCopied)
        print("done")
    elif migrate:
        dbBackendSqlite = SqliteBackend(None,
                                        dbname=config.config.DATABASE.database_file,
                                        perform_backups=config.config.DATABASE.perform_backups)
        dbBackendPostgres = PostgresqlBackend(None,
                                      user=config.config.DATABASE.postgres_user,
                                      password=config.config.DATABASE.postgres_pwd,
                                      database=config.config.DATABASE.postgres_db,
                                      host=config.config.DATABASE.postgres_host,
                                      perform_backups=config.config.DATABASE.perform_backups)
        print("Migrating the database. Please wait ...")
        if args.migrate_from_sqlite3:
            dbBackendPostgres.populate(dbBackendSqlite)
        else:
            dbBackendSqlite.populate(dbBackendPostgres)
    else:
        print("Starting stracker - press ctrl+c for shutdown")
        main(args.stracker_ini)
