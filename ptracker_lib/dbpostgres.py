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
import re
import traceback
from ptracker_lib.helpers import *
from ptracker_lib.constants import *
from ptracker_lib.dbgeneric import GenericBackend
from ptracker_lib.dbapsw import SqliteBackend # for backup support

try:
    import psycopg2
    postgresqlSupport = True
    acdebug("postgresql module found")
except ImportError:
    acdebug("postgresql module not found - disable postgres support")
    postgresqlSupport = False

if postgresqlSupport:
    # this is only possible, if postgres support (psycopg2) is found

    class MySQLCurWrapper:
        regexp = re.compile(r':([a-zA-Z_0-9]+)')
        def __init__(self, cur):
            self.cur = cur

        def __getattr__(self, a):
            if a == "lastrowid":
                return self.execute("select lastval()").fetchone()[0]
                return self.cur.lastrowid
            elif a == "description":
                return self.cur.description
            return self.__dict__[a]

        def execute(self, stmt, kw={}):
            #acinfo("old statement:" + stmt)
            rest = stmt
            nstmt = ""
            nkw = None
            while 1:
                M = self.regexp.search(rest)
                if M is None:
                    break
                v = M.group(1)
                try:
                    v = int(v)
                    # positional parameters
                    if nkw is None: nkw = []
                    replacement = '%s'
                    nkw.append(kw[v])
                except:
                    # keyword parameters
                    myassert(type(kw) == type({}))
                    if nkw is None:
                        nkw = {}
                    if v in kw:
                        p = kw[v]
                        if type(p) == type(True):
                            # convert booleans to integers, otherwise postgres complains
                            p = int(p)
                        nkw[v] = p
                    else:
                        acwarning("%s is not in supplued keyword arguments :-/", v)
                    replacement = r'%%(%s)s' % v
                nstmt += rest[:M.start()] + replacement
                rest = rest[M.end():]
            nstmt += rest
            if nkw is None:
                nkw = kw
            #acinfo("new statement:" + nstmt)
            try:
                self.cur.execute(nstmt, nkw)
            except:
                acdebug("exception on postgresql sql statement. Statement:\n%s\narguments:\n%s\n", nstmt, nkw)
                raise
            return self

        def fetchone(self):
            return self.cur.fetchone()

        def fetchall(self):
            return self.cur.fetchall()

        def __enter__(self):
            return self.cur.__enter__()

        def __exit__(self, type, value, tb):
            return self.cur.__exit__(type, value, tb)

    class MySQLConWrapper:
        def __init__(self, db):
            self.db = db

        def __enter__(self):
            return self.db.__enter__()

        def __exit__(self, type, value, tb):
            return self.db.__exit__(type, value, tb)

        def cursor(self):
            return MySQLCurWrapper(self.db.cursor())

        def commit(self):
            return self.db.commit()

        def rollback(self):
            return self.db.rollback()


    class PostgresqlBackend(GenericBackend):

        def __init__(self, lapHistoryFactory, user, host, password, database, perform_backups, force_version=None):
            db = psycopg2.connect(user=user, password=password, host=host, database=database)
            self.blob = "BYTEA"
            self.primkey = "SERIAL PRIMARY KEY"
            self.nullslast = "NULLS LAST"
            GenericBackend.__init__(self, lapHistoryFactory, MySQLConWrapper(db), perform_backups, force_version=force_version)

        def selectOrderedAggregate(self, non_agg_field, agg_field, agg_field_name, table_name):
            return "SELECT %(non_agg_field)s, array_to_string(array_agg(%(agg_field)s ORDER BY %(agg_field)s), ',') AS %(agg_field_name)s FROM %(table_name)s GROUP BY %(non_agg_field)s" % locals()

        def getVersion(self, cur = None):
            if cur is None:
                with self.db:
                    cur = self.db.cursor()
                    return self.getVersion(cur)
            else:
                try:
                    v = cur.execute("SELECT version FROM Version").fetchone()[0]
                    return v
                except psycopg2.Error:
                    acdebug(traceback.format_exc())
                    cur.execute("ROLLBACK") # the auto-rollback should be ok here; we are at the start of our transaction anyway...
                    cur.execute("BEGIN")
                    cur.execute("CREATE TABLE IF NOT EXISTS Version(vId INTEGER PRIMARY KEY, version INTEGER)")
                    cur.execute("INSERT INTO Version (vId,version) VALUES(0,0)")
                    return 0

        def setVersion(self, cur, version):
            cur.execute("UPDATE Version SET version=:version", locals())

        def isOnline(self):
            return True

        def backup(self, v1, v2):
            backup_name = "./postgres_backup.db3.bak_%d_%d" % (v1, v2)
            try:
                if not os.path.exists(backup_name):
                    acinfo("Creating backup in file %s. This can last a while ...", backup_name)
                    backup_db = SqliteBackend(self.lapHistoryFactory, backup_name, perform_backups=False, force_version=v1)
                    backup_db.populate(self)
                    backup_db.db.close()
                    acinfo("Backup created.")
                else:
                    acinfo("Backup file %s already exists. Skipping backup.", backup_name)
            except (KeyboardInterrupt, SystemExit):
                raise
            except:
                acerror("Error while performing database backup to %s.", backup_name)
                acerror(traceback.format_exc())

        def tables(self, cur = None):
            if cur is None:
                with self.db:
                    cur = self.db.cursor()
                    return self.tables(cur=cur)
            else:
                cur.execute("""SELECT table_name
                                FROM information_schema.tables
                                WHERE table_schema='public'
                                AND table_type='BASE TABLE'""")
                res = list(map(lambda x: x[0], cur.fetchall()))
                res.remove('version')
                return res

        def deferr_foreign_key_constraints(self, cur):
            cur.execute("SET CONSTRAINTS ALL DEFERRED")

        def postPopulate(self, cur):
            cur.execute(r"""
                SELECT 'SELECT SETVAL(' ||
                       quote_literal(quote_ident(PGT.schemaname) || '.' || quote_ident(S.relname)) ||
                       ', GREATEST(COALESCE(MAX(' ||quote_ident(C.attname)|| '), 1),1) ) FROM ' ||
                       quote_ident(PGT.schemaname)|| '.'||quote_ident(T.relname)
                FROM pg_class AS S,
                     pg_depend AS D,
                     pg_class AS T,
                     pg_attribute AS C,
                     pg_tables AS PGT
                WHERE S.relkind = 'S'
                    AND S.oid = D.objid
                    AND D.refobjid = T.oid
                    AND D.refobjid = C.attrelid
                    AND D.refobjsubid = C.attnum
                    AND T.relname = PGT.tablename
                ORDER BY S.relname
            """)
            stmts = cur.fetchall()
            for s in stmts:
                stmt = s[0]
                cur.execute(stmt)
                acdebug("fixed serial: %s -> %d", stmt, cur.fetchone()[0])

        def postCompress(self, cur):
            pass


