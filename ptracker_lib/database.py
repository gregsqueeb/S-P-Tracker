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
from threading import RLock
import functools
import traceback
from ptracker_lib.helpers import *
from ptracker_lib.async_worker import Worker, threadCallDecorator

class CallWrapper:
    MAX_PENDING_RESULTS = 20

    def __init__(self, ld, function):
        self.wrapper = threadCallDecorator(function)
        self.results = {}
        self.tracebacks = {}
        self.ld = ld
        self.ld.wrappers.append(self)
        self.callCnt = 0

    def done(self, res, resultID, add_callback):
        with self.ld.lock:
            if not res is None:
                self.results[resultID] = res
        if not add_callback is None:
            try:
                add_callback(functools.partial(self.result, resultID=resultID))
            except:
                acerror("Error while executing callback:")
                acerror(traceback.format_exc())

    def __call__(self, *args, **kw):
        if '__sync' in kw:
            my_async = not kw['__sync']
            del kw['__sync']
        else:
            my_async = self.ld.my_async
        if '__db_callback' in kw:
            add_callback = kw['__db_callback']
            del kw['__db_callback']
        else:
            add_callback = None
        with self.ld.lock:
            self.ld.checkErrors()
            resultID = self.callCnt
            self.callCnt += 1
        self.tracebacks[resultID] = traceback.extract_stack()
        if my_async:
            self.ld.worker.apply_async(self.wrapper, args, kw, callback=functools.partial(self.done, resultID=resultID, add_callback=add_callback))
        else:
            res = self.ld.worker.apply(self.wrapper, args, kw)
            self.done(res, resultID, add_callback)
        return functools.partial(self.result, resultID=resultID)

    def checkErrors(self):
        with self.ld.lock:
            for r in list(self.results.keys()):
                res = self.results[r]
                if not res is None and not res[0] is None:
                    del self.results[r]
                    ctb = self.tracebacks[r]
                    del self.tracebacks[r]
                    et,ev,etb = res[0]
                    acerror("Error found in database thread: %s", str(ev))
                    acerror("".join(traceback.format_exception(et, ev, etb)))
                    acerror("This function was called from:")
                    acerror("".join(traceback.format_list(ctb)))
                    raise ev.with_traceback(etb)
            if len(self.results) > CallWrapper.MAX_PENDING_RESULTS:
                ids = sorted(self.results.keys())
                ids = ids[:(len(self.results)-CallWrapper.MAX_PENDING_RESULTS)]
                for i in ids:
                    del self.results[i]
            if len(self.tracebacks) > CallWrapper.MAX_PENDING_RESULTS:
                ids = sorted(self.tracebacks.keys())
                ids = ids[:(len(self.results)-CallWrapper.MAX_PENDING_RESULTS)]
                for i in ids:
                    del self.tracebacks[i]

    def result(self, resultID):
        with self.ld.lock:
            self.checkErrors()
            if not resultID in self.results:
                return None
            if resultID in self.tracebacks:
                del self.tracebacks[resultID]
            res = self.results[resultID]
            del self.results[resultID]
            if not res is None:
                return res[1]
            return res

