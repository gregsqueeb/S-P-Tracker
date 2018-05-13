# -*- coding: utf-8 -*-

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
from ptracker_lib import acsim
import datetime
import calendar
import time
import math
import re
import functools
import traceback

__all__ = ['myassert', 'acdump', 'acdebug', 'acinfo', 'acwarning', 'acerror',
           'time_to_min_sec_msec_tuple', 'time_to_min_sec_hsec_tuple',
           'calc_comparison', 'format_time_ms', 'format_time', 'format_time_s',
           'datetime2unixtime', 'unixtime2datetime', 'unixtime_now',
           'utc2localtime', 'localtime2utc', 'format_datetime',
           'point_distance', 'callbackDecorator', 'isProMode',
           'format_temp', 'format_vel', 'setFormatUnits',
           'genericAcCallback', 'tracer', "acverbosity", "StringShortener", "DBBusyError",
           "guidhasher"]

class DBBusyError(RuntimeError):
    pass

def tracer(frame, event, arg):
    if event != 'call':
        return
    co = frame.f_code
    func_name = co.co_name
    if func_name == 'write':
        # Ignore write() calls from print statements
        return
    #func_line_no = frame.f_lineno
    #func_filename = co.co_filename
    traceback.print_stack(frame)
    print()

def myassert(cond, *args):
    if not cond:
        raise AssertionError(*args)

lastMsg = None
lastMsgCount = 0
def aclog(msg, *args, **kw):
    global lastMsg, lastMsgCount
    if len(args) > 0:
        msg = msg % args
    if len(kw) > 0:
        msg = ("%(log_prefix)s: " % kw) + msg
    # (try to) fix broken streams with unicode characters
    msg = msg.encode('ascii', 'replace').decode('ascii')
    try:
        log = acsim.ac.log
    except KeyError:
        log = print
    if msg == lastMsg:
        lastMsgCount += 1
        # no need to log again - we will log the repetition counter when the next different
        # message appears
        return
    else:
        if lastMsgCount > 1:
            log("%s: (last message repeated %d times)" % (kw['log_prefix'], lastMsgCount-1) )
        lastMsg = None
        lastMsgCount = 0
    lastMsg = msg
    lastMsgCount += 1
    log(msg)

default_prefix = "ptracker.py"
def restore_loggers(verbosity, prefix=None):
    global iacdump, iacdebug, iacinfo, iacwarning, iacerror, default_prefix
    if prefix is None:
        prefix = default_prefix
    else:
        default_prefix = prefix
    iacdump    = functools.partial(aclog, log_prefix=prefix+"[DUMP ]")
    iacdebug   = functools.partial(aclog, log_prefix=prefix+"[DEBUG]")
    iacinfo    = functools.partial(aclog, log_prefix=prefix+"[INFO ]")
    iacwarning = functools.partial(aclog, log_prefix=prefix+"[WARN ]")
    iacerror   = functools.partial(aclog, log_prefix=prefix+"[ERROR]")
    try:
        acinfo("Log verbosity changed: %d", verbosity)
    except:
        pass # at start of ptracker server, we are not yet able to log
    if verbosity < 1:
        iacwarning = lambda *args, **kw: None
    if verbosity < 2:
        iacinfo = lambda *args, **kw: None
    if verbosity < 3:
        iacdebug = lambda *args, **kw: None
    if verbosity < 4:
        iacdump = lambda *args, **kw: None

acverbosity = 2
restore_loggers(verbosity=acverbosity)

def acerror(*args, **kw):
    iacerror(*args, **kw)
def acwarning(*args, **kw):
    iacwarning(*args, **kw)
def acinfo(*args, **kw):
    iacinfo(*args, **kw)
def acdebug(*args, **kw):
    iacdebug(*args, **kw)
def acdump(*args, **kw):
    iacdump(*args, **kw)

try:
    from dateutil.tz import gettz
    gettzav = True
except ImportError:
    gettz = lambda: None
    gettzav = False

