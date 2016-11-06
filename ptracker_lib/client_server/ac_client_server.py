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


import atexit
import os
import subprocess
import traceback

from ptracker_lib import acsim
from ptracker_lib.helpers import *
from .client_server import *

def add_ac_api(inst):
    funcs = [('setSize', 'iff', None),
             ('setTitle', ('i', inst.ARG_STRING), None),
             ('setIconPosition', 'iff', None),
             ('sendChatMessage', (inst.ARG_STRING,), None),
             ('setVisible', 'ii', None),
             ('setBackgroundOpacity', 'if', None),
             ('setPosition', 'iff', None),
             ('getPosition', 'i', inst.ARG_PICKLE),
             ('setBackgroundColor', 'iiii', None),
             ('setFontColor', 'iffff', None),
             ('setFontSize', 'if', None),
             ('setFontAlignment', ('i', inst.ARG_STRING,), None),
             ('addLabel', ('i', inst.ARG_STRING), 'i'),
             ('addButton', ('i', inst.ARG_STRING), 'i'),
             ('setText', ('i', inst.ARG_STRING,), None),
             ('setBackgroundTexture', ('i', inst.ARG_STRING,), None),
             ('addSpinner', ('i', inst.ARG_STRING), 'i'),
             ('setRange', 'iff', None),
             ('setValue', 'if', None),
             ('setStep', 'if', None),
             ('addTextInput', ('i', inst.ARG_STRING), 'i'),
             ('setFocus', 'ii', None),
             ('newApp', (inst.ARG_STRING,), 'i'),
             ('drawBorder', 'ii', None),
             ('console', (inst.ARG_STRING,), None),
             ('log', (inst.ARG_STRING,), None),
             ('addOnClickedListener', ('i', inst.ARG_CALLBACK('f', 'f')), None),
             ('addOnValueChangeListener', ('i', inst.ARG_CALLBACK(inst.ARG_PICKLE)), None),
             ('addOnValidateListener', ('i', inst.ARG_CALLBACK(inst.ARG_PICKLE, )), None),
             ('addOnChatMessageListener', ('i', inst.ARG_CALLBACK(inst.ARG_STRING, inst.ARG_STRING)), None),
             ('focusCar', ('i',), None),
            ]
    for name,args,ret in funcs:
        inst.addFunction(name, args, ret, getattr(acsim.ac, name))
    inst.addFunction('setPositionTuple', ('i', inst.ARG_PICKLE), None, lambda acid, p: acsim.ac.setPosition(acid, p[0], p[1]))
    inst.addFunction('setPositionTuple2', ('i', inst.ARG_PICKLE, inst.ARG_PICKLE), None, lambda acid, p1, p2: acsim.ac.setPosition(acid, p1[0]+p2[0], p1[1]+p2[1]))

def create_ac_client_server(server_args = None):
    server_args += [str(os.getpid()), ]
    env = os.environ.copy()
    env['PYTHONPATH'] = ""
    env['PYTHONHOME'] = ""
    env['PYTHONVERBOSE'] = ""
    env['PATH'] = ""
    acinfo("Starting server: %s", server_args)
    ptracker_server = None
    try:
        ptracker_server = subprocess.Popen(server_args,
                                           stdout=subprocess.PIPE,
                                           stderr=subprocess.STDOUT,
                                           universal_newlines=True,
                                           bufsize=65536, # 64 kB buffer should be enough to hold stderr before the redirection occurs
                                           env=env)
        c = Client(IF_SHM, "ptracker-client-server-comm", os.getpid(), 15.)
        add_ac_api(c)
        c.commit()
        c.wait(timeout=15.)
        acinfo("Successfully created client server instances!")
        return c
    except OSError as e:
        acerror("Cannot execute ptracker-server.")
        acerror("Command executed:%s", " ".join(server_args))
        acerror("Error reported: %s", e.strerror )
        acerror(traceback.format_exc())
        raise e
    except Exception as e:
        if not ptracker_server is None:
            returned = ptracker_server.poll()
            if not returned is None:
                acerror("ptracker-server process exited too early. Return value: %d", returned)
            acerror("ptracker-server stderr/stdout:")
            acerror("%s", ptracker_server.stdout.read())
        acerror(traceback.format_exc())
        raise e
