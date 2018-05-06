
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

from threading import Thread, RLock
from queue import Queue, Full, Empty
import html
import urllib.parse
import urllib.request
import time
import traceback
import pickle

import cherrypy

from ptracker_lib.helpers import *
from stracker_lib import config

AUTH_CACHE_MAINTAINANCE_INTERVAL = 1800  # 30 minutes
MAX_CACHE_ENTRIES = 1000 # should be < 1 MB

class AuthCache(Thread):
    singleton = None

    def __init__(self, db):
        assert AuthCache.singleton is None
        AuthCache.singleton = self
        self.db = db
        self.blacklist = self.getBlacklistedPlayers()
        self.whitelist = self.getWhitelistedPlayers()
        self.cache_local = {}
        self.lock = RLock()
        self.queue = Queue(2)
        Thread.__init__(self, daemon=True)
        self.start()

    def getBlacklistedPlayers(self):
        players = self.db.getPlayers(__sync = True, limit=None, inBanList = True)()
        res = set()
        for p in players['players']:
            res.add(p['guid'])
        if config.config.HTTP_CONFIG.auth_ban_anonymized_players:
            players = self.db.getPlayers(__sync = True, limit=None, anonymized = True)()
            for p in players['players']:
                res.add(p['guid'])
        return res

    def rescanBlacklist(self):
        bl = self.getBlacklistedPlayers()
        with self.lock:
            self.blacklist = bl

    def getWhitelistedPlayers(self):
        players = self.db.getPlayers(__sync = True, limit=None, inWhitelist = True)()
        res = set()
        for p in players['players']:
            res.add(p['guid'])
        return res

    def get_local(self, **kw):
        GUID = guidhasher(kw['guid'])
        maxTimePercentage = kw['maxTimePercentage']
        maxRank = kw['maxRank']
        minNumLaps = kw['minNumLaps']
        with self.lock:
            if GUID in self.blacklist:
                return False, ["You are currently banned from this server."]
            if GUID in self.whitelist:
                return True, []
        if maxTimePercentage is None and maxRank is None and minNumLaps is None:
            return "OK"
        k = pickle.dumps(tuple(sorted(kw.items(), key=lambda x: x[0])))
        with self.lock:
            entry = self.cache_local.get(k, None)
        if entry is None:
            entry = dict(
                access_time=time.time(),
                result=self.runauth(**kw)
                )
            with self.lock:
                self.cache_local[k] = entry
        with self.lock:
            self.cache_local[k]['access_time'] = time.time()
        return entry['result']

    def runauth(self, **kw):
        kw['__sync'] = True
        return self.db.auth(**kw)()

    def run(self):
        while 1:
            try:
                try:
                    self.queue.get(True, AUTH_CACHE_MAINTAINANCE_INTERVAL) # maintain cache each 30 minutes
                except Empty:
                    pass
                acdebug("Starting acauth cache maintainance")
                bl = self.getBlacklistedPlayers()
                wl = self.getWhitelistedPlayers()
                with self.lock:
                    self.blacklist = bl
                    self.whitelist = wl
                t = time.time()
                with self.lock:
                    keys = list(self.cache_local.keys())
                keys.sort(key=lambda x: self.cache_local[x]['access_time'], reverse=True)
                for idx,k in enumerate(keys):
                    kw = dict(pickle.loads(k))
                    accessTime = self.cache_local[k]['access_time']
                    if t - accessTime > 60*60*24*7 or idx > MAX_CACHE_ENTRIES:
                        with self.lock:
                            del self.cache_local[k]
                    else:
                        entry = dict(
                            access_time=accessTime,
                            result=self.runauth(**kw)
                            )
                        with self.lock:
                            self.cache_local[k] = entry
                        time.sleep(0.1)
                acdebug("Done with acauth cache maintainance")
            except:
                acerror("error in acauth thread.")
                acerror(traceback.format_exc())

    def reset(self):
        try:
            self.queue.put(None, False)
        except Full:
            pass