def time_to_min_sec_msec_tuple(t):
    mins = t // (60*1000)
    secs = (t - 60*1000*mins) // 1000
    msecs = (t - 60*1000*mins - secs*1000)
    return (mins, secs, msecs)

def time_to_min_sec_hsec_tuple(t):
    try:
        t = int(round(t/10.))
    except:
        t = 0
    mins = t // (60*100)
    secs = (t - 60*100*mins) // 100
    hsecs = (t - 60*100*mins - secs*100)
    return (mins, secs, hsecs)

def calc_comparison(curr,best,label):
    if curr is None or curr <= 0 or best is None or best <= 0:
        res = (None,curr,best,label)
    else:
        res = (curr - best,curr,best,label)
    return res

def format_time_ms(t, isDelta):
    if not t is None:
        mins, secs, msecs = time_to_min_sec_msec_tuple(abs(t))
        if isDelta:
            sign = "+"
            if t < 0: sign = "-"
            res = "%s%02d.%03d" % (sign, mins*60+secs, msecs)
        else:
            res = "%02d:%02d.%03d" % (mins, secs, msecs)
    else:
        if isDelta:
            res = "+--.---"
        else:
            res = "--.--.---"
    return res

def format_time(t, isDelta):
    if not t is None:
        mins, secs, hsecs = time_to_min_sec_hsec_tuple(abs(t))
        if isDelta:
            sign = "+"
            if t < 0: sign = "-"
            res = "%s%02d.%02d" % (sign, mins*60+secs, hsecs)
        else:
            res = "%02d:%02d.%02d" % (mins, secs, hsecs)
    else:
        if isDelta:
            res = "+--.--"
        else:
            res = "--.--.--"
    return res

def format_time_s(t):
    if not t is None:
        mins, secs, hsecs = time_to_min_sec_hsec_tuple(abs(t))
        res = "%02d:%02d" % (mins, secs)
    else:
        res = "--:--"
    return res

def datetime2unixtime(dt):
    return int(calendar.timegm(dt.timetuple()))

def unixtime2datetime(t):
    return datetime.datetime.utcfromtimestamp(t)

def utc2localtime(dt):
    global gettzav
    if not gettzav:
        gettzav = True
        acerror("cannot import dateutil.tz. timezones will be inaccurate.")
    return dt.replace(tzinfo=datetime.timezone.utc).astimezone(gettz()).replace(tzinfo=None)

def localtime2utc(dt):
    global gettzav
    if not gettzav:
        gettzav = True
        acerror("cannot import dateutil.tz. timezones will be inaccurate.")
    return dt.replace(tzinfo=gettz()).astimezone(datetime.timezone.utc).replace(tzinfo=None)

def unixtime_now():
    return datetime2unixtime(datetime.datetime.utcnow())

def format_datetime(dt, onlyDate=False):
    dt = utc2localtime(dt)
    if not onlyDate:
        return str(dt)[:len("0000-00-00 00:00")]
    else:
        return str(dt.date())

def point_distance(p1, p2):
    return math.sqrt((p1[0]-p2[0])**2 + (p1[1]-p2[1])**2 + (p1[2]-p2[2])**2)

# helper functions
def callbackDecorator(f):
    if acsim.offline():
        if not hasattr(callbackDecorator, "offlineWarningIssued"):
            callbackDecorator.offlineWarningIssued = True
            acinfo("we are offline, no exception catching is performed")
        return f

    @functools.wraps(f)
    def new_f(*args, **kw):
        try:
            return f(*args, **kw)
        except:
            acerror("error caught:\n%s", traceback.format_exc())

    return new_f

