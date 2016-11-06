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

import tempfile
import winsound
import wave
import audioop
from math import log, exp
import os, os.path
from threading import Thread
from ptracker_lib.helpers import *
from ptracker_lib.config import config

cleanup_temp_files = False

def tempfile_gen(suffix):
    with tempfile.TemporaryDirectory(prefix='ptracker_') as d:
        acinfo("Generated temporary directory %s", d)
        filecnt = 0
        while not cleanup_temp_files:
            res = os.path.join(d, "%d%s" % (filecnt,suffix))
            yield res
            filecnt += 1


wavTemps = None
sound_cache = {}
def playsound(filename, volume):
    if type(filename) == int:
        filename = config.sound_file_mapping[filename]
    if volume <= 0.0:
        return
    global sound_cache, wavTemps
    if wavTemps is None:
        wavTemps = tempfile_gen('.wav')
    if abs(volume - 1.) >= 0.01:
        if not (filename, volume) in sound_cache:
            tmp_filename = next(wavTemps)
            t = Thread(target=create_and_play_sound, args=(filename,volume,tmp_filename))
            t.start()
            sound_cache[(filename, volume)] = (t, tmp_filename)
            return
        cached = sound_cache[(filename,volume)]
        if type(cached) == type(()):
            t = cached[0]
            t.join(timeout=0.0)
            if not t.isAlive():
                sound_cache[(filename,volume)] = cached[1]
                cached = cached[1]
            else:
                # sound genertion still in process...
                return
        filename = cached
    winsound.PlaySound(filename, winsound.SND_FILENAME|winsound.SND_ASYNC)

def create_and_play_sound(filename,volume,tmp_filename):
    mapvol = lambda x: (1-log(1 + (1-x)*(exp(1)-1)))**3
    volume = mapvol(volume)
    f = wave.open(filename, 'rb')
    s = f.readframes(f.getnframes())
    sn = audioop.mul(s, f.getsampwidth(), volume)
    fn = wave.open(tmp_filename, 'wb')
    fn.setnchannels(f.getnchannels())
    fn.setsampwidth(f.getsampwidth())
    fn.setframerate(f.getframerate())
    fn.writeframes(sn)
    fn.close()
    f.close()
    winsound.PlaySound(tmp_filename,winsound.SND_FILENAME|winsound.SND_ASYNC)
    acinfo("Generated sound file %s", tmp_filename)

def shutdown():
    if wavTemps is None:
        return
    global cleanup_temp_files
    cleanup_temp_files = True
    try:
        next(wavTemps)
    except StopIteration:
        pass
