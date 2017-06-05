# FetchParge-code originated by Stereo (stereo_minoprint.py)
# personally I have no clue what I'm doing, so please call in if you see improvements
from ptracker_lib import acsim
from ptracker_lib.helpers import *
from ptracker_lib.ac_ini_files import RaceIniFile
import json
import threading
import time

try:
  import urllib.request
  import urllib.parse
except Exception as ex:
  acerror("helithreading::urllib not imported: {}".format(str(ex)))

# We'll store any result we get from the MR backend here, it's assumed that
# some other piece of code just uses this AND SETs TO NONE THEN
requestPending = False
lastErrorTimestamp = time.time()
errors_in_sequence = 0

# driver name, car model and track are unique per Helicorsa session, they only need to be setup once
lockit = threading.RLock()
ratings = {}
name_queries = {}

# this is the template for the web request
urlstrtemplate = 'http://app.minorating.com:806/minodata/drivers/?serverIp={}&serverPort={}'
urlstr = ""

def requestMinoratingData(name):
    global requestPending, urlstr, name_queries
    curr_t = time.time()
    min_delay = 10
    if errors_in_sequence > 2:
        min_delay = 20
    if errors_in_sequence > 4:
        min_delay = 60
    if errors_in_sequence > 6:
        min_delay = 300
    if errors_in_sequence > 9:
        min_delay = 3000000
    # limit MR requests, maximum 1 per 10s, and in case of negative responses maximum 10 negative responses in sequence
    if requestPending == False and acsim.ac.getServerIP() != "" and (lastErrorTimestamp == 0 or (curr_t - lastErrorTimestamp > min_delay)):
        # delete old names from queries
        for name in list(name_queries.keys()):
            if curr_t - name_queries[name][1] > 120:
                acdebug("remove %s from MR cache", name)
                del name_queries[name]
                with lockit:
                    if name in ratings:
                        del ratings[name]
        urlstr = urlstrtemplate.format(acsim.ac.getServerIP(), acsim.ac.getServerHttpPort())
        acdebug("helithreading::FetchPage.Start(): " + urlstr)
        requestPending = True
        FetchPage().start()

def getDriverRating(name):
    global name_queries
    curr_t = time.time()
    if not name in name_queries:
        name_queries[name] = [curr_t, curr_t]
    name_queries[name][1] = curr_t
    nqt = name_queries[name]
    # don't query old names over and over again, just query new names
    with lockit:
        incache = name in ratings
    if not incache and nqt[1] - nqt[0] < 25.:
        requestMinoratingData(name)
    return ratings.get(name, None)

class FetchPage(threading.Thread):
    def run(self):
        global requestPending, lastMRSessionId, driverSteamId, ratings, lastErrorTimestamp, errors_in_sequence

        try:
            # this replaces spaces with %20 and so forth
            url = urllib.parse.quote(urlstr, safe="%/:=&?~#+!$,;'@()*[]")
            request_resp = ""
            with urllib.request.urlopen(url, timeout=5) as mresponse:
                request_resp = mresponse.read().decode('utf-8')
                acdebug("MR returned %s", request_resp)
                json_data = json.loads(request_resp)
                new_ratings = {}
                for d in json_data:
                    new_ratings[d["name"]] = d["grade"]
                with lockit:
                    for name in ratings:
                        if not name in new_ratings:
                            new_ratings[name] = ratings[name]
                    ratings = new_ratings
                lastErrorTimestamp = time.time()
                errors_in_sequence = 0
                acdebug("helithreading::FetchPage() successful")
        except Exception as e:
            acwarning("helithreading::FetchPage(): error: %s", str(e))
            acwarning("info returned: %s", str(request_resp))
            lastErrorTimestamp = time.time()
            errors_in_sequence += 1
        requestPending = False