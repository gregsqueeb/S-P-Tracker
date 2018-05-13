import json
import pygal
import subprocess
import datetime
import array
import bisect

def datetime2unixts(dt):
    return float( (dt - datetime.datetime(1970,1,1)).total_seconds() )

class SAR:
    def __init__(self, binary_files, sadf_call = '/usr/bin/sadf -j -- -A 300'.split(" ")):
        self.S = {}
        # the goal is to have a structure S[HOST][SIGNAL] -> (TS array, value array)
        for f in binary_files:
            print(sadf_call + [f])
            try:
                json_o = subprocess.check_output(sadf_call + [f], universal_newlines=True)
            except:
                json_o = subprocess.check_output(sadf_call + [f], universal_newlines=True, shell=True)
            #print(len(json_o))
            jc = json.loads(json_o)
            for h in jc['sysstat']['hosts']:
                host = h['nodename']
                if not host in self.S: self.S[host] = {}
                for s in h['statistics']:
                    if not 'timestamp' in s: continue
                    timestamp = datetime2unixts(datetime.datetime.strptime(s['timestamp']['date'] + " " + s['timestamp']['time'], "%Y-%m-%d %H:%M:%S"))
                    for d in s:
                        if d == "timestamp": continue
                        self._walk_dict(host, timestamp, d, s[d])
        print("parsing finished")

    def _walk_dict(self, host, timestamp, signal_name, v):
        if type(v) in (float, int):
            if not signal_name in self.S[host]: self.S[host][signal_name] = (array.array('d'), array.array('d'))
            idx = bisect.bisect_left(self.S[host][signal_name][0], timestamp)
            self.S[host][signal_name][0].insert(idx,timestamp)
            self.S[host][signal_name][1].insert(idx,v)
        elif type(v) == dict:
            for k in v:
                self._walk_dict(host, timestamp, signal_name+"/"+k, v[k])
        elif type(v) in (list, tuple):
            for e in v:
                # elements should be dicts containing exactly one string
                if type(e) == dict:
                    name = None
                    for k in e:
                        if type(e[k]) == str:
                            name = signal_name + "/" + e[k]
                    if not name is None:
                        self._walk_dict(host, timestamp, name, e)
        elif type(v) == str:
            # probably the signal name of a list group
            pass

    def hosts(self):
        return sorted(list(self.S.keys()))

    def signals(self):
        signals = set()
        for h in self.hosts():
            for s in self.S[h]:
                signals.add(s)
        return signals

    def get(self, signal_names, span, max_samples, host=None):
        if host is None: host = self.hosts()[0]
        s = [self.S[host][signal_name] for signal_name in signal_names]
        r = []
        tnow = datetime2unixts(datetime.datetime.now())
        min_t = tnow - span[0]*60*60
        max_t = tnow - span[1]*60*60
        min_idx = bisect.bisect_left(s[0][0], min_t)
        max_idx = bisect.bisect_right(s[0][0], max_t)
        avg = []
        print(min_t, max_t, min_idx, max_idx)
        totalSamples = max_idx - min_idx
        for idx in range(min_idx, max_idx):
            t = s[0][0][idx]
            v = s[0][1][idx]
            for sub in s[1:]:
                v = v - sub[1][idx]
            avg.append( ((t-tnow)/(60*60), v) )
            n = idx - min_idx
            if len(r) < n*max_samples/totalSamples:
                r.append((avg[0][0], sum([x[1] for x in avg])/len(avg)))
                avg = []
        return r
