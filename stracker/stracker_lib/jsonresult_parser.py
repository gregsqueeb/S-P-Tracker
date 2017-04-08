from ptracker_lib.helpers import *

import simplejson as json

class JsonResults:

    def __init__(self,filename):
        acdebug("opening result json file %s", filename)
        self._R = json.load(open(filename), strict=False)

    def isRace(self):
        return self._R["Type"] == "RACE"

    def racePositions(self):
        guid = [x['DriverGuid'] for x in self._R["Result"]]
        model = [x['CarModel'] for x in self._R["Result"]]
        drivers = list(zip(guid,model))
        totaltime = [int(x['TotalTime']) for x in self._R["Result"]]
        numlaps = [0] * len(self._R["Result"])
        for l in self._R["Laps"]:
            d = (l["DriverGuid"], l["CarModel"])
            if d in drivers:
                numlaps[drivers.index(d)] += 1
        result = {}
        for pos,d in enumerate(drivers):
            if totaltime[pos] > 0:
                result[d] = {'totaltime': totaltime[pos], 'numlaps': numlaps[pos], 'position': pos}
        return result