class LapDatabase:

    DB_MODE_NORMAL = 0
    DB_MODE_READONLY = 1
    DB_MODE_MEMORY = 2

    def __init__(self, lapHistoryFactory, dbMode, backendFactory):
        self.lock = RLock()
        self.my_async = True
        self.worker = Worker(self.my_async)
        self.dbMode = dbMode
        self.wrappers = []
        if self.dbMode == self.DB_MODE_READONLY:
            regLap = lambda *args, **kw: None
        else:
            regLap = lambda *args, self=self, **kw: self.db().registerLap(*args, **kw)
        self.createDB =              CallWrapper(self, backendFactory)
        # create db access functions
        self.registerLap =           CallWrapper(self, regLap)
        self.getBestSectorTimes =    CallWrapper(self, lambda *args, self=self, **kw: self.db().getBestSectorTimes(*args, **kw))
        self.getBestLap =            CallWrapper(self, lambda *args, self=self, **kw: self.db().getBestLap(*args, **kw))
        self.getBestLapWithSectors = CallWrapper(self, lambda *args, self=self, **kw: self.db().getBestLap(*args, **kw))
        self.finishSession =         CallWrapper(self, lambda *args, self=self, **kw: self.db().finishSession(*args, **kw))
        self.newSession =            CallWrapper(self, lambda *args, self=self, **kw: self.db().newSession(*args, **kw))
        self.lapStats =              CallWrapper(self, lambda *args, self=self, **kw: self.db().lapStats(*args, **kw))
        self.sessionStats =          CallWrapper(self, lambda *args, self=self, **kw: self.db().sessionStats(*args, **kw))
        self.alltracks =             CallWrapper(self, lambda *args, self=self, **kw: self.db().alltracks(*args, **kw))
        self.allcars =               CallWrapper(self, lambda *args, self=self, **kw: self.db().allcars(*args, **kw))
        self.allservers =            CallWrapper(self, lambda *args, self=self, **kw: self.db().allservers(*args, **kw))
        self.auth =                  CallWrapper(self, lambda *args, self=self, **kw: self.db().auth(*args, **kw))
        self.currentCombo =          CallWrapper(self, lambda *args, self=self, **kw: self.db().currentCombo(*args, **kw))
        self.lapDetails =            CallWrapper(self, lambda *args, self=self, **kw: self.db().lapDetails(*args, **kw))
        self.setOnline =             CallWrapper(self, lambda *args, self=self, **kw: self.db().setOnline(*args, **kw))
        self.getSBandPB =            CallWrapper(self, lambda *args, self=self, **kw: self.db().getSBandPB(*args, **kw))
        self.compressDB =            CallWrapper(self, lambda *args, self=self, **kw: self.db().compressDB(*args, **kw))
        self.sessionDetails =        CallWrapper(self, lambda *args, self=self, **kw: self.db().sessionDetails(*args, **kw))
        self.playerInSessionDetails =CallWrapper(self, lambda *args, self=self, **kw: self.db().playerInSessionDetails(*args, **kw))
        self.getPlayers =            CallWrapper(self, lambda *args, self=self, **kw: self.db().getPlayers(*args, **kw))
        self.playerDetails =         CallWrapper(self, lambda *args, self=self, **kw: self.db().playerDetails(*args, **kw))
        self.modifyBlacklistEntry =  CallWrapper(self, lambda *args, self=self, **kw: self.db().modifyBlacklistEntry(*args, **kw))
        self.modifyGroup =           CallWrapper(self, lambda *args, self=self, **kw: self.db().modifyGroup(*args, **kw))
        self.setupDepositGet =       CallWrapper(self, lambda *args, self=self, **kw: self.db().setupDepositGet(*args, **kw))
        self.setupDepositSave =      CallWrapper(self, lambda *args, self=self, **kw: self.db().setupDepositSave(*args, **kw))
        self.setupDepositRemove =    CallWrapper(self, lambda *args, self=self, **kw: self.db().setupDepositRemove(*args, **kw))
        self.csGetSeasons =          CallWrapper(self, lambda *args, self=self, **kw: self.db().csGetSeasons(*args, **kw))
        self.csModify =              CallWrapper(self, lambda *args, self=self, **kw: self.db().csModify(*args, **kw))
        self.playerInSessionPaCModify = CallWrapper(self, lambda *args, self=self, **kw: self.db().playerInSessionPaCModify(*args, **kw))
        self.modifyLap =             CallWrapper(self, lambda *args, self=self, **kw: self.db().modifyLap(*args, **kw))
        self.modifyRequiredChecksums = CallWrapper(self, lambda *args, self=self, **kw: self.db().modifyRequiredChecksums(*args, **kw))
        self.getRequiredChecksums = CallWrapper(self, lambda *args, self=self, **kw: self.db().getRequiredChecksums(*args, **kw))
        self.reconnect            = CallWrapper(self, lambda *args, self=self, **kw: self.db().reconnect(*args, **kw))
        self.csSetTeamName        = CallWrapper(self, lambda *args, self=self, **kw: self.db().csSetTeamName(*args, **kw))
        self.statistics           = CallWrapper(self, lambda *args, self=self, **kw: self.db().statistics(*args, **kw))
        self.trackAndCarDetails   = CallWrapper(self, lambda *args, self=self, **kw: self.db().trackAndCarDetails(*args, **kw))
        self.trackMap             = CallWrapper(self, lambda *args, self=self, **kw: self.db().trackMap(*args, **kw))
        self.carBadge             = CallWrapper(self, lambda *args, self=self, **kw: self.db().carBadge(*args, **kw))
        self.comparisonInfo       = CallWrapper(self, lambda *args, self=self, **kw: self.db().comparisonInfo(*args, **kw))
        self.queryFuelConsumption = CallWrapper(self, lambda *args, self=self, **kw: self.db().queryFuelConsumption(*args, **kw))
        self.allgroups            = CallWrapper(self, lambda *args, self=self, **kw: self.db().allgroups(*args, **kw))
        self.recordChat           = CallWrapper(self, lambda *args, self=self, **kw: self.db().recordChat(*args, **kw))
        self.filterChat           = CallWrapper(self, lambda *args, self=self, **kw: self.db().filterChat(*args, **kw))
        self.messagesDisabled     = CallWrapper(self, lambda *args, self=self, **kw: self.db().messagesDisabled(*args, **kw))
        self.anonymize            = CallWrapper(self, lambda *args, self=self, **kw: self.db().anonymize(*args, **kw))
        self.getPtsResponse       = CallWrapper(self, lambda *args, self=self, **kw: self.db().getPtsResponse(*args, **kw))
        self.queryMR              = CallWrapper(self, lambda *args, self=self, **kw: self.db().queryMR(*args, **kw))
        self.isOnline = lambda self=self: self.db().isOnline()
        # create the database
        self._db = None
        self.dbRef = self.createDB(lapHistoryFactory)

    def db(self, maxTries = None):
        while self._db is None and (maxTries is None or maxTries > 0):
            self._db = self.dbRef()
            if not maxTries is None:
                maxTries -= 1
            if (maxTries is None or maxTries > 0) and self._db is None:
                time.sleep(0.1)
        return self._db

    def dbReady(self):
        return not self.db(maxTries = 1) is None

    def shutdown(self):
        self.worker.shutdown()

    def checkErrors(self):
        for w in self.wrappers:
            w.checkErrors()