def isProMode(lapStatEntry):
    l = lapStatEntry
    proModeOK = 0
    proModeNOK = 0
    proModeUnknown = 0
    proModeSettings = {
        'tyreWear':1.,
        'fuelRate':1.,
        'damage':1.,
        'abs':[-1.1,0.1],
        'tractionControl':[-1.1,0.1],
        'autoBlib':0,
        'autoBrake':0,
        'autoShift':0,
        'idealLine':0,
        'stabilityControl':0.,
        'tempAmbient':26,
        'tempTrack':32
    }
    for k in proModeSettings.keys():
        v = l.get(k, None)
        if v is None:
            proModeUnknown += 1
        elif ((type(proModeSettings[k]) != type([]) and abs(v-proModeSettings[k]) < 1e-5) or
              (type(proModeSettings[k]) == type([]) and v >= proModeSettings[k][0] and v <= proModeSettings[k][1])):
            proModeOK += 1
        else:
            proModeNOK += 1
    if proModeNOK == 0 and proModeUnknown == 0:
        return 1
    elif proModeNOK > 0:
        return 0
    else:
        return 2

def format_temp_celsius(x):
    return "%d °C" % (int(x))

def format_temp_fahrenheit(x):
    return "%d °F" % (int(x*9./5. +  32.))

def format_vel_kmh(x):
    return "%d km/h" % (int(x))

def format_vel_mph(x):
    return "%d mph" % (int(x/1.609344))

vel_unit = "km/h"
temp_unit = "°C"
def setFormatUnits(vel_u, temp_u):
    global vel_unit, temp_unit
    vel_unit = vel_u
    temp_unit = temp_u

def format_temp(x):
    if temp_unit == "°C":
        return format_temp_celsius(x)
    elif temp_unit == "°F":
        return format_temp_fahrenheit(x)
    else:
        return "? "+temp_unit

def format_vel(x):
    if vel_unit == "km/h":
        return format_vel_kmh(x)
    elif vel_unit == "mph":
        return format_vel_mph(x)
    else:
        return "? "+vel_unit

class StringShortener:
    def __init__(self, l, n):
        # find minimal i such that l[:][:i] is unique
        max_len = max([len(x) for x in l])
        if max_len <= n:
            self.long2short = dict([(x,x) for x in l])
        else:
            # we need to cut down

            def testValid(l):
                s = set()
                for x in l:
                    if x in s: return False
                    s.add(x)
                return True

            solutions = []

            for www in range(2):
                if www == 0:
                    # try word-wise
                    def splitWords(x):
                        words = re.split(r'\s', x)
                        new_words = []
                        prefix = ''
                        for w in words:
                            if re.match(r'^[0-9]*$', w) or re.match(r'^\S$', w):
                                if len(new_words) > 0:
                                    new_words[-1] = new_words[-1] + " " + w
                                else:
                                    prefix = w + ' '
                            else:
                                new_words.append(prefix+w)
                                prefix = ''
                        if len(prefix) > 0:
                            new_words.append(prefix)
                        return new_words

                    words = [list(filter(lambda x: x not in [None, ''], re.split(r'(?:[ _]+)|(?:\b(?:[0-9]+)\b)|(?:\b\w\b)', x))) for x in l]
                    js = " "
                    min_items = 1
                    ins = [[], [], [".."]]
                else:
                    # try character-wise
                    words = l[:]
                    min_items = n-2
                    js = ""
                    ins = ["..","..",".."]

                num_words = [len(w) for w in words]
                min_num_words = min(num_words)
                max_num_words = max(num_words)

                # -> try to cancel out last part, keeping wi words (including all words)
                for wi in range(min_items,max_num_words-1):
                    nl = [js.join(words[k][:wi] + ins[0]) for k in range(len(l))]
                    if testValid(nl):
                        solutions.append(dict(zip(l, nl)))
                        break

                # -> try to cancel out first part
                for wi in range(min_items, max_num_words-1):
                    nl = [js.join(ins[1] + words[k][-wi:]) for k in range(len(l))]
                    if testValid(nl):
                        solutions.append(dict(zip(l, nl)))
                        break

                # -> try to cancel out mid part
                for wi1 in range(min_items-1, min_num_words-2):
                    for wi2 in range(1, min_num_words-wi1):
                        nl = [js.join(words[k][:wi1] + ins[2] + words[k][-wi2:]) for k in range(len(l))]
                        if testValid(nl):
                            solutions.append(dict(zip(l, nl)))
                            break

            self.long2short = None

            # check for a solution fulfilling the n-constraint
            for l2s in solutions:
                maxl = max([len(l2s[x]) for x in l])
                if maxl <= n:
                    self.long2short = l2s
                    break

            if self.long2short is None and len(solutions) > 0:
                self.long2short = solutions[0]

            if self.long2short is None:
                self.long2short = dict([(x,x) for x in l])

    def apply(self, s):
        return self.long2short.get(s, s)

