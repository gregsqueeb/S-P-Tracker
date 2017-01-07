# FetchParge-code originated by Stereo (stereo_minoprint.py)
# personally I have no clue what I'm doing, so please call in if you see improvements
from ptracker_lib import acsim
from ptracker_lib.helpers import *
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
lastErrorTimestamp = 0
errors_in_sequence = 0

# The result contains some Ids that will speed up the query massively,
# so we'll just store them on the fly
lastMRSessionId = -1
driverSteamId = -1

# driver name, car model and track are unique per Helicorsa session, they only need to be setup once
driverName = ""
carModel = ""
track = ""
ratings = {}

# this is the template for the web request
urlstrtemplate = 'http://app.minorating.com:805/minodata/getMRServerInfo/?id={}&session={}&name={}&model={}&track={}&anotherDriver=&sessionType=&serverIp={}&serverPort={}'
urlstr = ""

def initConstants():
    global driverName, carModel, track

    driverName = acsim.ac.getDriverName(0)
    carModel = acsim.ac.getCarName(0)
    track = acsim.ac.getTrackName(0)
    if(str(acsim.ac.getTrackConfiguration(0)) == "-1"):
        track = track + "[]"
    else:
        track = track + "[" + acsim.ac.getTrackConfiguration(0) + "]"

def requestMinoratingData():
    global requestPending, urlstr
    if carModel == "":
        initConstants()
    min_delay = 10
    if errors_in_sequence > 2:
        min_delay = 20
    if errors_in_sequence > 4:
        min_delay = 60
    if errors_in_sequence > 6:
        min_delay = 300
    if errors_in_sequence > 9:
        min_delay = 3000000
    if requestPending == False and acsim.ac.getServerIP() != "" and (lastErrorTimestamp == 0 or (time.time() - lastErrorTimestamp > min_delay)):
        # limit MR requests to 1 per 2 minutes in case of negative responses from MR
        urlstr = urlstrtemplate.format(driverSteamId, lastMRSessionId, driverName, carModel, track, acsim.ac.getServerIP(), acsim.ac.getServerHttpPort())
        acdebug("helithreading::FetchPage.Start(): " + urlstr)
        requestPending = True
        FetchPage().start()

def getDriverRating(name):
    if not name in ratings:
        requestMinoratingData()
    return ratings.get(name, None)

class FetchPage(threading.Thread):
    def run(self):
        global requestPending, lastMRSessionId, driverSteamId, ratings, lastErrorTimestamp

        try:
            # this replaces spaces with %20 and so forth
            url = urllib.parse.quote(urlstr, safe="%/:=&?~#+!$,;'@()*[]")
            request_resp = ""
            with urllib.request.urlopen(url, timeout=5) as mresponse:
                request_resp = mresponse.read().decode('utf-8')
                acdebug("MR returned %s", request_resp)
                json_data = json.loads(request_resp)
                new_ratings = {}
                for d in json_data["drivers"]:
                    new_ratings[d["name"]] = d["grade"]
                ratings = new_ratings
                lastMRSessionId = json_data["sessionId"]
                if driverSteamId == -1:
                    driverSteamId = json_data["driverSteamId"]
                lastErrorTimestamp = 0
                errors_in_sequence = 0
                acdebug("helithreading::FetchPage() successful")
        except Exception as e:
            acwarning("helithreading::FetchPage(): error: %s", str(e))
            acwarning("info returned: %s", str(request_resp))
            lastErrorTimestamp = time.time()
            errors_in_sequence += 1
        requestPending = False