class ProxyCallAll:
    def __init__(self, funcs):
        self.funcs = funcs

    def __call__(self, *args, **kw):
        resultRefs = []
        for f in self.funcs:
            acdebug("call %s(*%s,**%s)", str(f), str(args), str(kw))
            resultRefs.append(f(*args, **kw))
        return functools.partial(self.results, resultRefs=resultRefs)

    def results(self, resultRefs):
        for ref in resultRefs:
            r = ref()
            if not r is None:
                return r

class LapDatabaseProxy:
    functions=["registerLap", "getBestSectorTimes", "getBestLap", "getBestLapWithSectors", "finishSession", "newSession", "lapStats", "sessionStats", "shutdown", "isOnline"]

    def __init__(self, dbs):
        self.dbs = dbs
        for f in LapDatabaseProxy.functions:
            p = ProxyCallAll(list(map(lambda x: getattr(x, f), self.dbs)))
            setattr(self, f, p)

if __name__ == "__main__":
    # stress test for database functions
    from ptracker_lib import helpers
    #helpers.restore_loggers(5)
    from threading import Thread
    from dbapsw import SqliteBackend
    #from dbsqlite import SqliteBackend
    import random
    import os

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

    class Tester:
        def __init__(self, database):
            self.thread = Thread(target=self.run)
            self.database = database
            self.functions = [
                functools.partial(self.database.newSession,
                                  trackname='track1', carnames=['car1'], sessionType='race', multiplayer=False,
                                  numberOfLaps=7, duration=0, server='server1', sessionState={}),
                functools.partial(self.database.registerLap,
                                  trackChecksum='ts1', carChecksum='cs1', acVersion='none',
                                  steamGuid='myguid', playerName='me', playerIsAI=0,
                                  lapHistory=dlh, tyre='tyre1', lapCount=0, sessionTime=0, fuelRatio=0.4, valid=True, carname='car1', staticAssists={}, dynamicAssists={},
                                  maxSpeed = 100.0, teamName = None,
                                  timeInPitLane = None, timeInPit = None, escKeyPressed = None, gripLevel=None, collisionsCar=0, collisionsEnv=1, cuts=2),
                functools.partial(self.database.getBestLap,
                                  __sync=True, trackname='track1', carname='car1', assertValidSectors=0, playerGuid='myguid'),
                functools.partial(self.database.lapStats,
                                  __sync=True, mode = "top", limit=[0,30], track="track1", artint=0, cars=['car1'], ego_guid='myguid', valid=[0,1,2], minSessionStartTime=0),
                functools.partial(self.database.sessionStats,
                                  __sync=True, limit=[0,30], tracks=["track1"], sessionTypes=['race'], ego_guid='myguid', minSessionStartTime=0, minNumPlayers=0, multiplayer=[0,1]),
                functools.partial(self.database.lapDetails,
                                  __sync=True, lapid=1),
                functools.partial(self.database.checkErrors),
                functools.partial(self.database.setOnline,
                                  __sync=True, server_name="test", guids_online=['myguid']),
                functools.partial(self.database.getSBandPB,
                                  __sync=True, trackname = "track1", carname = 'car1', playerGuid = 'myguid'),
            ]
            self.thread.start()

        def run(self):
            print ("started")
            self.functions[3]()
            self.functions[3]()
            self.functions[0]()
            for i in range(1000):
                f = self.functions[random.randint(0, len(self.functions)-1)]
                if not f.keywords is None and "__sync" in f.keywords:
                    ref = f()
                    ref()
                else:
                    f()
            print ("finished")
    try:
        os.remove("atest_database.db3")
    except OSError:
        pass
    dbBackend = functools.partial(SqliteBackend, dbname="test_database.db3", perform_backups=False)
    database = LapDatabase(lambda *args,**kw: None, LapDatabase.DB_MODE_NORMAL, dbBackend)
    testers = []
    nthreads = 10
    for i in range(nthreads):
        testers.append(Tester(database))
    for i in range(nthreads):
        testers[i].thread.join()