callback_counter = 0
def genericAcCallback(real_callback):

    @functools.wraps(real_callback)
    @callbackDecorator
    def new_f(*args):
        acsim.ac.newCallback(new_f.__name__, args)
        return real_callback(*args)

    global callback_counter
    try:
        fname = real_callback.__name__
    except AttributeError:
        try:
            fname = real_callback.func.name
        except AttributeError:
            fname = "lambdaobj"

    name = "_callback_%s_%d_" % (fname, callback_counter)
    acdebug("Registered callback %s as %s", str(real_callback), name)
    globals()[name] = new_f
    globals()[name].__name__ = name
    callback_counter += 1
    return new_f

def simulate_crappy_connection():
    import socket
    import random
    import threading

    class SocketWrapper:
        orig_socket = socket.socket
        def __init__(self, *args, **kw):
            self.pending = b''
            self.socket = self.orig_socket(*args, **kw)
            self.tracebacks = []
            self.readThreadId = None
            self.writeThreadId = None

        def _checkthread(self, threadId):
            tb = "".join(traceback.format_stack())
            if not tb in self.tracebacks:
                self.tracebacks.append(tb)
            if threadId is None:
                threadId = threading.currentThread().ident
            if threadId != threading.currentThread().ident:
                acwarning("Socket recv/send is called from multiple threads. Tracebacks: ")
                for t in self.tracebacks[::-1]:
                    acdebug("%s", t)
            return threadId

        def recv(self, l):
            self.readThreadId = self._checkthread(self.readThreadId)
            if len(self.pending) == 0:
                self.pending = self.socket.recv(l)
            r = random.randint(0,1)
            if r == 0 or len(self.pending) == 0:
                l = len(self.pending)
            else:
                l = random.randint(1,len(self.pending))
            if l < len(self.pending):
                acdebug("crappy recv %d < %d", l, len(self.pending))
            res = self.pending[:l]
            self.pending = self.pending[l:]
            return res

        def send(self, b):
            self.writeThreadId = self._checkthread(self.writeThreadId)
            r = random.randint(0,1)
            if r == 0:
                l = len(b)
            else:
                l = random.randint(1,len(b))
            if l < len(b):
                acdebug("crappy send %d < %d", l, len(b))
            return self.socket.send(b[:l])

        def sendall(self, b):
            self.writeThreadId = self._checkthread(self.writeThreadId)
            sentb = 0
            while sentb < len(b):
                sentb += self.send(b[sentb:])
            return sentb

        def __getattr__(self, a):
            return getattr(self.socket, a)

    socket.socket = SocketWrapper

dbGuidMapper = None
def guidhasher(guid):
    global dbGuidMapper
    if dbGuidMapper is None:
        import ptracker_lib.DBGuidMapper
        dbGuidMapper =  ptracker_lib.DBGuidMapper.dbGuidMapper
    if guid is None:
        return None
    if not guid.startswith("sha256#") and guid != "":
        guid_new = dbGuidMapper.raw_hash(guid)
        dbGuidMapper.register_guid_mapping(guid, guid_new)
        guid = guid_new
    return guid

if 0:
    acwarning("!!!!!!!!!!!!!!!!!!!Simulating a crappy connection!!!!!!!!!!!!!!!!!")
    try:
        simulate_crappy_connection()
    except:
        acerror(traceback.format_exc())