class PerformAuth(Thread):
    MODE_PROXY=0
    MODE_LOCAL=1

    def __init__(self, mode, **kw):
        self.mode = mode
        self.result = ""
        self.kw = kw
        Thread.__init__(self, daemon=True)
        self.start()

    # the signature of this function is used to check the url parameters.
    def perform_auth(self, db, GUID=None, PSW=None, track=None, cars=None, server=None, valid=None, tyre_list=None, maxTimePercentage=None, maxRank=None, minNumLaps=None,
                           andurl=None, timeout=None, andurl1=None, andurl2=None, andurl3=None, andurl4=None, andurl5=None, groups=[]):
        if self.mode == self.MODE_PROXY:
            if not andurl is None:
                if not andurl.startswith('http://'):
                    andurl = "http://" + andurl
                if not andurl.endswith('&') and not andurl.endswith('?'):
                    if '?' in andurl:
                        andurl += '&'
                    else:
                        andurl += '?'
                andurl = andurl + "GUID=%s" % (GUID + (("&PSW=%s" % PSW) if not PSW is None else ""))
                acdebug("opening url: %s", andurl)
                andurl_ans = urllib.request.urlopen(andurl)
                return andurl_ans.read().decode(andurl_ans.headers.get_content_charset('utf-8')).strip()
            raise RuntimeError
        elif self.mode == self.MODE_LOCAL:
            ok, reason = AuthCache.singleton.get_local(
                guid=GUID,
                track=track,
                cars=cars.split(",") if not cars in [None,''] else None,
                server=server,
                valid=valid.split(",") if not valid in [None,''] else None,
                tyre_list=tyre_list.split(",") if not tyre_list in [None,''] else None,
                minNumLaps=int(minNumLaps) if not minNumLaps in [None,''] else None,
                maxTimePercentage=float(maxTimePercentage) if not maxTimePercentage in [None,''] else None,
                maxRank=int(maxRank) if not maxRank in [None,''] else None,
                groups=groups)
            if ok:
                return "OK"
            else:
                return "DENY|" + ";".join(reason)
        raise RuntimeError

    @callbackDecorator
    def run(self):
        self.result = self.perform_auth(**self.kw)

