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

################################################################################
# Never Eat Yellow Snow APPS - ptracker
#
# This file is part of the ptracker project. See ptracker.py for details.
################################################################################
import os.path
import shutil
import apsw
import time
#apsw.config(apsw.SQLITE_CONFIG_SERIALIZED)
import traceback
import threading
from ptracker_lib.helpers import *
from ptracker_lib.dbgeneric import GenericBackend

#stmt_log = open("apsw_log.sql", "w")

class CursorWrapper:
    def __init__(self, cur, db):
        self.db = db
        self.reset(cur)
        self._description = []

    def reset(self, cur):
        self.cur = cur
        #self.cur.setexectrace(self.exectrace)

    #def exectrace(self, cursor, sql, bindings):
    #    try:
    #        self._description = []
    #        self._description = cursor.getdescription()
    #        acdebug("description of query: %s", self._description)
    #        return True
    #    except:
    #        acdebug("exectrace got an error: %s", traceback.format_exc())
    #        return True

    def __getattr__(self, a):
        if a == "lastrowid":
            return self.cur.getconnection().last_insert_rowid()
        elif a == "description":
            try:
                #desc = self._description
                desc = self.cur.getdescription()
                desc = [(x[0].lower(), x[1]) for x in desc]
                return desc
            except apsw.ExecutionCompleteError:
                acdebug("error while getting description:")
                acdebug(traceback.format_exc())
                return []
        return self.__dict__[a]

    def execute(self, stmt, kw={}):
        if not self.db.inTransaction:
            acwarning("Execute but not in transaction?")
            acwarning("\n".join(traceback.format_stack()))
        tStart = time.time()
        while 1:
            try:
                #t = stmt
                #t = t.replace("\n", " ")
                #for k in sorted(kw.keys(), key=lambda x: len(x), reverse=True):
                #    if ":" + k in t:
                #        v = ("'%s'" % kw[k]) if type(kw[k]) == str else ("%s" % kw[k])
                #        t = t.replace(":" + k, v)
                #stmt_log.write(t+";\n")
                #stmt_log.flush()
                return self.cur.execute(stmt, kw)
            except apsw.LockedError as e:
                if time.time() - tStart > 1.:
                    acwarning("Waiting too long for database to get unlocked")
                    raise e
                time.sleep(0.2)
            except apsw.BusyError as e:
                raise DBBusyError(str(e))

    def fetchone(self):
        return self.cur.fetchone()

    def fetchall(self):
        return self.cur.fetchall()

    def __enter__(self):
        return self.cur.__enter__()

    def __exit__(self, t, v, tb):
        return self.cur.__exit__(t, v, tb)


class ApswConnectionWrapper:

    def __init__(self, apswconn):
        self.db = apswconn
        self.inTransaction = False
        self.cur = None

    def __enter__(self):
        self.inTransaction = True
        c = self.cursor()
        c.execute("BEGIN")

    def __exit__(self, type, value, tb):
        if tb is None:
            c = self.cursor()
            c.execute("COMMIT")
            self.inTransaction = False
        else:
            c = self.cursor()
            c.execute("ROLLBACK")
            self.inTransaction = False

    def commit(self):
        return self.db.commit()

    def rollback(self):
        return self.db.rollback()

    def cursor(self):
        if self.cur is None:
            self.cur = self.db.cursor()
        c = self.cur
        return CursorWrapper(c, self)

    def close(self):
        return self.db.close()

# class serving as a proxy object for our database access
class SqliteBackend(GenericBackend):

    def __init__(self, lapHistoryFactory, dbname, perform_backups, force_version = None):
        self.dbname = dbname
        acinfo("Using database '%s'" % dbname)
        self.blob = "BLOB"
        self.primkey = "INTEGER PRIMARY KEY"
        db = apsw.Connection(dbname)
        db.setbusyhandler(self.busy)
        GenericBackend.__init__(self, lapHistoryFactory, ApswConnectionWrapper(db), perform_backups, force_version=force_version)

    def selectOrderedAggregate(self, non_agg_field, agg_field, agg_field_name, table_name):
        return "SELECT %(non_agg_field)s, GROUP_CONCAT(%(agg_field)s) AS %(agg_field_name)s FROM (SELECT %(non_agg_field)s,%(agg_field)s FROM %(table_name)s ORDER BY %(non_agg_field)s,%(agg_field)s) GROUP BY %(non_agg_field)s" % locals()

    def busy(self, n):
        acdebug("busy handler called (%d)", n)
        time.sleep(0.1)
        return True

    def backup(self, old_version, new_version):
        if os.path.exists(self.dbname):
            backup_name = self.dbname + ".bak_%d_%d" % (old_version, new_version)
            if not os.path.exists(backup_name):
                acinfo("Creating backup to %s", backup_name)
                backup_db = apsw.Connection(backup_name)
                with backup_db.backup("main", self.db.db, "main") as b:
                    while not b.done:
                        b.step(100)
                backup_db.close()
                acinfo("Backup created.")
            else:
                acinfo("Backup file already exists, skipping.")
        else:
            acinfo("Skipping backup of %s", self.dbname)

    def getVersion(self, cur = None):
        if cur is None:
            with self.db:
                cur = self.db.cursor()
                return self.getVersion(cur)
        else:
            # execute a select statement to ensure locking?
            cur.execute("SELECT name FROM sqlite_master WHERE type='table';")
            cur.execute("""
                PRAGMA foreign_keys = ON;
            """)
            r = cur.execute("PRAGMA user_version")
            version = r.fetchone()[0]
        return version

    def setVersion(self, cur, version):
        cur.execute("PRAGMA user_version = %d" % version)

    def isOnline(self):
        return True

    def tables(self, cur = None):
        if cur is None:
            with self.db:
                cur = self.db.cursor()
                return self.tables(cur)
        else:
            cur.execute("SELECT name FROM sqlite_master WHERE type='table';")
            tables = list(map(lambda x: x[0], cur.fetchall()))
            return tables

    def deferr_foreign_key_constraints(self, cur):
        cur.execute("PRAGMA defer_foreign_keys = 1")

    def postPopulate(self, cur):
        pass

    def postCompress(self, cur):
        if cur is None:
            cur = self.db.db.cursor()
            cur.execute("VACUUM")
        else:
            acdebug("discarding vacuum call from within a transaction.")
