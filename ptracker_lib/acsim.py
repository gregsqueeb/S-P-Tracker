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
import pickle
import datetime
import os.path
import os
import importlib
import traceback
import sys
import gzip
import struct

ONLINE = 0
OFFLINE = 1

class Frame:
    def __init__(self, callback, args):
        self.function_calls = {}
        self.callback = callback
        self.args = args

try:
    import ac as acorig

    class WrapperFunc:
        def __init__(self, module, funcName, parent):
            self.funcName = funcName
            self.parent = parent
            self.module = module

        def __call__(self, *args, **kw):
            kw = {}
            if len(kw) == 0:
                r = self.module.__dict__[self.funcName](*args)
                self.parent.logCall(self.funcName, args, {}, r)
            else:
                r = self.module.__dict__[self.funcName](*args, **kw)
                self.parent.logCall(self.funcName, args, kw, r)
            if self.funcName == "addRenderCallback":
                acorig.log("called %s(%s, %s) -> %s" % (self.funcName, args, kw, r))
            return r

    def DirectFunc(module, funcName, parent):
        return module.__dict__[funcName]

    class AC:
        def __init__(self):
            self.frames = [Frame("acMain", [])]
            script_file = os.path.realpath(__file__)
            script_dir = os.path.dirname(script_file)
            logfilename = os.path.join(script_dir, "..", "recs", datetime.datetime.utcnow().strftime('%Y%m%d_%H%M%S') + ".callog")
            try:
                self.file = gzip.open(logfilename, "wb")
                acorig.log("ptracker/ACSIM initialized logfilename=%s" % logfilename)
                self.wrapper = WrapperFunc
            except IOError:
                logfilename = "NONE (cannot open %s)" % logfilename
                self.file = None
                self.wrapper = DirectFunc

        def __getattr__(self, attr):
            res = None
            if attr != "log" and attr in acorig.__dict__:
                res = self.wrapper(acorig, attr, self)
            else:
                for m in watched_modules:
                    if attr in m.__dict__:
                        res = self.wrapper(m, attr, self)
                        break
            if not res is None:
                self.__dict__[attr] = res
            return self.__dict__[attr]

        def log(self, *args):
            return acorig.log(*args)

        def logCall(self, funcName, args, kw, result):
            try:
                k = pickle.dumps((funcName, args, kw))
            except:
                k = pickle.dumps((funcName, None, None))
            r = pickle.dumps(result)
            self.frames[-1].function_calls[k] = r

        def newCallback(self, callback, args):
            if not self.file is None:
                s = pickle.dumps(self.frames[-1])
                l = len(s)
                self.file.write(struct.pack('i', l))
                self.file.write(s)
                self.frames[0] = Frame(callback, args)

        def save(self):
            if not self.file is None:
                self.newCallback('virtual_finish', ())
                self.file.close()
                self.file = None

        def isRecording(self):
            return not self.file is None

        def getACPid(self):
            return os.getpid()

    ac = AC()
    mode = ONLINE

except ImportError:
    # simulation mode

    class ACWrapperFunc:
        def __init__(self, funcName, parent):
            self.funcName = funcName
            self.parent = parent

        def __call__(self, *args, **kw):
            f = self.parent.frame
            try:
                k = pickle.dumps((self.funcName, args, kw))
            except:
                k = pickle.dumps((self.funcName, None, None))
            try:
                r = pickle.loads(f.function_calls[k])
            except KeyError:
                try:
                    k = pickle.dumps((self.funcName, None, None))
                    r = pickle.loads(f.function_calls[k])
                except KeyError:
                    if self.funcName in self.parent.wrappedFunctions and self.parent.wrappedFunctions[self.funcName] is None:
                        r = None
                    else:
                        if not self.parent.loggedFunctionError:
                            self.parent.loggedFunctionError = True
                            self.parent.log("ERROR did not find function %s with args %s. Returning None, but this is probably wrong." % (self.funcName, str(args)))
                        r = None
            return r

    class AC:
        def __init__(self, filename, loopTo = None):
            try:
                self.file = gzip.open(filename, 'rb')
            except:
                self.file = None
            self.frame = None
            self.module = None
            self.loggedFunctionError = False
            self.loopTo = loopTo

        def readExactBytes(self, n):
            r = self.file.read(n)
            while len(r) < n:
                t = self.file.read(n-len(r))
                if len(t) == 0:
                    return r
                r += t
            return r

        def readNextFrame(self):
            self.wrappedFunctions = {}
            l = self.readExactBytes(4)
            if len(l) == 0:
                self.frame = None
                return
            l = struct.unpack('i', l)[0]
            s = self.readExactBytes(l)
            self.frame = pickle.loads(s)
            for k in self.frame.function_calls:
                funcName, args, kw = pickle.loads(k)
                res = pickle.loads(self.frame.function_calls[k])
                self.wrappedFunctions[funcName] = res

        def newCallback(self, callback, args):
            pass

        def __getattr__(self, attr):
            if attr in self.wrappedFunctions:
                return ACWrapperFunc(attr, self)
            elif attr in self.__dict__:
                return self.__dict__[attr]
            else:
                def default(*args, **kw):
                    return None
                return default

        def log(self, *args):
            for a in args:
                if not sys.stdout.encoding is None:
                    a = a.encode(sys.stdout.encoding, errors='replace')
                print(a)

        def loop(self):
            self.readNextFrame()
            frames = 0
            if not self.loopTo is None:
                self.module.__dict__[self.frame.callback](*self.frame.args)
                self.log("loop to " + expression)
                while 1:
                    frames += 1
                    if eval(expression):
                        break
                    self.readNextFrame()
                    if self.frame is None:
                        assert(0)
            self.log("ok")
            warned_functions = {}
            while 1:
                frames += 1
                try:
                    self.module.__dict__[self.frame.callback](*self.frame.args)
                except:
                    print(traceback.format_exc())
                    if not self.frame.callback in warned_functions:
                        print("Warning: %s not in %s (ignoring)" % (self.frame.callback, self.module))
                        warned_functions[self.frame.callback] = None
                self.readNextFrame()
                if self.frame is None:
                    break
                #print ("Processed %d frames" % frames)
            print("Processed %d frames" % frames)

        def save(self):
            print ("Simulation finished.")

        def isRecording(self):
            return False

        def getACPid(self):
            return os.getpid()

    if __name__ != "__main__":
        expression = None
        if len(sys.argv) == 4:
            expression = sys.argv[3]
        if len(sys.argv) >= 3:
            filename = sys.argv[2]
        else:
            filename = None
        ac = AC(filename, loopTo = expression)
    else:
        ac = None

    mode = OFFLINE

watched_modules = []

def add_watched_module(module_name):
    module = importlib.import_module(module_name)
    watched_modules.append(module)
    return ac

def offline():
    return mode == OFFLINE

def setState(self, state):
    pass

if __name__ == "__main__":
    # change to default ac working dir (assuming we are located in apps/python/<app_name>/<lib>
    os.chdir('../../../..')
    sys.path.append('apps/python/system')
    module_name = sys.argv[1]
    sys.path.append('apps/python/%s' % module_name)
    module = importlib.import_module(module_name)
    module.acsim.ac.module = module
    module.acsim.ac.loop()
