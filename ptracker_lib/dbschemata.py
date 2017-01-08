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
import time

from ptracker_lib.helpers import *

class DbSchemata:
    def __init__(self, lapHistoryFactory, db, perform_backups, force_version = None):
        self.lapHistoryFactory = lapHistoryFactory
        self.db = db
        version = self.getVersion()
        self.invalidSplit = 1000*60*60*24
        self.invalidFinishPosition = 1000
        if not force_version is None:
            self.version = force_version
        else:
            self.version = 23
            if version < self.version and perform_backups:
                print("Performing database backup before migration. This might take a while. You'd better not interrupt this process.")
                self.backup(version, self.version)
            if version > self.version:
                acwarning("The database version is potentially incompatible. If you have problems using the app, try to restore your backup or upgrade to a later app version. Continuing anyway.")
        changed = False
        retries = 0
        migrate = False
        while retries < 5:
            try:
                with self.db:
                    version = self.getVersion(self.db.cursor())
                    if version < self.version:
                        migrate = True
                        print("Performing database migration from version %d to %d. You'd better not interrupt this process." % (version,self.version))
                    for vs in range(version, self.version):
                        f = getattr(self, "migrate_%d_%d" % (vs, vs+1))
                        f()
                        changed = True
                        self.postPopulate(self.db.cursor())
                    f = getattr(self, "fixup_%d" % self.version, None)
                    if not f is None:
                        acdebug("calling db fixup_%d", self.version)
                        f()
                    break
            except DBBusyError:
                time.sleep(5)
                retries += 1
        if migrate:
            self.postCompress(None)
            print("Database migration done.")

    def migrate_0_1(self):
        cur = self.db.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS
                Combos(
                    ComboId %(primkey)s,
                    Track TEXT,
                    Car TEXT,
                    TrackID TEXT,
                    CarID TEXT,
                    ACVersion TEXT
                );
        """ % self.__dict__)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS
                Players(
                    PlayerId %(primkey)s,
                    SteamGuid TEXT,
                    Name TEXT,
                    Surname TEXT,
                    Nickname TEXT
                );
        """ % self.__dict__)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS
                Hotlaps(
                    HotlapId %(primkey)s,
                    ComboId INTEGER,
                    PlayerId INTEGER,
                    LapTime INTEGER,
                    SectorTime0 INTEGER,
                    SectorTime1 INTEGER,
                    SectorTime2 INTEGER,
                    SectorTime3 INTEGER,
                    SectorTime4 INTEGER,
                    SectorTime5 INTEGER,
                    SectorTime6 INTEGER,
                    SectorTime7 INTEGER,
                    SectorTime8 INTEGER,
                    SectorTime9 INTEGER,
                    HistorySampleTimes %(blob)s,
                    HistoryWorldPositions %(blob)s,
                    HistoryVelocities %(blob)s,
                    HistoryNormSplinePositions %(blob)s,
                    DateTime TEXT,
                    FOREIGN KEY (ComboId) REFERENCES Combos (ComboId) DEFERRABLE,
                    FOREIGN KEY (PlayerId) REFERENCES Players (PlayerId) DEFERRABLE
                );
        """ % self.__dict__)
        self.setVersion(cur, 1)

    def migrate_1_2(self):
        # add some columns to the hotlap table
        cur = self.db.cursor()
        cur.execute("ALTER TABLE Combos ADD COLUMN TyreCompound TEXT DEFAULT 'unknown'")
        cur.execute("ALTER TABLE Combos ADD COLUMN SessionType TEXT DEFAULT 'unknwon'")
        cur.execute("ALTER TABLE Hotlaps ADD COLUMN NumberOfCars INTEGER DEFAULT -1")
        cur.execute("ALTER TABLE Hotlaps ADD COLUMN LapCount INTEGER DEFAULT -1")
        cur.execute("ALTER TABLE Hotlaps ADD COLUMN FuelPercent REAL DEFAULT -1")
        self.setVersion(cur, 2)

    def migrate_2_3(self):
        # completely new scheme :-/
        cur = self.db.cursor()
        cur.execute("ALTER TABLE Combos RENAME TO Combos_OLD")
        cur.execute("ALTER TABLE Players RENAME TO Players_OLD")
        cur.execute("""
            CREATE TABLE Combos (
                ComboId %(primkey)s,
                Track TEXT,
                Car TEXT,
                UNIQUE(Track, Car)
                );
            """ % self.__dict__)
        # fill the new combo table with the distinct entries of the old combo
        cur.execute("""
            INSERT INTO Combos (Track, Car)
            SELECT DISTINCT Track, Car FROM Combos_OLD;
        """)
        cur.execute("""
            CREATE TABLE Session (
                SessionId %(primkey)s,
                ComboId INTEGER,
                SessionType TEXT,
                Multiplayer INTEGER,
                NumberOfLaps INTEGER,
                Duration INTEGER,
                ServerIpPort TEXT,
                StartTimeDate INTEGER,
                EndTimeDate INTEGER,
                FOREIGN KEY (ComboId)  REFERENCES Combos(ComboId) DEFERRABLE
                );
            """ % self.__dict__)
        cur.execute("""
            CREATE TABLE Players (
                PlayerId %(primkey)s,
                SteamGuid TEXT,
                Name TEXT,
                ArtInt INTEGER DEFAULT 0
                );
            """ % self.__dict__)
        cur.execute("""
            CREATE UNIQUE INDEX PlayersUniqueIndex ON Players(SteamGuid);
        """)
        cur.execute("""
            INSERT INTO Players (PlayerId, SteamGuid, Name)
            SELECT PlayerId, SteamGuid, Name FROM Players_OLD;
        """)
        cur.execute("""
            CREATE TABLE PlayerInSession (
                PlayerInSessionId %(primkey)s,
                SessionId INTEGER,
                PlayerId INTEGER,
                ACVersion TEXT,
                PTVersion TEXT,
                TrackChecksum TEXT,
                CarChecksum TEXT,
                FinishPosition INTEGER DEFAULT %(invalidFinishPosition)d,
                FOREIGN KEY (SessionId) REFERENCES Session(SessionId) DEFERRABLE,
                FOREIGN KEY (PlayerId) REFERENCES Players(PlayerId) DEFERRABLE
            );
        """ % self.__dict__)
        cur.execute("""
            CREATE TABLE TyreCompounds (
                TyreCompoundId %(primkey)s,
                TyreCompound TEXT,
                UNIQUE(TyreCompound)
            );
        """ % self.__dict__)
        cur.execute("""
            INSERT INTO TyreCompounds (TyreCompound)
            SELECT DISTINCT TyreCompound FROM Combos_OLD;
        """)
        cur.execute("""
            CREATE TABLE Lap (
                LapId %(primkey)s,
                PlayerInSessionId INTEGER,
                TyreCompoundId INTEGER,
                LapCount INTEGER,
                SessionTime INTEGER,
                LapTime INTEGER,
                SectorTime0 INTEGER,
                SectorTime1 INTEGER,
                SectorTime2 INTEGER,
                SectorTime3 INTEGER,
                SectorTime4 INTEGER,
                SectorTime5 INTEGER,
                SectorTime6 INTEGER,
                SectorTime7 INTEGER,
                SectorTime8 INTEGER,
                SectorTime9 INTEGER,
                HistoryInfo %(blob)s,
                FuelRatio REAL,
                Valid INTEGER,
                FOREIGN KEY (PlayerInSessionId) REFERENCES PlayerInSession(PlayerInSessionId) DEFERRABLE,
                FOREIGN KEY (TyreCompoundId) REFERENCES TyreCompounds(TyreCompoundId) DEFERRABLE
            );
        """ % self.__dict__)
        # now we have to fill the tables
        # we do so by iterating over the join of the 3 old tables
        cur.execute("""
            SELECT *
            FROM Hotlaps JOIN Combos_OLD ON (Hotlaps.ComboId=Combos_OLD.ComboId)
                         JOIN Players_OLD ON (Hotlaps.PlayerId=Players_OLD.PlayerId)
            """)
        for r in cur.fetchall():
            (HotlapId, OldComboId, PlayerId, LapTime,
                St0, St1, St2, St3, St4, St5, St6, St7, St8, St9,
                HistSampleTimes, HistWorldPositions, HistVel, HistNsp,
                DateTime, NumCars, LapCount, FuelRatio,
                dum1, Track, Car, TrackId, CarId, ACVersion, TyreCompound,
                SessionType,
                dum2, SteamGuid, PlName, PlSurname, PlNickname) = r
            c2 = self.db.cursor()
            # get the (new) combo id
            c2.execute("""
                SELECT ComboId FROM Combos
                WHERE Track=:Track AND Car=:Car
            """, locals())
            ComboId = c2.fetchone()[0]
            # get the (new) tyre id
            c2.execute("""
                SELECT TyreCompoundId FROM TyreCompounds
                WHERE TyreCompound=:TyreCompound
            """, locals())
            TyreCompoundId = c2.fetchone()[0]
            # insert a new session to the db
            Multiplayer = int(St0 < 86400000)
            dt = datetime.datetime.strptime(DateTime,"%Y-%m-%d %H:%M:%S.%f")
            timestamp = datetime2unixtime(dt)
            NumberOfLaps = 0
            Duration = 0
            serverIpPort = ""
            c2.execute("""
                INSERT INTO Session (
                    ComboId,
                    SessionType,
                    Multiplayer,
                    NumberOfLaps,
                    Duration,
                    ServerIpPort,
                    StartTimeDate,
                    EndTimeDate)
                VALUES(
                    :ComboId,
                    :SessionType,
                    :Multiplayer,
                    :NumberOfLaps,
                    :Duration,
                    :serverIpPort,
                    :timestamp,
                    :timestamp);
            """, locals())
            # and get the session id
            SessionId = cur.lastrowid
            myassert(not SessionId is None)
            # insert a new PlayerInSession entry to the db
            PTVersion="1.1"
            c2.execute("""
                INSERT INTO PlayerInSession (SessionId,PlayerId,ACVersion,PTVersion,TrackChecksum,CarChecksum)
                VALUES(:SessionId,:PlayerId,:ACVersion,:PTVersion,:TrackId,:CarId);
            """, locals())
            # and get the PlayerInSessionId
            PlayerInSessionId = cur.lastrowid
            myassert(not PlayerInSessionId is None)
            # insert a new Lap entry
            Valid=1
            SessionTime=-1
            try:
                sampleTimes = pickle.loads(HistSampleTimes)
                worldPositions = pickle.loads(HistWorldPositions)
                velocities = pickle.loads(HistVel)
                normSplinePositions = pickle.loads(HistNsp)
            except pickle.UnpicklingError:
                sampleTimes = pickle.loads(zlib.decompress(HistSampleTimes))
                worldPositions = pickle.loads(zlib.decompress(HistWorldPositions))
                velocities = pickle.loads(zlib.decompress(HistVel))
                normSplinePositions = pickle.loads(zlib.decompress(HistNsp))
            historyInfoCmp = compress(sampleTimes, worldPositions, velocities, normSplinePositions)
            c2.execute("""
                INSERT INTO Lap (PlayerInSessionId,LapCount,SessionTime,LapTime,
                            SectorTime0,SectorTime1,SectorTime2,SectorTime3,SectorTime4,
                            SectorTime5,SectorTime6,SectorTime7,SectorTime8,SectorTime9,
                            HistoryInfo,
                            FuelRatio,
                            TyreCompoundId,
                            Valid)
                VALUES(:PlayerInSessionId,:LapCount,:SessionTime,:LapTime,
                       :St0,:St1,:St2,:St3,:St4,:St5,:St6,:St7,:St8,:St9,
                       :historyInfoCmp,
                       :FuelRatio,:TyreCompoundId,:Valid);
            """,locals())
        cur.execute("DROP TABLE Hotlaps")
        cur.execute("DROP TABLE Combos_OLD")
        cur.execute("DROP TABLE Players_OLD")
        cur.execute("""
        CREATE VIEW
            LapTimes
        AS
            SELECT Lap.LapTime AS LapTime,
                   Lap.SectorTime0 AS SectorTime0,
                   Lap.SectorTime1 AS SectorTime1,
                   Lap.SectorTime2 AS SectorTime2,
                   Lap.SectorTime3 AS SectorTime3,
                   Lap.SectorTime4 AS SectorTime4,
                   Lap.SectorTime5 AS SectorTime5,
                   Lap.SectorTime6 AS SectorTime6,
                   Lap.SectorTime7 AS SectorTime7,
                   Lap.SectorTime8 AS SectorTime8,
                   Lap.SectorTime9 AS SectorTime9,
                   Lap.HistoryInfo AS HistoryInfo,
                   Lap.Valid AS Valid,
                   Players.SteamGuid AS SteamGuid,
                   Players.Name AS Name,
                   Players.ArtInt AS ArtInt,
                   Combos.Track AS Track,
                   Combos.Car AS Car
            FROM Lap JOIN PlayerInSession ON (Lap.PlayerInSessionId=PlayerInSession.PlayerInSessionId)
                     JOIN Session ON (PlayerInSession.SessionId=Session.SessionId)
                     JOIN Combos ON (Session.ComboId=Combos.ComboId)
                     JOIN Players ON (PlayerInSession.PlayerId=Players.PlayerId)
        """)
        self.setVersion(cur, 3)
        acinfo("Migrated from db version 2 to 3.")

    def migrate_3_4(self):
        # Remove combo table and add the track column to session and car column to
        # playerinsession (might be a session running multiple cars, even a player
        # with different cars within the same session)
        cur = self.db.cursor()
        cur.execute("""
            CREATE TABLE Tracks(
                TrackId %(primkey)s,
                Track TEXT,
                UNIQUE(Track)
            )
        """ % self.__dict__)
        cur.execute("""
            CREATE TABLE Cars(
                CarId %(primkey)s,
                Car TEXT,
                UNIQUE(Car)
            )
        """ % self.__dict__)
        cur.execute("ALTER TABLE Session RENAME TO Session_OLD")
        cur.execute("ALTER TABLE PlayerInSession RENAME TO PlayerInSession_OLD")
        cur.execute("ALTER TABLE Lap RENAME TO Lap_OLD")
        cur.execute("DROP VIEW LapTimes")
        cur.execute("INSERT INTO Tracks(Track) SELECT DISTINCT Track FROM Combos")
        cur.execute("INSERT INTO Cars(Car) SELECT DISTINCT Car FROM Combos")
        cur.execute("""
            CREATE TABLE Session(
                SessionId %(primkey)s,
                TrackId INTEGER,
                SessionType TEXT,
                Multiplayer INTEGER,
                NumberOfLaps INTEGER,
                Duration INTEGER,
                ServerIpPort TEXT,
                StartTimeDate INTEGER,
                EndTimeDate INTEGER,
                FOREIGN KEY (TrackId)  REFERENCES Tracks(TrackId) DEFERRABLE
            )
        """ % self.__dict__)
        cur.execute("""
            INSERT INTO Session
            SELECT
                Session_OLD.SessionId,
                Tracks.TrackId,
                Session_OLD.SessionType,
                Session_OLD.Multiplayer,
                Session_OLD.NumberOfLaps,
                Session_OLD.Duration,
                Session_OLD.ServerIpPort,
                Session_OLD.StartTimeDate,
                Session_OLD.EndTimeDate
            FROM Session_OLD
                JOIN Combos ON Session_OLD.ComboId=Combos.ComboId
                JOIN Tracks ON Tracks.Track=Combos.Track

        """)
        cur.execute("""
            CREATE TABLE PlayerInSession (
                PlayerInSessionId %(primkey)s,
                SessionId INTEGER,
                PlayerId INTEGER,
                ACVersion TEXT,
                PTVersion TEXT,
                TrackChecksum TEXT,
                CarChecksum TEXT,
                CarId INTEGER,
                FinishPosition INTEGER DEFAULT %(invalidFinishPosition)d,
                FOREIGN KEY (SessionId) REFERENCES Session(SessionId) DEFERRABLE,
                FOREIGN KEY (PlayerId) REFERENCES Players(PlayerId) DEFERRABLE,
                FOREIGN KEY (CarId) REFERENCES Cars(CarId) DEFERRABLE,
                UNIQUE (SessionId,PlayerId,CarId)
            )
        """ % self.__dict__)
        cur.execute("""
            INSERT INTO PlayerInSession
            SELECT
                PlayerInSession_OLD.PlayerInSessionId,
                PlayerInSession_OLD.SessionId,
                PlayerInSession_OLD.PlayerId,
                PlayerInSession_OLD.ACVersion,
                PlayerInSession_OLD.PTVersion,
                PlayerInSession_OLD.TrackChecksum,
                PlayerInSession_OLD.CarChecksum,
                Cars.CarId,
                PlayerInSession_OLD.FinishPosition
            FROM PlayerInSession_OLD
                JOIN Session_OLD ON PlayerInSession_OLD.SessionId=Session_OLD.SessionId
                JOIN Combos ON Session_OLD.ComboId=Combos.ComboId
                JOIN Cars ON Cars.Car=Combos.Car
        """)
        cur.execute("""
            CREATE TABLE Lap (
                LapId %(primkey)s,
                PlayerInSessionId INTEGER,
                TyreCompoundId INTEGER,
                LapCount INTEGER,
                SessionTime INTEGER,
                LapTime INTEGER,
                SectorTime0 INTEGER,
                SectorTime1 INTEGER,
                SectorTime2 INTEGER,
                SectorTime3 INTEGER,
                SectorTime4 INTEGER,
                SectorTime5 INTEGER,
                SectorTime6 INTEGER,
                SectorTime7 INTEGER,
                SectorTime8 INTEGER,
                SectorTime9 INTEGER,
                HistoryInfo %(blob)s,
                FuelRatio REAL,
                Valid INTEGER,
                FOREIGN KEY (PlayerInSessionId) REFERENCES PlayerInSession(PlayerInSessionId) DEFERRABLE,
                FOREIGN KEY (TyreCompoundId) REFERENCES TyreCompounds(TyreCompoundId) DEFERRABLE
            );
        """ % self.__dict__)
        cur.execute("""
            INSERT INTO Lap
            SELECT
                *
            FROM Lap_OLD
        """)
        cur.execute("DROP TABLE Lap_OLD")
        cur.execute("DROP TABLE PlayerInSession_OLD")
        cur.execute("DROP TABLE Session_OLD")
        cur.execute("DROP TABLE Combos")
        cur.execute("""
        CREATE VIEW
            LapTimes
        AS
            SELECT Lap.LapTime AS LapTime,
                   Lap.SectorTime0 AS SectorTime0,
                   Lap.SectorTime1 AS SectorTime1,
                   Lap.SectorTime2 AS SectorTime2,
                   Lap.SectorTime3 AS SectorTime3,
                   Lap.SectorTime4 AS SectorTime4,
                   Lap.SectorTime5 AS SectorTime5,
                   Lap.SectorTime6 AS SectorTime6,
                   Lap.SectorTime7 AS SectorTime7,
                   Lap.SectorTime8 AS SectorTime8,
                   Lap.SectorTime9 AS SectorTime9,
                   Lap.HistoryInfo AS HistoryInfo,
                   Lap.Valid AS Valid,
                   Players.SteamGuid AS SteamGuid,
                   Players.Name AS Name,
                   Players.ArtInt AS ArtInt,
                   Tracks.Track AS Track,
                   Cars.Car AS Car
            FROM Lap JOIN PlayerInSession ON (Lap.PlayerInSessionId=PlayerInSession.PlayerInSessionId)
                     JOIN Session ON (PlayerInSession.SessionId=Session.SessionId)
                     JOIN Tracks ON (Session.TrackId=Tracks.TrackId)
                     JOIN Cars ON (PlayerInSession.CarId=Cars.CarId)
                     JOIN Players ON (PlayerInSession.PlayerId=Players.PlayerId)
        """)
        cur.execute("""
        CREATE VIEW
            PlayerInSessionView
        AS
            SELECT
                PlayerInSession.PlayerInSessionId AS PlayerInSessionId,
                Players.SteamGuid AS SteamGuid,
                Cars.Car AS Car,
                Session.SessionId AS SessionId
            FROM
                Players
                    JOIN PlayerInSession ON (Players.PlayerId=PlayerInSession.PlayerId)
                    JOIN Cars ON (PlayerInSession.CarId=Cars.CarId)
                    JOIN Session ON (PlayerInSession.SessionId=Session.SessionId)
        """)
        self.setVersion(cur, 4)
        acinfo("Migrated from db version 3 to 4.")

    def migrate_4_5(self):
        cur = self.db.cursor()
        # add a boolean for soft split sectors (previously soft splits
        # have not been saved, so default is 0)
        cur.execute("""
            ALTER TABLE Lap
            ADD COLUMN SectorsAreSoftSplits INTEGER DEFAULT 0
        """)
        # add a boolean whether a player has finished the race or not
        cur.execute("""
            ALTER TABLE PlayerInSession
            ADD COLUMN RaceFinished INTEGER DEFAULT 0
        """)
        # and set according to the LapCount information
        invalidPosition = self.invalidFinishPosition
        cur.execute("""
            UPDATE PlayerInSession SET
                RaceFinished = 1
            WHERE PlayerInSessionId IN
                (SELECT PlayerInSessionView.PlayerInSessionId FROM
                 PlayerInSessionView
                    JOIN Session ON (PlayerInSessionView.SessionId=Session.SessionId)
                    JOIN Lap ON (PlayerInSessionView.PlayerInSessionId=Lap.PlayerInSessionId)
                    JOIN PlayerInSession ON (PlayerInSession.PlayerInSessionId=PlayerInSessionView.PlayerInSessionId)
                 WHERE Lap.LapCount > 0 AND Session.NumberOfLaps=Lap.LapCount AND PlayerInSession.FinishPosition < :invalidPosition)
        """, locals())
        cur.execute("DROP VIEW LapTimes")
        cur.execute("""
        CREATE VIEW
            LapTimes
        AS
            SELECT Lap.LapTime AS LapTime,
                   Lap.SectorTime0 AS SectorTime0,
                   Lap.SectorTime1 AS SectorTime1,
                   Lap.SectorTime2 AS SectorTime2,
                   Lap.SectorTime3 AS SectorTime3,
                   Lap.SectorTime4 AS SectorTime4,
                   Lap.SectorTime5 AS SectorTime5,
                   Lap.SectorTime6 AS SectorTime6,
                   Lap.SectorTime7 AS SectorTime7,
                   Lap.SectorTime8 AS SectorTime8,
                   Lap.SectorTime9 AS SectorTime9,
                   Lap.HistoryInfo AS HistoryInfo,
                   Lap.Valid AS Valid,
                   Players.SteamGuid AS SteamGuid,
                   Players.Name AS Name,
                   Players.ArtInt AS ArtInt,
                   Tracks.Track AS Track,
                   Cars.Car AS Car,
                   Lap.SectorsAreSoftSplits AS SectorsAreSoftSplits
            FROM Lap JOIN PlayerInSession ON (Lap.PlayerInSessionId=PlayerInSession.PlayerInSessionId)
                     JOIN Session ON (PlayerInSession.SessionId=Session.SessionId)
                     JOIN Tracks ON (Session.TrackId=Tracks.TrackId)
                     JOIN Cars ON (PlayerInSession.CarId=Cars.CarId)
                     JOIN Players ON (PlayerInSession.PlayerId=Players.PlayerId)
        """)
        self.setVersion(cur, 5)
        acinfo("Migrated from db version 4 to 5.")

    def migrate_5_6(self):
        cur = self.db.cursor()
        cur.execute("DROP VIEW LapTimes")
        cur.execute("CREATE INDEX LapValidPlayerInSessionId ON Lap(Valid,PlayerInSessionId)")
        cur.execute("""
        CREATE VIEW
            LapTimes
        AS
            SELECT Lap.LapTime AS LapTime,
                   Lap.SectorTime0 AS SectorTime0,
                   Lap.SectorTime1 AS SectorTime1,
                   Lap.SectorTime2 AS SectorTime2,
                   Lap.SectorTime3 AS SectorTime3,
                   Lap.SectorTime4 AS SectorTime4,
                   Lap.SectorTime5 AS SectorTime5,
                   Lap.SectorTime6 AS SectorTime6,
                   Lap.SectorTime7 AS SectorTime7,
                   Lap.SectorTime8 AS SectorTime8,
                   Lap.SectorTime9 AS SectorTime9,
                   Lap.HistoryInfo AS HistoryInfo,
                   Lap.Valid AS Valid,
                   Players.SteamGuid AS SteamGuid,
                   Players.Name AS Name,
                   Players.ArtInt AS ArtInt,
                   Tracks.Track AS Track,
                   Cars.Car AS Car,
                   Lap.SectorsAreSoftSplits AS SectorsAreSoftSplits,
                   Lap.SessionTime AS SessionTime,
                   Session.StartTimeDate AS SessionStartTimeDate,
                   TyreCompounds.TyreCompound AS TyreCompound,
                   Lap.LapId AS LapId
            FROM Lap JOIN PlayerInSession ON (Lap.PlayerInSessionId=PlayerInSession.PlayerInSessionId)
                     JOIN Session ON (PlayerInSession.SessionId=Session.SessionId)
                     JOIN Tracks ON (Session.TrackId=Tracks.TrackId)
                     JOIN Cars ON (PlayerInSession.CarId=Cars.CarId)
                     JOIN Players ON (PlayerInSession.PlayerId=Players.PlayerId)
                     JOIN TyreCompounds ON (Lap.TyreCompoundId=TyreCompounds.TyreCompoundID)
        """)
        cur.execute("CREATE INDEX IdxLapTime ON Lap(LapTime)")
        for i in range(10):
            cur.execute("CREATE INDEX IdxSectorTime%d ON Lap(SectorTime%d)" % (i,i) )
        cur.execute("CREATE INDEX IdxSessioTimeDate ON Session(StartTimeDate)")
        cur.execute("CREATE INDEX IdxLapTimePlayer ON Lap(LapTime,PlayerInSessionId)")
        cur.execute("CREATE INDEX PlayerIdSteamGuid ON Players(PlayerId,SteamGuid)")
        cur.execute("SELECT LapId, HistoryInfo, LapTime FROM Lap WHERE Valid=2")
        lapsToInvalidate = []
        for r in cur.fetchall():
            lapId = r[0]
            sampleTimes, worldPositions, velocities, normSplinePositions = decompress(r[1])
            lapTime = r[2]
            try:
                lh = self.lapHistoryFactory( lapTime=lapTime,
                                             sectorTimes=[None]*10,
                                             sampleTimes=sampleTimes,
                                             worldPositions=worldPositions,
                                             velocities=velocities,
                                             normSplinePositions=normSplinePositions,
                                             a2b=True )
            except AssertionError:
                acinfo("Invalidating lap with lap id %d" % lapId)
                lapsToInvalidate.append(lapId)
        if len(lapsToInvalidate) > 0:
            lti = ",".join(map(str, lapsToInvalidate))
            cur.execute("""
                UPDATE Lap SET
                    Valid = 0
                WHERE LapId IN (%s)
            """ % (lti) )
            acinfo("Invalidating %d opponent laps (plausibility checks failed)" % len(lapsToInvalidate) )
        self.setVersion(cur, 6)
        acinfo("Migrated from db version 5 to 6.")

    def migrate_6_7(self):
        cur = self.db.cursor()
        cur.execute("CREATE INDEX PlayerInSessionPlayerIdCarId ON PlayerInSession(PlayerId,CarId)")
        #cur.execute("CREATE INDEX LapValidPlayerInSessionId ON Lap(Valid,PlayerInSessionId)")
        cur.execute("DROP VIEW LapTimes")
        cur.execute("""
        CREATE VIEW
            LapTimes
        AS
            SELECT Lap.LapTime AS LapTime,
                   Lap.SectorTime0 AS SectorTime0,
                   Lap.SectorTime1 AS SectorTime1,
                   Lap.SectorTime2 AS SectorTime2,
                   Lap.SectorTime3 AS SectorTime3,
                   Lap.SectorTime4 AS SectorTime4,
                   Lap.SectorTime5 AS SectorTime5,
                   Lap.SectorTime6 AS SectorTime6,
                   Lap.SectorTime7 AS SectorTime7,
                   Lap.SectorTime8 AS SectorTime8,
                   Lap.SectorTime9 AS SectorTime9,
                   Lap.HistoryInfo AS HistoryInfo,
                   Lap.Valid AS Valid,
                   Players.SteamGuid AS SteamGuid,
                   Players.Name AS Name,
                   Players.ArtInt AS ArtInt,
                   Tracks.Track AS Track,
                   Cars.Car AS Car,
                   Lap.SectorsAreSoftSplits AS SectorsAreSoftSplits,
                   Lap.SessionTime AS SessionTime,
                   Session.StartTimeDate AS SessionStartTimeDate,
                   TyreCompounds.TyreCompound AS TyreCompound,
                   Lap.LapId AS LapId,
                   PlayerInSession.PlayerId AS PlayerId,
                   Lap.PlayerInSessionId AS PlayerInSessionId,
                   PlayerInSession.CarId AS CarId
            FROM Lap JOIN PlayerInSession ON (Lap.PlayerInSessionId=PlayerInSession.PlayerInSessionId)
                     JOIN Session ON (PlayerInSession.SessionId=Session.SessionId)
                     JOIN Tracks ON (Session.TrackId=Tracks.TrackId)
                     JOIN Cars ON (PlayerInSession.CarId=Cars.CarId)
                     JOIN Players ON (PlayerInSession.PlayerId=Players.PlayerId)
                     JOIN TyreCompounds ON (Lap.TyreCompoundId=TyreCompounds.TyreCompoundID)
        """)
        self.setVersion(cur, 7)
        acinfo("Migrated from db version 6 to 7.")

    def migrate_7_8(self):
        cur = self.db.cursor()

        cur.execute("ALTER TABLE Session ADD COLUMN PenaltiesEnabled INTEGER")
        cur.execute("ALTER TABLE Session ADD COLUMN AllowedTyresOut INTEGER")
        cur.execute("ALTER TABLE Session ADD COLUMN TyreWearFactor REAL")
        cur.execute("ALTER TABLE Session ADD COLUMN FuelRate REAL")
        cur.execute("ALTER TABLE Session ADD COLUMN Damage REAL")

        cur.execute("ALTER TABLE PlayerInSession ADD COLUMN ABS INTEGER")
        cur.execute("ALTER TABLE PlayerInSession ADD COLUMN AutoBlib INTEGER")
        cur.execute("ALTER TABLE PlayerInSession ADD COLUMN AutoBrake INTEGER")
        cur.execute("ALTER TABLE PlayerInSession ADD COLUMN AutoClutch INTEGER")
        cur.execute("ALTER TABLE PlayerInSession ADD COLUMN AutoShift INTEGER")
        cur.execute("ALTER TABLE PlayerInSession ADD COLUMN IdealLine INTEGER")
        cur.execute("ALTER TABLE PlayerInSession ADD COLUMN StabilityControl REAL")
        cur.execute("ALTER TABLE PlayerInSession ADD COLUMN TractionControl INTEGER")
        cur.execute("ALTER TABLE PlayerInSession ADD COLUMN VisualDamage INTEGER")
        cur.execute("ALTER TABLE PlayerInSession ADD COLUMN InputMethod TEXT")
        cur.execute("ALTER TABLE PlayerInSession ADD COLUMN Shifter INTEGER")

        cur.execute("ALTER TABLE Lap ADD COLUMN MaxABS REAL")
        cur.execute("ALTER TABLE Lap ADD COLUMN MaxTC REAL")
        cur.execute("ALTER TABLE Lap ADD COLUMN TemperatureAmbient INTEGER")
        cur.execute("ALTER TABLE Lap ADD COLUMN TemperatureTrack INTEGER")

        self.setVersion(cur, 8)
        acinfo("Migrated from db version 7 to 8.")

    def migrate_8_9(self):
        cur = self.db.cursor()

        cur.execute("ALTER TABLE PlayerInSession ADD COLUMN FinishTime INTEGER")

        cur.execute("DROP VIEW IF EXISTS Example_BestLaps_imola_evoraGtc_p45_Limit_30_Offset_0")
        cur.execute("DROP VIEW IF EXISTS Example_SessionOverview_Type_RaceOrQualify_Multiplayer_MinNumPlayers_4")
        cur.execute("DROP VIEW LapTimes")
        cur.execute("""
        CREATE VIEW
            LapTimes
        AS
            SELECT Lap.LapTime AS LapTime,
                   Lap.SectorTime0 AS SectorTime0,
                   Lap.SectorTime1 AS SectorTime1,
                   Lap.SectorTime2 AS SectorTime2,
                   Lap.SectorTime3 AS SectorTime3,
                   Lap.SectorTime4 AS SectorTime4,
                   Lap.SectorTime5 AS SectorTime5,
                   Lap.SectorTime6 AS SectorTime6,
                   Lap.SectorTime7 AS SectorTime7,
                   Lap.SectorTime8 AS SectorTime8,
                   Lap.SectorTime9 AS SectorTime9,
                   Lap.HistoryInfo AS HistoryInfo,
                   Lap.Valid AS Valid,
                   Players.SteamGuid AS SteamGuid,
                   Players.Name AS Name,
                   Players.ArtInt AS ArtInt,
                   Tracks.Track AS Track,
                   Cars.Car AS Car,
                   Lap.SectorsAreSoftSplits AS SectorsAreSoftSplits,
                   Lap.SessionTime AS SessionTime,
                   Session.StartTimeDate AS SessionStartTimeDate,
                   TyreCompounds.TyreCompound AS TyreCompound,
                   Lap.LapId AS LapId,
                   PlayerInSession.PlayerId AS PlayerId,
                   Lap.PlayerInSessionId AS PlayerInSessionId,
                   PlayerInSession.CarId AS CarId,
                   Session.PenaltiesEnabled AS PenaltiesEnabled,
                   Session.AllowedTyresOut AS AllowedTyresOut,
                   Session.TyreWearFactor AS TyreWearFactor,
                   Session.FuelRate AS FuelRate,
                   Session.Damage AS Damage,
                   PlayerInSession.ABS AS AidABS,
                   PlayerInSession.AutoBlib AS AidAutoBlib,
                   PlayerInSession.AutoBrake AS AidAutoBrake,
                   PlayerInSession.AutoClutch AS AidAutoClutch,
                   PlayerInSession.AutoShift AS AidAutoShift,
                   PlayerInSession.IdealLine AS AidIdealLine,
                   PlayerInSession.StabilityControl AS AidStabilityControl,
                   PlayerInSession.TractionControl AS AidTractionControl,
                   PlayerInSession.VisualDamage AS AidVisualDamage,
                   PlayerInSession.InputMethod AS InputMethod,
                   PlayerInSession.Shifter AS InputShifter,
                   Lap.MaxABS AS LapMaxABS,
                   Lap.MaxTC AS LapMaxTC,
                   Lap.TemperatureAmbient AS TemperatureAmbient,
                   Lap.TemperatureTrack AS TemperatureTrack
            FROM Lap JOIN PlayerInSession ON (Lap.PlayerInSessionId=PlayerInSession.PlayerInSessionId)
                     JOIN Session ON (PlayerInSession.SessionId=Session.SessionId)
                     JOIN Tracks ON (Session.TrackId=Tracks.TrackId)
                     JOIN Cars ON (PlayerInSession.CarId=Cars.CarId)
                     JOIN Players ON (PlayerInSession.PlayerId=Players.PlayerId)
                     JOIN TyreCompounds ON (Lap.TyreCompoundId=TyreCompounds.TyreCompoundID)
        """)
        cur.execute("""
            CREATE VIEW
                Example_BestLaps_imola_evoraGtc_p45_Limit_30_Offset_0
            AS
                WITH BestLapTimeHelper AS (
                SELECT MIN(LapTime) AS LapTime, PlayerInSession.PlayerId AS PlayerId, PlayerInSession.CarId AS CarId
                FROM Lap JOIN PlayerInSession ON (Lap.PlayerInSessionId=PlayerInSession.PlayerInSessionId)
                WHERE
                    Lap.Valid IN (1,2)  AND
                    Lap.PlayerInSessionId IN (SELECT PlayerInSession.PlayerInSessionId
                                                FROM
                                                    PlayerInSession JOIN Session ON (PlayerInSession.SessionId=Session.SessionId)
                                                                    JOIN Players ON (Players.PlayerId=PlayerInSession.PlayerId)
                                                WHERE Session.TrackId IN (SELECT TrackId FROM Tracks WHERE Track='imola') AND
                                                      PlayerInSession.CarId IN (SELECT CarId FROM Cars WHERE Car IN ('lotus_evora_gtc','p4-5_2011'))
                )
                GROUP BY PlayerInSession.PlayerId,PlayerInSession.CarId
            )
            SELECT * FROM (
                    WITH BestLapIds AS (
                              SELECT MAX(LapTimes.LapId) AS LapId FROM
                                   BestLapTimeHelper JOIN LapTimes ON
                                                            (BestLapTimeHelper.LapTime=LapTimes.LapTime AND
                                                             BestLapTimeHelper.PlayerId=LapTimes.PlayerId AND
                                                             BestLapTimeHelper.CarId=LapTimes.CarId)
                                   GROUP BY LapTimes.LapTime,LapTimes.PlayerId,LapTimes.CarId
                                   ORDER BY LapTimes.LapTime
                                   LIMIT 30
                                   OFFSET 0
                                  )
                    SELECT Name, LapTimes.LapTime, Valid, LapTimes.Car
                    FROM BestLapIds JOIN LapTimes ON (BestLapIds.LapId = LapTimes.LapId)
            ) AS tmp
        """)
        cur.execute("""
            CREATE VIEW
                Example_SessionOverview_Type_RaceOrQualify_Multiplayer_MinNumPlayers_4
            AS
                WITH SelectedSessions AS (
                	SELECT * FROM Session
                	WHERE StartTimeDate > 0
                	      AND SessionType IN ('Race', 'Qualify')
                	      AND Multiplayer = 1
               	),
                EgoGUID AS (
                	SELECT SteamGuid FROM Players WHERE Name='DMr Neys'
               	)
            SELECT * FROM (
                WITH PlayersWithPositions AS (
                	SELECT
                	    PlayerInSession.PlayerId AS PlayerId,
                	    SelectedSessions.SessionId AS SessionId,
                	    PlayerInSession.FinishPosition AS FinishPosition,
                	    PlayerInSession.RaceFinished AS RaceFinished,
                	    Players.Name AS Name,
                	    Players.SteamGuid AS SteamGuid
                	FROM SelectedSessions
                	     JOIN PlayerInSession ON (PlayerInSession.SessionId = SelectedSessions.SessionId)
                	     JOIN Players ON (PlayerInSession.PlayerId = Players.PlayerId)
                	)
                SELECT SelectedSessions.SessionId AS SessionId,
            	       SelectedSessions.SessionType,
            	       Pos1.Name AS Pos1,
            	       Pos2.Name AS Pos2,
            	       Pos3.Name AS Pos3,
            	       SelfPos.FinishPosition AS SelfPosition,
            	       NumPlayers.N AS NumPlayers,
            	       SelectedSessions.StartTimeDate AS StartTimeDate,
            	       SelectedSessions.Multiplayer
                FROM SelectedSessions LEFT JOIN
            	       (SELECT Name, SessionId FROM PlayersWithPositions WHERE FinishPosition = 1) AS Pos1 ON (SelectedSessions.SessionId = Pos1.SessionId) LEFT JOIN
            	       (SELECT Name, SessionId FROM PlayersWithPositions WHERE FinishPosition = 2) AS Pos2 ON (SelectedSessions.SessionId = Pos2.SessionId) LEFT JOIN
            	       (SELECT Name, SessionId FROM PlayersWithPositions WHERE FinishPosition = 3) AS Pos3 ON (SelectedSessions.SessionId = Pos3.SessionId) LEFT JOIN
            	       (SELECT FinishPosition, SessionId
            	           FROM PlayersWithPositions
            	           WHERE SteamGuid IN (SELECT * FROM EgoGUID) AND FinishPosition < 1000) AS SelfPos ON (SelectedSessions.SessionId = SelfPos.SessionId) LEFT JOIN
            	       (SELECT COUNT(*) AS N, SessionId
            	           FROM PlayersWithPositions GROUP BY SessionId) AS NumPlayers ON (SelectedSessions.SessionId = NumPlayers.SessionId)
                ) AS Result
            WHERE Result.NumPlayers >= 4
            ORDER BY Result.StartTimeDate DESC
        """)
        self.setVersion(cur, 9)
        acinfo("Migrated from db version 8 to 9.")

    def migrate_9_10(self):
        cur = self.db.cursor()

        # add timestamp column to lap
        a = cur.execute("SELECT * FROM Lap LIMIT 1").fetchone()
        colNames = tuple(map(lambda x: x[0], cur.description))
        if not 'Timestamp' in colNames:
            cur.execute("ALTER TABLE Lap ADD COLUMN Timestamp INTEGER")
        # assign approximate timestamps to the laps
        # if sessionTime is increasing, this can be done by
        #       timestamp = startSessionTime + sessionTime*0.001
        # if sessionTim is decreasing (qualify / practice mode in stracker), it can be approximated by
        #       timestamp = startSessionTime + (sessionTime[firstLap] - sessionTime)*0.001
        cur.execute("SELECT StartTimeDate,SessionTime,SessionId,LapId FROM Lap NATURAL JOIN PlayerInSession NATURAL JOIN Session WHERE Timestamp IS NULL ORDER BY SessionId,LapId")
        lapTimestamps = {}
        lastSessionId = None
        sessionTimes = []
        while 1:
            r = cur.fetchone()
            if r is None:
                r = (None,None,None,None)
            startTimeDate,sessionTime,sessionId,lapId = r
            if sessionId != lastSessionId:
                if len(sessionTimes) > 0:
                    # assign approximate timestamps to the laps
                    if sessionTimes[0][2] > sessionTimes[-1][2] + 5000:
                        order = -1
                    elif sessionTimes[0][2] < sessionTimes[-1][2] - 5000:
                        order = 1
                    else:
                        order = 0
                    acinfo("sessionId %d -> order %d" % (lastSessionId, order))
                    for s in sessionTimes:
                        if order > 0:
                            lapTimestamps[s[0]] = s[1] + int(s[2]*0.001)
                        elif order < 0:
                            lapTimestamps[s[0]] = s[1] + int((sessionTimes[0][2] - s[2])*0.001)
                        else:
                            lapTimestamps[s[0]] = s[1]
                sessionTimes = []
                order = 0
                lastSessionId = sessionId
            if sessionId is None:
                break
            sessionTimes.append( (lapId,startTimeDate,sessionTime) )
        for lapId in lapTimestamps:
            timestamp = lapTimestamps[lapId]
            cur.execute("UPDATE Lap SET Timestamp=:timestamp WHERE LapId=:lapId", locals())

        # add IsOnline column to Players
        a = cur.execute("SELECT * FROM Players LIMIT 1").fetchone()
        colNames = tuple(map(lambda x: x[0], cur.description))
        if not 'IsOnine' in colNames:
            cur.execute("ALTER TABLE Players ADD COLUMN IsOnline TEXT")
        self.setVersion(cur, 10)
        acinfo("Migrated from db version 9 to 10.")

    def migrate_10_11(self):
        cur = self.db.cursor()
        # add aids to Lap table (better support if a player re-joins a session
        cur.execute("ALTER TABLE Lap ADD COLUMN AidABS INTEGER")
        cur.execute("ALTER TABLE Lap ADD COLUMN AidTC INTEGER")
        cur.execute("ALTER TABLE Lap ADD COLUMN AidAutoBlib INTEGER")
        cur.execute("ALTER TABLE Lap ADD COLUMN AidAutoBrake INTEGER")
        cur.execute("ALTER TABLE Lap ADD COLUMN AidAutoClutch INTEGER")
        cur.execute("ALTER TABLE Lap ADD COLUMN AidAutoShift INTEGER")
        cur.execute("ALTER TABLE Lap ADD COLUMN AidIdealLine INTEGER")
        cur.execute("ALTER TABLE Lap ADD COLUMN AidStabilityControl REAL")
        cur.execute("ALTER TABLE Lap ADD COLUMN AidSlipStream REAL")
        cur.execute("ALTER TABLE Lap ADD COLUMN AidTyreBlankets INTEGER")
        cur.execute("""
            UPDATE Lap
            SET
                AidABS = (SELECT ABS FROM PlayerInSession WHERE Lap.PlayerInSessionId = PlayerInSession.PlayerInSessionId)
               ,AidTC = (SELECT TractionControl FROM PlayerInSession WHERE Lap.PlayerInSessionId = PlayerInSession.PlayerInSessionId)
               ,AidAutoBlib = (SELECT AutoBlib FROM PlayerInSession WHERE Lap.PlayerInSessionId = PlayerInSession.PlayerInSessionId)
               ,AidAutoBrake = (SELECT AutoBrake FROM PlayerInSession WHERE Lap.PlayerInSessionId = PlayerInSession.PlayerInSessionId)
               ,AidAutoClutch = (SELECT AutoClutch FROM PlayerInSession WHERE Lap.PlayerInSessionId = PlayerInSession.PlayerInSessionId)
               ,AidAutoShift = (SELECT AutoShift FROM PlayerInSession WHERE Lap.PlayerInSessionId = PlayerInSession.PlayerInSessionId)
               ,AidIdealLine = (SELECT IdealLine FROM PlayerInSession WHERE Lap.PlayerInSessionId = PlayerInSession.PlayerInSessionId)
               ,AidStabilityControl = (SELECT StabilityControl FROM PlayerInSession WHERE Lap.PlayerInSessionId = PlayerInSession.PlayerInSessionId)
        """)
        # we would want to drop the columns from player in session, but we can't,
        # because sqlite doesn't seem to support this... So we set all stuff to NULL here
        cur.execute("""
            UPDATE PlayerInSession
            SET
                ABS = NULL,
                TractionControl = NULL,
                AutoBlib = NULL,
                AutoBrake = NULL,
                AutoClutch = NULL,
                AutoShift = NULL,
                IdealLine = NULL,
                StabilityControl = NULL
        """)
        # add max speed to Lap table
        cur.execute("ALTER TABLE Lap ADD COLUMN MaxSpeed_KMH REAL")

        # adapt LapTimes and Example_BestLaps_imola_evoraGtc_p45_Limit_30_Offset_0 views
        cur.execute("DROP VIEW Example_BestLaps_imola_evoraGtc_p45_Limit_30_Offset_0")
        cur.execute("DROP VIEW LapTimes")

        cur.execute("""
        CREATE VIEW
            LapTimes
        AS
            SELECT Lap.LapTime AS LapTime,
                   Lap.SectorTime0 AS SectorTime0,
                   Lap.SectorTime1 AS SectorTime1,
                   Lap.SectorTime2 AS SectorTime2,
                   Lap.SectorTime3 AS SectorTime3,
                   Lap.SectorTime4 AS SectorTime4,
                   Lap.SectorTime5 AS SectorTime5,
                   Lap.SectorTime6 AS SectorTime6,
                   Lap.SectorTime7 AS SectorTime7,
                   Lap.SectorTime8 AS SectorTime8,
                   Lap.SectorTime9 AS SectorTime9,
                   Lap.HistoryInfo AS HistoryInfo,
                   Lap.Valid AS Valid,
                   Players.SteamGuid AS SteamGuid,
                   Players.Name AS Name,
                   Players.ArtInt AS ArtInt,
                   Tracks.Track AS Track,
                   Cars.Car AS Car,
                   Lap.SectorsAreSoftSplits AS SectorsAreSoftSplits,
                   Lap.Timestamp AS Timestamp,
                   TyreCompounds.TyreCompound AS TyreCompound,
                   Lap.LapId AS LapId,
                   PlayerInSession.PlayerId AS PlayerId,
                   Lap.PlayerInSessionId AS PlayerInSessionId,
                   PlayerInSession.CarId AS CarId,
                   Session.PenaltiesEnabled AS PenaltiesEnabled,
                   Session.AllowedTyresOut AS AllowedTyresOut,
                   Session.TyreWearFactor AS TyreWearFactor,
                   Session.FuelRate AS FuelRate,
                   Session.Damage AS Damage,
                   Lap.AidABS AS AidABS,
                   Lap.AidAutoBlib AS AidAutoBlib,
                   Lap.AidAutoBrake AS AidAutoBrake,
                   Lap.AidAutoClutch AS AidAutoClutch,
                   Lap.AidAutoShift AS AidAutoShift,
                   Lap.AidIdealLine AS AidIdealLine,
                   Lap.AidStabilityControl AS AidStabilityControl,
                   Lap.AidTC AS AidTractionControl,
                   Lap.AidSlipStream AS AidSlipStream,
                   Lap.AidTyreBlankets AS AidTyreBlankets,
                   PlayerInSession.InputMethod AS InputMethod,
                   PlayerInSession.Shifter AS InputShifter,
                   Lap.MaxABS AS LapMaxABS,
                   Lap.MaxTC AS LapMaxTC,
                   Lap.TemperatureAmbient AS TemperatureAmbient,
                   Lap.TemperatureTrack AS TemperatureTrack,
                   Lap.MaxSpeed_KMH AS MaxSpeed_KMH
            FROM Lap JOIN PlayerInSession ON (Lap.PlayerInSessionId=PlayerInSession.PlayerInSessionId)
                     JOIN Session ON (PlayerInSession.SessionId=Session.SessionId)
                     JOIN Tracks ON (Session.TrackId=Tracks.TrackId)
                     JOIN Cars ON (PlayerInSession.CarId=Cars.CarId)
                     JOIN Players ON (PlayerInSession.PlayerId=Players.PlayerId)
                     JOIN TyreCompounds ON (Lap.TyreCompoundId=TyreCompounds.TyreCompoundID)
        """)
        cur.execute("""
            CREATE VIEW
                Example_BestLaps_imola_evoraGtc_p45_Limit_30_Offset_0
            AS
                WITH BestLapTimeHelper AS (
                SELECT MIN(LapTime) AS LapTime, PlayerInSession.PlayerId AS PlayerId, PlayerInSession.CarId AS CarId
                FROM Lap JOIN PlayerInSession ON (Lap.PlayerInSessionId=PlayerInSession.PlayerInSessionId)
                WHERE
                    Lap.Valid IN (1,2)  AND
                    Lap.PlayerInSessionId IN (SELECT PlayerInSession.PlayerInSessionId
                                                FROM
                                                    PlayerInSession JOIN Session ON (PlayerInSession.SessionId=Session.SessionId)
                                                                    JOIN Players ON (Players.PlayerId=PlayerInSession.PlayerId)
                                                WHERE Session.TrackId IN (SELECT TrackId FROM Tracks WHERE Track='imola') AND
                                                      PlayerInSession.CarId IN (SELECT CarId FROM Cars WHERE Car IN ('lotus_evora_gtc','p4-5_2011'))
                )
                GROUP BY PlayerInSession.PlayerId,PlayerInSession.CarId
            )
            SELECT * FROM (
                    WITH BestLapIds AS (
                              SELECT MAX(LapTimes.LapId) AS LapId FROM
                                   BestLapTimeHelper JOIN LapTimes ON
                                                            (BestLapTimeHelper.LapTime=LapTimes.LapTime AND
                                                             BestLapTimeHelper.PlayerId=LapTimes.PlayerId AND
                                                             BestLapTimeHelper.CarId=LapTimes.CarId)
                                   GROUP BY LapTimes.LapTime,LapTimes.PlayerId,LapTimes.CarId
                                   ORDER BY LapTimes.LapTime
                                   LIMIT 30
                                   OFFSET 0
                                  )
                    SELECT Name, LapTimes.LapTime, Valid, LapTimes.Car
                    FROM BestLapIds JOIN LapTimes ON (BestLapIds.LapId = LapTimes.LapId)
            ) AS tmp
        """)
        self.setVersion(cur, 11)
        acinfo("Migrated from db version 10 to 11.")

    def migrate_11_12(self):
        cur = self.db.cursor()
        cur.execute("ALTER TABLE Lap ADD COLUMN TimeInPitLane INTEGER")
        cur.execute("ALTER TABLE Lap ADD COLUMN TimeInPit INTEGER")
        cur.execute("""
            CREATE TABLE PlayerGroups (
                GroupId %(primkey)s,
                GroupName TEXT
            )
        """ % self.__dict__)
        cur.execute("""
            CREATE TABLE GroupEntries (
                GroupEntryId %(primkey)s,
                PlayerId INTEGER,
                GroupId INTEGER,
                FOREIGN KEY (PlayerId) REFERENCES Players(PlayerId) DEFERRABLE,
                FOREIGN KEY (GroupId) REFERENCES PlayerGroups(GroupId) DEFERRABLE
            )
        """ % self.__dict__)
        cur.execute("CREATE UNIQUE INDEX GroupEntriesUniqueIndex ON GroupEntries(PlayerId,GroupId)")
        cur.execute("""
            CREATE TABLE SetupDeposit (
                SetupId %(primkey)s,
                PlayerId INTEGER,
                TrackId INTEGER,
                CarId INTEGER,
                GroupId INTEGER,
                Name TEXT,
                Setup %(blob)s,
                FOREIGN KEY (PlayerId) REFERENCES Players(PlayerId) DEFERRABLE,
                FOREIGN KEY (TrackId) REFERENCES Tracks(TrackId) DEFERRABLE,
                FOREIGN KEY (CarId) REFERENCES Cars(CarId) DEFERRABLE,
                FOREIGN KEY (GroupId) REFERENCES PlayerGroups(GroupId) DEFERRABLE
            )
        """ % self.__dict__)
        cur.execute("CREATE INDEX SetupDepositIndexByCarGroupAndTrack ON SetupDeposit(CarId,GroupId,TrackId)")
        cur.execute("CREATE INDEX SetupDepositIndexByCarPlayerAndTrack ON SetupDeposit(CarId,PlayerId,TrackId)")
        cur.execute("""
            CREATE TABLE Blacklist (
                BlacklistId %(primkey)s,
                PlayerId INTEGER,
                DateAdded INTEGER,
                Duration INTEGER,
                FOREIGN KEY (PlayerId) REFERENCES Players(PlayerId) DEFERRABLE
            )
        """ % self.__dict__)

        # adapt LapTimes and Example_BestLaps_imola_evoraGtc_p45_Limit_30_Offset_0 views
        cur.execute("DROP VIEW Example_BestLaps_imola_evoraGtc_p45_Limit_30_Offset_0")
        cur.execute("DROP VIEW LapTimes")

        cur.execute("""
        CREATE VIEW
            LapTimes
        AS
            SELECT Lap.LapTime AS LapTime,
                   Lap.SectorTime0 AS SectorTime0,
                   Lap.SectorTime1 AS SectorTime1,
                   Lap.SectorTime2 AS SectorTime2,
                   Lap.SectorTime3 AS SectorTime3,
                   Lap.SectorTime4 AS SectorTime4,
                   Lap.SectorTime5 AS SectorTime5,
                   Lap.SectorTime6 AS SectorTime6,
                   Lap.SectorTime7 AS SectorTime7,
                   Lap.SectorTime8 AS SectorTime8,
                   Lap.SectorTime9 AS SectorTime9,
                   Lap.HistoryInfo AS HistoryInfo,
                   Lap.Valid AS Valid,
                   Players.SteamGuid AS SteamGuid,
                   Players.Name AS Name,
                   Players.ArtInt AS ArtInt,
                   Tracks.Track AS Track,
                   Cars.Car AS Car,
                   Lap.SectorsAreSoftSplits AS SectorsAreSoftSplits,
                   Lap.Timestamp AS Timestamp,
                   TyreCompounds.TyreCompound AS TyreCompound,
                   Lap.LapId AS LapId,
                   PlayerInSession.PlayerId AS PlayerId,
                   Lap.PlayerInSessionId AS PlayerInSessionId,
                   PlayerInSession.CarId AS CarId,
                   Session.PenaltiesEnabled AS PenaltiesEnabled,
                   Session.AllowedTyresOut AS AllowedTyresOut,
                   Session.TyreWearFactor AS TyreWearFactor,
                   Session.FuelRate AS FuelRate,
                   Session.Damage AS Damage,
                   Lap.AidABS AS AidABS,
                   Lap.AidAutoBlib AS AidAutoBlib,
                   Lap.AidAutoBrake AS AidAutoBrake,
                   Lap.AidAutoClutch AS AidAutoClutch,
                   Lap.AidAutoShift AS AidAutoShift,
                   Lap.AidIdealLine AS AidIdealLine,
                   Lap.AidStabilityControl AS AidStabilityControl,
                   Lap.AidTC AS AidTractionControl,
                   Lap.AidSlipStream AS AidSlipStream,
                   Lap.AidTyreBlankets AS AidTyreBlankets,
                   PlayerInSession.InputMethod AS InputMethod,
                   PlayerInSession.Shifter AS InputShifter,
                   Lap.MaxABS AS LapMaxABS,
                   Lap.MaxTC AS LapMaxTC,
                   Lap.TemperatureAmbient AS TemperatureAmbient,
                   Lap.TemperatureTrack AS TemperatureTrack,
                   Lap.MaxSpeed_KMH AS MaxSpeed_KMH,
                   Lap.TimeInPitLane AS TimeInPitLane,
                   Lap.TimeInPit AS TimeInPit
            FROM Lap JOIN PlayerInSession ON (Lap.PlayerInSessionId=PlayerInSession.PlayerInSessionId)
                     JOIN Session ON (PlayerInSession.SessionId=Session.SessionId)
                     JOIN Tracks ON (Session.TrackId=Tracks.TrackId)
                     JOIN Cars ON (PlayerInSession.CarId=Cars.CarId)
                     JOIN Players ON (PlayerInSession.PlayerId=Players.PlayerId)
                     JOIN TyreCompounds ON (Lap.TyreCompoundId=TyreCompounds.TyreCompoundID)
        """)
        cur.execute("""
            CREATE VIEW
                Example_BestLaps_imola_evoraGtc_p45_Limit_30_Offset_0
            AS
                WITH BestLapTimeHelper AS (
                SELECT MIN(LapTime) AS LapTime, PlayerInSession.PlayerId AS PlayerId, PlayerInSession.CarId AS CarId
                FROM Lap JOIN PlayerInSession ON (Lap.PlayerInSessionId=PlayerInSession.PlayerInSessionId)
                WHERE
                    Lap.Valid IN (1,2)  AND
                    Lap.PlayerInSessionId IN (SELECT PlayerInSession.PlayerInSessionId
                                                FROM
                                                    PlayerInSession JOIN Session ON (PlayerInSession.SessionId=Session.SessionId)
                                                                    JOIN Players ON (Players.PlayerId=PlayerInSession.PlayerId)
                                                WHERE Session.TrackId IN (SELECT TrackId FROM Tracks WHERE Track='imola') AND
                                                      PlayerInSession.CarId IN (SELECT CarId FROM Cars WHERE Car IN ('lotus_evora_gtc','p4-5_2011'))
                )
                GROUP BY PlayerInSession.PlayerId,PlayerInSession.CarId
            )
            SELECT * FROM (
                    WITH BestLapIds AS (
                              SELECT MAX(LapTimes.LapId) AS LapId FROM
                                   BestLapTimeHelper JOIN LapTimes ON
                                                            (BestLapTimeHelper.LapTime=LapTimes.LapTime AND
                                                             BestLapTimeHelper.PlayerId=LapTimes.PlayerId AND
                                                             BestLapTimeHelper.CarId=LapTimes.CarId)
                                   GROUP BY LapTimes.LapTime,LapTimes.PlayerId,LapTimes.CarId
                                   ORDER BY LapTimes.LapTime
                                   LIMIT 30
                                   OFFSET 0
                                  )
                    SELECT Name, LapTimes.LapTime, Valid, LapTimes.Car
                    FROM BestLapIds JOIN LapTimes ON (BestLapIds.LapId = LapTimes.LapId)
            ) AS tmp
        """)
        self.setVersion(cur, 12)
        acinfo("Migrated from db version 11 to 12.")

    def migrate_12_13(self):
        cur = self.db.cursor()
        cur.execute("""
            CREATE VIEW
            BlacklistedPlayers AS
                WITH BlacklistedPlayersPerId AS (
                    SELECT PlayerId,COUNT(*) AS BanCount,MAX(DateAdded+Duration) AS BannedUntil FROM Blacklist
                    GROUP BY PlayerId
                )
            SELECT Blacklist.BlacklistId AS BlacklistId,
                   Blacklist.PlayerId AS PlayerId,
                   Blacklist.DateAdded AS DateAdded,
                   Blacklist.Duration AS Duration,
                   BlacklistedPlayersPerId.BanCount AS BanCount,
                   BlacklistedPlayersPerId.BannedUntil AS BannedUntil
            FROM BlacklistedPlayersPerId LEFT JOIN Blacklist ON
                (BlacklistedPlayersPerId.PlayerId=Blacklist.PlayerId AND
                 BlacklistedPlayersPerId.BannedUntil=Blacklist.DateAdded+Blacklist.Duration)
        """)
        self.setVersion(cur, 13)
        acinfo("Migrated from db version 12 to 13.")

    def migrate_13_14(self):
        cur = self.db.cursor()
        cur.execute("""
            CREATE TABLE CSSeasons (
                CSId %(primkey)s,
                CSName TEXT
            )
        """ % self.__dict__)
        cur.execute("""
            CREATE TABLE CSEvent (
                EventId %(primkey)s,
                EventName TEXT,
                CSId INTEGER,
                FOREIGN KEY (CSId) REFERENCES CSSeasons(CSId) DEFERRABLE
            )
        """ % self.__dict__)
        cur.execute("""
            CREATE TABLE CSPointSchema (
                PointSchemaId %(primkey)s,
                PSName TEXT
            )
        """ % self.__dict__)
        cur.execute("""
            CREATE TABLE CSPointSchemaEntry (
                PointSchemaEntryId %(primkey)s,
                PointSchemaId INTEGER,
                Position INTEGER,
                Points REAL,
                FOREIGN KEY (PointSchemaId) REFERENCES CSPointSchema(PointSchemaId) DEFERRABLE
            )
        """ % self.__dict__)
        cur.execute("""
            CREATE TABLE CSEventSessions (
                CSEventSessionId %(primkey)s,
                EventId INTEGER,
                SessionId INTEGER,
                PointSchemaId INTEGER,
                SessionName TEXT,
                FOREIGN KEY (EventId) REFERENCES CSEvent(EventId) DEFERRABLE,
                FOREIGN KEY (SessionId) REFERENCES Session(SessionId) DEFERRABLE,
                FOREIGN KEY (PointSchemaId) REFERENCES CSPointSchema(PointSchemaId) DEFERRABLE
            )
        """ % self.__dict__)
        cur.execute("""
            CREATE TABLE PiSCorrections (
                PiSCorrectionId %(primkey)s,
                PlayerInSessionId INTEGER,
                DeltaPoints REAL,
                DeltaTime INTEGER,
                DeltaLaps INTEGER,
                FOREIGN KEY (PlayerInSessionId) REFERENCES PlayerInSession(PlayerInSessionId) DEFERRABLE
            )
        """ % self.__dict__)
        cur.execute("ALTER TABLE Lap ADD COLUMN ESCPressed INTEGER")
        cur.execute("ALTER TABLE Tracks ADD COLUMN RequiredTrackChecksum TEXT")
        cur.execute("ALTER TABLE Cars ADD COLUMN RequiredCarChecksum TEXT")
        self.setVersion(cur, 14)
        acinfo("Migrated from db version 13 to 14.")

    def migrate_14_15(self):
        cur = self.db.cursor()
        # fix the finish position bug from stracker <= 2.4.2
        ans = cur.execute("""
            SELECT SessionId,PlayerInSessionId FROM
            Session NATURAL JOIN PlayerInSession NATURAL JOIN
                (SELECT PlayerInSessionId,MAX(LapCount) AS MaxLapCount FROM Lap GROUP BY PlayerInSessionId) AS MaxLapCountHelper
            WHERE SessionType='Race' AND MaxLapCount=NumberOfLaps AND FinishTime IS NULL
        """).fetchall()
        incorrectPlayerInSessions = list(map(lambda x: (x[0],x[1]), ans)) + [(None, None)]
        lastSid = None
        for i in incorrectPlayerInSessions:
            sid = i[0]
            if not lastSid is None and lastSid != sid:
                acinfo("Correcting Session id=%d", lastSid)
                # correct the session
                ans = cur.execute("""
                    SELECT PlayerInSessionId,FinishTime,MaxLapCount,FinishPosition
                    FROM Session NATURAL JOIN PlayerInSession NATURAL JOIN
                        (SELECT PlayerInSessionId,MAX(LapCount) AS MaxLapCount FROM Lap GROUP BY PlayerInSessionId) AS MaxLapCountHelper
                    WHERE SessionId=:lastSid
                """, locals()).fetchall()
                classification = []
                for a in ans:
                    classification.append(dict(pisid=a[0],finishTime=a[1],numLaps=a[2],pos=a[3]))
                classification = sorted(classification,
                                        key=lambda x: x['finishTime'] if not x['finishTime'] is None else 60*60*1000*24*5+x['pos']-x['numLaps']*1000)
                for newidx,p in enumerate(classification):
                    pos = newidx + 1
                    pisid = p['pisid']
                    if p['finishTime'] is None: pos = 1000
                    acinfo("  PlayerInSession id=%d newPos=%d oldPos=%d", pisid, pos, p['pos'])
                    cur.execute("""
                        UPDATE PlayerInSession SET
                            FinishPosition=:pos
                        WHERE PlayerInSessionId=:pisid
                    """, locals())
            lastSid = sid
            if sid is None:
                break
            pisid = i[1]
            cur.execute("""
                UPDATE PlayerInSession SET
                    FinishTime = (SELECT SUM(LapTime) FROM Lap WHERE PlayerInSessionId=:pisid)
                WHERE PlayerInSessionId=:pisid
            """, locals())
        # some unique indices for the championship thing
        cur.execute("CREATE UNIQUE INDEX CSSeasonsUniqueIndex ON CSSeasons(CSName)")
        cur.execute("CREATE UNIQUE INDEX CSEventUniqueIndex ON CSEvent(CSId,EventName)")
        cur.execute("CREATE UNIQUE INDEX CSEventSessionUniqueIndex ON CSEventSessions(SessionId)")
        cur.execute("CREATE UNIQUE INDEX CSPointSchemaUniqueIndex ON CSPointSchema(PSName)")
        # add missing columns for championships
        cur.execute("ALTER TABLE PlayerInSession ADD COLUMN FinishPositionOrig INTEGER")
        cur.execute("ALTER TABLE PisCorrections ADD COLUMN Comment TEXT")
        cur.execute("UPDATE PlayerInSession SET FinishPositionOrig=FinishPosition")
        self.setVersion(cur, 15)
        acinfo("Migrated from db version 14 to 15.")

    def migrate_15_16(self):
        cur = self.db.cursor()
        # delete duplicate point schema entries (existing due to a bug in the point schema admin
        # interface
        cur.execute("""
            DELETE FROM CSPointSchemaEntry
            WHERE PointSchemaEntryId NOT IN
            (SELECT PseToKeep FROM
                (SELECT MAX(PointSchemaEntryId) AS PseToKeep,PointSchemaId,Position FROM
                 CSPointSchemaEntry GROUP BY PointSchemaId,Position) AS Tmp1
            )
        """, locals())
        cur.execute("CREATE UNIQUE INDEX CSPointSchemaEntryUniqueIndex ON CSPointSchemaEntry(PointSchemaId,Position)")
        self.setVersion(cur, 16)
        acinfo("Migrated from db version 15 to 16.")

    def migrate_16_17(self):
        cur = self.db.cursor()
        # rename vallelunga to vallelunga-extended_circuit
        # and vallelunga-club to vallelunga-club_circuit
        newv = cur.execute("""
            SELECT TrackId FROM Tracks WHERE Track='vallelunga-extended_circuit'
        """).fetchone()
        if newv is None:
            cur.execute("""
                UPDATE Tracks SET Track='vallelunga-extended_circuit' WHERE Track='vallelunga'
            """)
        newc = cur.execute("""
            SELECT TrackId FROM Tracks WHERE Track='vallelunga-club_circuit'
        """).fetchone()
        if newc is None:
            cur.execute("""
                UPDATE Tracks SET Track='vallelunga-club_circuit' WHERE Track='vallelunga-club'
            """)
        self.setVersion(cur, 17)
        acinfo("Migrated from db version 16 to 17.")

    def migrate_17_18(self):
        cur = self.db.cursor()
        cur.execute("""
            CREATE TABLE Teams (
                TeamId %(primkey)s,
                TeamName TEXT
            )
        """ % self.__dict__)
        cur.execute("CREATE UNIQUE INDEX TeamsUniqueIndex ON Teams(TeamName)")
        cur.execute("ALTER TABLE PlayerInSession ADD COLUMN TeamId INTEGER REFERENCES Teams(TeamId) DEFERRABLE")
        self.setVersion(cur, 18)
        acinfo("Migrated from db version 17 to 18.")

    def migrate_18_19(self):
        cur = self.db.cursor()

        cur.execute("ALTER TABLE Tracks ADD COLUMN UiTrackName TEXT")
        cur.execute("ALTER TABLE Tracks ADD COLUMN Length REAL")
        cur.execute("ALTER TABLE Tracks ADD COLUMN MapData %(blob)s" % self.__dict__)

        cur.execute("ALTER TABLE Cars ADD COLUMN UiCarName TEXT")
        cur.execute("ALTER TABLE Cars ADD COLUMN Brand TEXT")
        cur.execute("ALTER TABLE Cars ADD COLUMN BadgeData %(blob)s" % self.__dict__)

        self.setVersion(cur, 19)
        acinfo("Migrated from db version 18 to 19.")

    def migrate_19_20(self):
        cur = self.db.cursor()

        for i in range(10):
            st = "SectorTime%d" % i
            cur.execute("UPDATE Lap SET %(st)s = round(%(st)s) WHERE %(st)s != ROUND(%(st)s)" % locals())

        cur.execute("ALTER TABLE Lap ADD COLUMN Cuts INTEGER")
        cur.execute("ALTER TABLE Lap ADD COLUMN CollisionsCar INTEGER")
        cur.execute("ALTER TABLE Lap ADD COLUMN CollisionsEnv INTEGER")
        cur.execute("ALTER TABLE Lap ADD COLUMN GripLevel REAL")
        cur.execute("ALTER TABLE Players ADD COLUMN Whitelisted INTEGER")

        self.setVersion(cur, 20)
        acinfo("Migrated from db version 19 to 20.")

    def migrate_20_21(self):
        cur = self.db.cursor()

        # was wollen wir?
        #   -> Anzahl Runden/km einer Combo (Track, Cars) ermitteln
        #   -> Ermitteln des Ranks einer bestimmten Zeit innerhalb der Combo
        #   -> Test, ob eine Combo (TrackId,CarId1,...CarIdN) bereits eine ID hat

        # was brauchen wir?
        #   -> Mapping von TrackId, CarId auf ComboId
        #   -> Neue Spalte ComboId in Session

        cur.execute("""
            CREATE TABLE Combos (
                ComboId %(primkey)s,
                TrackId INTEGER,
                FOREIGN KEY (TrackId) REFERENCES Tracks(TrackId) DEFERRABLE
            )
        """ % self.__dict__)
        cur.execute("""
            CREATE TABLE ComboCars (
                ComboCarId %(primkey)s,
                ComboId INTEGER,
                CarId INTEGER,
                FOREIGN KEY (ComboId) REFERENCES Combos(ComboId) DEFERRABLE,
                FOREIGN KEY (CarId) REFERENCES Cars(CarId) DEFERRABLE
            )
        """ % self.__dict__)
        cur.execute("ALTER TABLE Session ADD COLUMN ComboId INTEGER REFERENCES Combos(ComboId)")

        agg_select_stmt = self.selectOrderedAggregate("ComboId", "CarId", "CarIds", "ComboCars")
        cur.execute("""
            CREATE VIEW ComboView AS
            SELECT Combos.ComboId, CarIds, TrackId FROM
                (%(agg_select_stmt)s) AS ComboCars
            LEFT JOIN
                Combos ON (ComboCars.ComboId=Combos.ComboId)
        """ % locals())
        self.fixup_21(cur)
        self.setVersion(cur, 21)
        acinfo("Migrated from db version 20 to 21.")

    def fixup_21(self, cur=None):
        if cur is None:
            cur = self.db.cursor()
            return self.fixup_21(cur)
        # automatically fill from existing data
        # we assume here that the track changes at each combo
        # this will not work very well on multiserver setups with multiple car types per session
        cur.execute("""
            SELECT l.SessionId AS start,
                (
                    SELECT min(a.SessionId) AS SessionId
                    FROM (SELECT * FROM Session WHERE ComboId IS NULL) AS a
                        LEFT OUTER JOIN (SELECT * FROM Session WHERE ComboId IS NULL) as b ON a.SessionId = b.SessionId - 1 AND a.TrackId = b.TrackId
                    WHERE b.SessionId is null
                        and a.SessionId >= l.SessionId
                ) as end
            FROM (SELECT * FROM Session WHERE ComboId IS NULL) AS l
                LEFT OUTER JOIN (SELECT * FROM Session WHERE ComboId IS NULL) AS r ON r.SessionId = l.SessionId - 1 AND r.TrackId = l.TrackId
            WHERE r.SessionId is null
        """)
        ranges = cur.fetchall()
        for r in ranges:
            minId = r[0]
            maxId = r[1]
            cur.execute("""
                SELECT DISTINCT TrackId, CarId FROM
                Session NATURAL JOIN PlayerInSession
                WHERE SessionId >= :minId AND SessionId <= :maxId
                ORDER BY CarId
            """, locals())
            ans = cur.fetchall()
            cars = []
            trackId = None
            for c in ans:
                cars.append(c[1])
                trackId = c[0]
            if not trackId is None and len(cars) > 0:
                comboId = self.getOrCreateComboId(cur, trackId, cars)
                cur.execute("""
                    UPDATE Session SET ComboId = :comboId WHERE SessionId >= :minId AND SessionId <= :maxId AND ComboId IS NULL
                """, locals())

    def migrate_21_22(self):
        cur = self.db.cursor()
        cur.execute("ALTER TABLE Players ADD COLUMN MessagesDisabled INTEGER")
        cur.execute("ALTER TABLE Lap ADD COLUMN Ballast REAL")
        # seperate the history info from the lap table, for this is bad for sqlite queries
        cur.execute("""
            CREATE TABLE LapBinBlob(
            	LapBinBlobId %(primkey)s,
            	LapId INTEGER,
            	HistoryInfo %(blob)s,
            	FOREIGN KEY (LapId) REFERENCES Lap(LapId) DEFERRABLE
            )
        """ % self.__dict__)
        cur.execute("""
            CREATE TABLE ChatHistory(
                ChatHistoryId %(primkey)s,
                PlayerId INTEGER,
                Timestamp INTEGER,
                Content TEXT,
                Server TEXT,
            	FOREIGN KEY (PlayerId) REFERENCES Players(PlayerId) DEFERRABLE
            )
        """ % self.__dict__)
        self.fixup_22(cur)
        self.setVersion(cur, 22)
        acinfo("Migrated from db version 21 to 22.")

    def fixup_22(self, cur=None):
        if cur is None:
            cur = self.db.cursor()
            return self.fixup_22(cur)
        cur.execute("INSERT INTO LapBinBlob(LapId, HistoryInfo) SELECT LapId, HistoryInfo FROM Lap WHERE HistoryInfo NOTNULL")
        cur.execute("UPDATE Lap SET HistoryInfo=NULL WHERE HistoryInfo NOTNULL")
        # make sure that the session duration is a sane integer, this gives errors when migrating to postgres otherwise
        cur.execute("UPDATE Session SET Duration=8640000 WHERE Duration > 8640000")

    def migrate_22_23(self):
        cur = self.db.cursor()
        cur.execute("""
            CREATE TABLE MinoratingCache (
                MRCacheId %(primkey)s,
                PlayerId INTEGER,
                Timestamp INTEGER,
                Minorating TEXT,
                FOREIGN KEY (PlayerId) REFERENCES Players(PlayerId) DEFERRABLE
            )
        """ % self.__dict__)
        self.setVersion(cur, 23)