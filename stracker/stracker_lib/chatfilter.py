
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

import re
from ptracker_lib.helpers import *
from stracker_lib.config import config

bad_words = []

def extend_spaces(w):
    res = ""
    for c in w:
        res += c + " "
    return res.strip()

def init():
    sfile = config.SWEAR_FILTER.swear_file
    try:
        c = 0
        for l in open(sfile).readlines():
            w = l.strip().lower()
            if w != "":
                bad_words.append(w)
                bad_words.append(extend_spaces(w))
            c += 1
        acinfo("Added %d words to swear filter.", c)
    except OSError as e:
        acerror("Cannot read file with bad words (%s): %s", sfile, str(e))

def subst(n, r, text):
    c = 0
    while 1:
        text, count1 = re.subn(r'([a-z_]+)'+n, r'\1'+r, text)
        text, count2 = re.subn(n+r'([a-z_]+)', r+r'\1', text)
        if count1 + count2 == 0:
            break
        c += count1 + count2
    return text, c

def isbad(text):
    substitutions = {
        "4" : "a",
        "1" : "i",
        "3" : "e",
        "7" : "t",
        "5" : "s",
        "0" : "o",
    }
    # subst multiple whitespaces with a single space
    text = re.sub(r'\W+', ' ', text).lower()
    while 1:
        c = 0
        for s in substitutions.keys():
            text, count = subst(s, substitutions[s], text)
            c += count
        if c == 0:
            break
    for w in bad_words:
        if re.search(r'\b' + w + r'\b', text) != None:
            return True
    return False

init()
