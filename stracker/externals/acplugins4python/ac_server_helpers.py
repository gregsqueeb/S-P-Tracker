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
Copyright (c) 2015, NeverEatYellowSnow (NEYS)
All rights reserved.

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are met:
1. Redistributions of source code must retain the above copyright
   notice, this list of conditions and the following disclaimer.
2. Redistributions in binary form must reproduce the above copyright
   notice, this list of conditions and the following disclaimer in the
   documentation and/or other materials provided with the distribution.
3. All advertising materials mentioning features or use of this software
   must display the following acknowledgement:
   This product includes software developed from NeverEatYellowSnow (NEYS).
4. Neither the name of NeverEatYellowSnow (NEYS) nor the
   names of its contributors may be used to endorse or promote products
   derived from this software without specific prior written permission.

THIS SOFTWARE IS PROVIDED BY <COPYRIGHT HOLDER> ''AS IS'' AND ANY
EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
DISCLAIMED. IN NO EVENT SHALL <COPYRIGHT HOLDER> BE LIABLE FOR ANY
DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES
(INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES;
LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND
ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
(INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
"""

import struct
import codecs

class GenericStructParser:
    def __init__(self, fmt, converter = lambda x: x):
        self.fmt = fmt
        self.converter = converter

    def get(self,b,k):
        r=struct.unpack_from(self.fmt,b,k)
        if len(r) == 1:
            r = r[0]
        return self.converter(r),k+struct.calcsize(self.fmt)

    def put(self,v):
        try:
            v[0]
        except:
            v = [v]
        return struct.pack(self.fmt,*v)

    def size(self):
        return struct.calcsize(self.fmt)

class GenericArrayParser:
    def __init__(self, lFmt, eSize, decode, encode):
        self.lFmt = lFmt
        self.eSize = eSize
        self.decode = decode
        self.encode = encode

    def get(self,b,k):
        l,=struct.unpack_from(self.lFmt,b,k)
        k += struct.calcsize(self.lFmt)
        nk = k+self.eSize*l
        raw = b[k:nk]
        return self.decode(raw),nk

    def put(self,v):
        raw = self.encode(v)
        l = len(raw)//self.eSize
        return struct.pack(self.lFmt,l) + raw

    def size(self):
        raise NotImplementedError

Uint8 = GenericStructParser('B')
Bool = GenericStructParser('B', lambda x: x != 0)
Uint16 = GenericStructParser('H')
Int16 = GenericStructParser('h')
Uint32 = GenericStructParser('I')
Int32 = GenericStructParser('i')
Float = GenericStructParser('f')
Vector3f = GenericStructParser('fff')
Ascii = GenericArrayParser(
    'B', 1,
    lambda x: codecs.decode(x, 'ascii', 'replace'),
    lambda x: codecs.encode(x, 'ascii', 'strict'),
)
UTF32 = GenericArrayParser(
    'B', 4,
    lambda x: codecs.decode(x, 'utf-32', 'replace'),
    lambda x: codecs.encode(x, 'utf-32', 'strict')[4:], # first 4 bytes are ignored?
)

class GenericPacket:
    def __init__(self, **kw):
        if len(kw):
            for f,p in self._content:
                setattr(self, f, kw[f])

    def from_buffer(self, buffer, idx):
        for f,p in self._content:
            try:
                r,idx = p.get(buffer,idx)
                setattr(self,f,r)
            except Exception as exc:
                raise RuntimeError("Error while processing attribute %s: %s" % (f, str(exc)))
        return idx,self

    def to_buffer(self):
        res = struct.pack('B', self.packetId)
        for f,p in self._content:
            res += p.put(getattr(self,f))
        return res

    def __str__(self):
        res = str(type(self)) + "("
        for f,_ in self._content:
            v = getattr(self, f, None)
            if type(v) in (tuple, list):
                v = tuple(str(x) for x in v)
            res += f + "=" + str(v) + ", "
        res += ")"
        return res

    def size(self):
        s = 0
        for f,p in self._content:
            s += p.size()
        return s

class DictToClass:
    def __init__(self, **kw):
        for k in kw:
            setattr(self, k, kw[k])