def acauth(admin, db, **kw):
    GUID = kw.get('GUID', None)
    PSW = kw.get('PSW', None)
    if 'curr_url' in kw:
        del kw['curr_url']
    if GUID is None and PSW is None and admin:
        help_text = """<html>
Use this page as target for server_cfg.ini&#39;s AUTH_PLUGIN_ADDRESS=127.0.0.1:&lt;stracker_http_port&gt;/acauth? <br>
You can use the following arguments after ?:
<ul>
    <li>track:  The track name used for lap stat filtering. If omitted, the current combo will be used (for multiserver setups, be sure to set the server argument)</li>
    <li>cars:   The cars used for lap stat filtering (comma seperated). If omitted the current combo will be used (for multiserver setups, be sure to set the server argument)</li>
    <li>server: The stracker server name of the server used for lap stat filtering. If omitted, lap times of all servers will be queried.</li>
    <li>valid:  Which laps shall be taken into account (comma seperated list of integers). If omitted, valid and unknown laps will be used (0,1). </li>
    <li>tyre_list: The list of tyre used for lap stat filtering (comma seperated). If omitted all tyres will be used.</li>
    <li>groups: The list of groups (comma seperated list of integer ids) used for lap stat filtering. If omitted all drivers will be used.</li>
    <li>minNumLaps: The minimum number of laps done for this combo.</li>
    <li>maxTimePercentage: If the user's best lap time (according to prior definitions) is out of bounds, he will not be able to join the server. </li>
    <li>maxRank: If the user's rank in the best lap time statistics (according to prior definitions) is out bounds, he will not be able to join the server.</li>
    <li>andurl1: Additional auth URL (quoted). The auth request will only pass, if the result of this URL is OK. URL's need to be quoted, i.e. replace
                 ':' characters with %%3A, '?' characters with %%3F and '&' characters with %%26. Example for minorating: <br>andurl1=%s</li>
    <li>andurl2: further url to be checked (format is as andulr1).</li>
    <li>andurl3: further url to be checked (format is as andulr1).</li>
    <li>andurl4: further url to be checked (format is as andulr1).</li>
    <li>andurl5: further url to be checked (format is as andulr1).</li>
    <li>timeout: Timeout in milliseconds for the request. After the timeout has passed, the user will be denied and asked to try again. Default no timeout. Note that
                 it is highly recommended to apply a timeout to the query because long running queries are known to cause server lags (for me it started around 100 ms). If you
                 are using none of minNumLaps, maxTimePercentage or maxRank users shall normally not encounter a timeout because the queries are optimized. If you are using
                 one of the above, your users might have to reconnect when they get an AUTH message notifying about a timeout. It is generally not possible to keep the runtime
                 of the needed queries low enough without caching them.
    </li>
</ul>
Blacklisted players are never authorized. <br>
Whitelisted players are always authorized. <br>
<br>
Examples:
    <ul>
        <li>
            <i>%s</i>
            <br>
            This example filters the best lap times on the nurburgring achieved on the server named acserver with BMW M3 E30 or the Audi quattro.
            Only valid or unknown laps are considered, on Street Vintage or Street tyres. If the user&#39;s best lap is within 105 percent of the server&#39;s best lap and
            the rank of the player is below or equal to 15, the player is allowed to enter the server.
        </li>
        <li>
            <i>%s</i>
            <br>
            This allows all drivers who drove at least 20 laps on acserver with acserver's current combo.
        </li>
        <li>
            <i>%s</i>
            <br>
            This allows all drivers of specific groups (who have driven at least one lap on acserver's current combo).
            Specifying group only has effeccts together with at least one of minNumLaps, maxTimePercentage or maxRank.
            The group has to be specified with the numeric identifier. You get this identifier by selecting the group
            in the lapstat page and inspecting the generated url.
        </li>
    </ul>
</html>""" % (html.escape(urllib.parse.quote("plugin.minorating.com:805/minodata/auth/ABCN/?")),
              html.escape("AUTH_PLUGIN_ADDRESS=127.0.0.1:50041/acauth?track=nurburgring&cars=bmw_m3_e30,ks_audi_sport_quattro&server=acserver&valid=1,2&tyre_list=(SV),(ST)&maxTimePercentage=105&maxRank=15&"),
              html.escape("AUTH_PLUGIN_ADDRESS=127.0.0.1:50041/acauth?server=acserver&minNumLaps=20&"),
              html.escape("AUTH_PLUGIN_ADDRESS=127.0.0.1:50041/acauth?server=acserver&minNumLaps=1&groups=4,5&"),
              )
        return help_text
    else:
        start_t = time.time()
        timeout = kw.get('timeout', None)
        acinfo("acauth request: %s", cherrypy.request.request_line)
        try:
            kw['db'] = db
            # start a thread for the local request
            thrds = [PerformAuth(PerformAuth.MODE_LOCAL, **kw)]
            # start one thread for each andurl
            for i in range(5):
                andurl = kw.get("andurl%d" % (i+1), None)
                if not andurl is None:
                    nkw = kw.copy()
                    nkw["andurl"] = andurl
                    thrds.append(PerformAuth(PerformAuth.MODE_PROXY, **nkw))
            # join the threads respecting the timeout setting (if any)
            for t in thrds:
                t.join(timeout=(float(timeout)*0.001 - (time.time()-start_t)) if not timeout is None else None)
            # create results string
            results = "', '".join([t.result for t in thrds])
            results = "'" + results + "'"
            # check for explicit denies
            for t in thrds:
                r = t.result
                if r.startswith("DENY"):
                    acwarning("acauth deny: %s", results)
                    return r
            # check for timeouts
            for t in thrds:
                r = t.result
                if r == "":
                    acwarning("acauth timeout: %s", results)
                    return "DENY|Timeout while processing request. Please try again."
            if all([t.result.startswith("OK") for t in thrds]):
                acinfo("acauth passed: %s", results)
                return "OK"
        except:
            if not 'results' in locals(): results = '?'
            acerror("Error in acauth:")
            acerror(traceback.format_exc())
        acerror("acauth error: %s", results)
        return "DENY|Internal error. Please report this event to the server's administrator."
