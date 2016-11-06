
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

# ac module for simulation
import sys
import os,os.path
sys.path.append(os.path.split(__file__)[0] + "/..")

class Methods:
    def __init__(self):
        pass

    def OpenKey(self, *args):
        print("OpenKey")
        pass

    def QueryValueEx(self, k, v):
        print("QueryValueEx")
        if v == "Personal":
            return [d]
        print(v, k)

    def log(self, *args):
        print(*args)

    def __getattr__(self, a, *args):
        if a == "__initializing__":
            return __initializing__
        print("getattr",a)
        return lambda *args, **kw: None

m = Methods()
sys.modules['winreg'] = m
sys.modules['ac'] = m

try:
    os.makedirs(os.path.join(d, "Assetto Corsa", "logs"))
except:
    pass