if __name__ == "__main__":
    # basic db testing (postgres and sqlite)

    def dbtest(backend, avoidDeleteAll = False):
        class DummyLapHistory:
            pass
        dlh = DummyLapHistory()
        dlh.sectorTimes = []
        dlh.lapTime = 39000
        dlh.sampleTimes = list(range(0,39001,1000))
        n = len(dlh.sampleTimes)
        dlh.normSplinePositions = list(map(lambda x,n=n: x/n, range(n)))
        dlh.velocities = [[0.,0.,0.]]*n
        dlh.worldPositions = [[0.,0.,0.]]*n
        dlh.sectorsAreSoftSplits = False
        backend.newSession(trackname='track1', carnames=('car1', 'car2'), sessionType='race', multiplayer=False,
                       numberOfLaps=7, duration=0, server='server1', sessionState={})
        backend.registerLap(trackChecksum='ts1', carChecksum='cs1', acVersion='none',
                        steamGuid='myguid', playerName='.Pfalz.Ulrika Eleonora den ÃƒÆ’Ã‚Â¤ldre', playerIsAI=0,
                        lapHistory=dlh, tyre='tyre1', lapCount=0, sessionTime=0, fuelRatio=0.4, valid=True, carname='car1', staticAssists={}, dynamicAssists={},
                        maxSpeed = 100.0, timeInPitLane = 1, timeInPit = 2, teamName = None, escKeyPressed=False,
                        gripLevel = 0.5, collisionsCar=1, collisionsEnv=2, cuts=3)
        print("inserted lap")
        dlh.lapTime = 38000
        backend.registerLap(trackChecksum='ts1', carChecksum='cs1', acVersion='none',
                        steamGuid='myguid', playerName='me', playerIsAI=0,
                        lapHistory=dlh, tyre='tyre1', lapCount=1, sessionTime=0, fuelRatio=0.4, valid=True, carname='car1', staticAssists={}, dynamicAssists={},
                        maxSpeed = 100.0, timeInPitLane = None, timeInPit = None, teamName = None, escKeyPressed=False,
                        gripLevel = 0.5, collisionsCar=1, collisionsEnv=2, cuts=3)
        dlh.lapTime = 40000
        backend.registerLap(trackChecksum='ts1', carChecksum='cs1', acVersion='none',
                        steamGuid='myguid', playerName='me', playerIsAI=0,
                        lapHistory=dlh, tyre='tyre1', lapCount=2, sessionTime=0, fuelRatio=0.4, valid=True, carname='car1', staticAssists={}, dynamicAssists={},
                        maxSpeed = 100.0, timeInPitLane = 1, timeInPit = 2, teamName = "abc", escKeyPressed=False,
                        gripLevel = 0.5, collisionsCar=1, collisionsEnv=2, cuts=3)
        dlh.lapTime = 38500
        backend.registerLap(trackChecksum='ts1', carChecksum='cs1', acVersion='none',
                        steamGuid='myguid', playerName='me', playerIsAI=0,
                        lapHistory=dlh, tyre='tyre1', lapCount=3, sessionTime=0, fuelRatio=0.4, valid=True, carname='car1', staticAssists={}, dynamicAssists={},
                        maxSpeed = 100.0, timeInPitLane = 1, timeInPit = 2, teamName = "abc", escKeyPressed=False,
                        gripLevel = 0.5, collisionsCar=1, collisionsEnv=2, cuts=3)
        backend.finishSession(positions=[{'steamGuid':'myguid', 'playerName':'me','playerIsAI':0, 'raceFinished':1, 'finishTime':None}])
        backend.setupDepositSave('myguid', 'car1', 'track1', 'myset', 0, b"")
        bestLap = backend.getBestLap(trackname='track1', carname='car1', assertValidSectors=0, playerGuid='myguid')
        myassert (bestLap.lapTime == 38000)
        lapStats = backend.lapStats(mode = "top", limit=[0,30], track="track1", artint=0, cars=['car1'], ego_guid='myguid', valid=[0,1,2], minSessionStartTime=0)
        print(lapStats)
        myassert (len(lapStats['laps']) == 1)
        myassert (lapStats['laps'][0]['lapTime'] == 38000)
        backend.lapStats(mode = "top", limit=[None,30], track="track1", artint=0, cars=['car1'], ego_guid='myguid', valid=[0,1,2], minSessionStartTime=0)
        myassert (len(lapStats['laps']) == 1)
        myassert (lapStats['laps'][0]['lapTime'] == 38000)
        sesStats = backend.sessionStats(limit=[0,30], tracks=["track1"], sessionTypes=['race'], ego_guid='myguid', minSessionStartTime=0, minNumPlayers=0, multiplayer=[0,1])
        print ("sesStats1", sesStats)
        sesStats2 = backend.sessionStats(limit=[3,30], tracks=["track1"], sessionTypes=['race'], ego_guid='myguid', minSessionStartTime=0, minNumPlayers=0, multiplayer=[0,1])
        print("sesStats2", sesStats2)
        # check the compression functions
        backend.compressDB(COMPRESS_NULL_SLOW_BINARY_BLOBS)
        backend.compressDB(COMPRESS_NULL_ALL_BINARY_BLOBS_EXCEPT_GUID, steamGuid="myguid")
        backend.compressDB(COMPRESS_NULL_ALL_BINARY_BLOBS)
        if not avoidDeleteAll:
            backend.compressDB(COMPRESS_DELETE_ALL)


    import sys, os, glob
    sys.path.append("..")
    sys.path.append("../../system")
    class FromLapHistory:
        def __init__(self, **kw):
            self.__dict__.update(kw)
        def __str__(self):
            res = ""
            for k in self.__dict__:
                res += "%s = %s\n" % (k, self.__dict__[k])
            return res
    psql_backend = PostgresqlBackend(FromLapHistory, "postgres", "raspberrypi", "postgres", "stracker_test", True)
    # make sure everything is clean...
    with psql_backend.db:
        cur = psql_backend.db.cursor()
        cur.execute("DROP SCHEMA public cascade")
        cur.execute("CREATE SCHEMA public")
    # recreate the backend, so we are in initial state
    psql_backend = PostgresqlBackend(FromLapHistory, "postgres", "raspberrypi", "postgres", "stracker_test", True)
    dbtest(psql_backend)

    # same with sqlite backend
    sqlite_backend = SqliteBackend(FromLapHistory, ":memory:", False)
    dbtest(sqlite_backend)
    dbtest(sqlite_backend, True) # make sure we have data in the database...

    # check migration from sqlite to postgres
    with psql_backend.db:
        cur = psql_backend.db.cursor()
        cur.execute("DROP SCHEMA public cascade")
        cur.execute("CREATE SCHEMA public")
    psql_backend = PostgresqlBackend(FromLapHistory, "postgres", "raspberrypi", "postgres", "stracker_test", True)
    psql_backend.populate(sqlite_backend)

    # check migration from postgres to sqlite
    sqlite_backend = SqliteBackend(FromLapHistory, ":memory:", False)
    sqlite_backend.populate(psql_backend)
    # check that an error is raised, if the target database is not empty
    try:
        error_found = False
        sqlite_backend.populate(psql_backend)
    except:
        error_found = True
    myassert (error_found)

    # check the backup functionality
    psql_backend = PostgresqlBackend(FromLapHistory, "postgres", "raspberrypi", "postgres", "stracker_test", True)
    # make sure everything is clean...
    with psql_backend.db:
        cur = psql_backend.db.cursor()
        cur.execute("DROP SCHEMA public cascade")
        cur.execute("CREATE SCHEMA public")
    for f in glob.glob("*.db3.bak*"):
        os.remove(f)
    sqlite_backend = SqliteBackend(FromLapHistory, "test.db3", True, force_version=1)
    sqlite_backend = SqliteBackend(FromLapHistory, "test.db3", True)

    psql_backend = PostgresqlBackend(FromLapHistory, "postgres", "raspberrypi", "postgres", "stracker_test", True, force_version=1)
    psql_backend = PostgresqlBackend(FromLapHistory, "postgres", "raspberrypi", "postgres", "stracker_test", True)
