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
from threading import Thread
from queue import Queue
import traceback
import sys
import functools

# return traceback in case of exceptions, printed in the main thread
def threadCallDecorator(f):

    @functools.wraps(f)
    def new_f(*args, **kw):
        try:
            res = (None, f(*args, **kw))
            return res
        except:
            return (sys.exc_info(), None)

    return new_f

class Worker(Thread):
    def __init__(self, my_async):
        Thread.__init__(self)
        self.daemon = True
        self.queueIn = Queue()
        self.processing = 0
        self.queueOut = Queue()
        self.my_async = my_async
        if my_async:
            self.start()

    def run(self):
        #from ptracker_lib.helpers import tracer
        #sys.settrace(tracer)
        while True:
            item = self.queueIn.get()
            if item is None:
                return
            self.processing = 1
            f, args, kw, callback = item
            res = f(*args, **kw)
            self.processing = 0
            if not callback is None:
                callback(res)
            else:
                self.queueOut.put(res)

    def apply_async(self, f, args, kw, callback):
        if self.my_async:
            self.queueIn.put( (f, args, kw, callback) )
        else:
            callback(f(*args, **kw))

    def apply(self, f, args, kw):
        if self.my_async:
            self.queueIn.put( (f, args, kw, None) )
            return self.queueOut.get()
        else:
            return f(*args, **kw)

    def shutdown(self):
        self.queueIn.put( None )
        self.join()
