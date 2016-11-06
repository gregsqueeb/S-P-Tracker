
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

"""
json_yield demo.

This is all in one file to keep things simple.
Starts a server listening on cherrypy default
of localhost:8080, which provides a /prime
resource exposing a Python generator.

Dependency: cherrypy

See http://codedstructure.blogspot.com/2010/12/http-streaming-from-python-generators.html

2010-12-31
Ben Bass (benbass at codedstructure dot net)
"""

import functools
import json
import uuid
import time
import traceback
from ptracker_lib.helpers import *
from stracker_lib import config

def json_yield(fn):
    """
    converts yields from request functions to JSON chunks
    sent back to sender
    """

    # each application of this decorator has its own id
    json_yield._fn_id += 1

    # put it into the local scope so our internal function
    # can use it properly
    fn_id = json_yield._fn_id

    @functools.wraps(fn)
    def _(self, key, *o, **k):
        """
        key should be unique to a session.
        Multiple overlapping calls with the same
        key should not happen (will result in
        ValueError: generator already executing)
        """
        # create generator if it hasn't already been
        if (fn_id,key) not in json_yield._gen_dict:
            new_gen = fn(self, *o, **k)
            json_yield._gen_dict[(fn_id,key)] = [new_gen, True, time.time()]
            acdebug("Streaming started.")
        try:
            _cleanup_stale_generators(json_yield._gen_dict)
            json_yield._gen_dict[(fn_id,key)][1] = True
            json_yield._gen_dict[(fn_id,key)][2] = time.time()

            # get next result from generator
            try:
                # get, assuming there is more.
                gen = json_yield._gen_dict[(fn_id, key)][0]
                content = next(gen)
                if type(content) == dict:
                    result = content
                    result.update({'state': 'ready'})
                else:
                    result = {'state': 'ready', 'content' : content}
                # send it
                return json.dumps(result)
            except StopIteration:
                # remove the generator object
                del json_yield._gen_dict[(fn_id,key)]
                # signal we are finished.
                return json.dumps({'state': 'done',
                                   'content': None})
        except:
            acdebug(traceback.format_exc())
        finally:
            try:
                json_yield._gen_dict[(fn_id,key)][1] = False
                json_yield._gen_dict[(fn_id,key)][2] = time.time()
            except:
                pass

    return _
# some function data...
json_yield._gen_dict = {}
json_yield._fn_id = 0

def _cleanup_stale_generators(d):
    t = time.time()
    for k in list(d.keys()):
        active = d[k][1]
        lastCall = d[k][2]
        if not active and t - lastCall > 5:
            del d[k]

def new_key():
    _cleanup_stale_generators(json_yield._gen_dict)
    if len(json_yield._gen_dict) >= config.config.HTTP_CONFIG.max_streaming_clients:
        raise RuntimeError("Too many streaming clients connected (%d). Try again later." % len(json_yield._gen_dict))
    return uuid.uuid4().hex
