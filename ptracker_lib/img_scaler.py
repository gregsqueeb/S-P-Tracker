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

import array
import os
import os.path
import shutil
import tempfile
from ptracker_lib.helpers import *
from ptracker_lib import png

dimcache = {}
filecache = {}

cleanup_temp_files = False

def tempfile_gen(suffix):
    with tempfile.TemporaryDirectory(prefix='ptracker_') as d:
        acinfo("Generated temporary directory %s", d)
        filecnt = 0
        while not cleanup_temp_files:
            res = os.path.join(d, "%d%s" % (filecnt,suffix))
            yield res
            filecnt += 1

pngTemps = tempfile_gen('.png')

def getTempFileName():
    return next(pngTemps)

def shutdown():
    global cleanup_temp_files
    cleanup_temp_files = True
    try:
        next(pngTemps)
    except StopIteration:
        pass

def scaleImg(filename, newWidth, newHeight, maxAlpha):

    if filename in dimcache:
        oldWidth, oldHeight = dimcache[filename]
        if oldWidth == 1:
            newWidth = 1
        if oldHeight == 1:
            newHeight = 1

    cachekey = (filename, newWidth, newHeight, maxAlpha)

    if not cachekey in filecache:

        rgba = png.Reader(filename).asRGBA8()
        oldWidth = rgba[0]
        oldHeight = rgba[1]
        op = tuple(rgba[2])
        channels = rgba[3]['planes']
        aMax = int(maxAlpha*255)
        dimcache[filename] = (oldWidth, oldHeight)

        #acinfo("Scaling image %s (%d,%d) -> (%d,%d)", filename, oldWidth, oldHeight, newWidth, newHeight)

        # handle oldWidth / oldHeight = 1 case:
        if oldWidth == 1:
            newWidth = 1
        if oldHeight == 1:
            newHeight = 1

        np = [array.array('B') for h in range(newHeight)]
        rowbytes = b" "*(channels*newWidth)
        for r in np: r.frombytes(rowbytes)
        if newHeight == oldHeight and newWidth == oldWidth:
            for y in range(newHeight):
                np[y][:] = array.array('B', op[y][:])
                np[y][3::4] = array.array('B', [min(alpha, aMax) for alpha in op[y][3::4]])
        else:
            # bilinear interpolation
            factorx = oldWidth / newWidth
            factory = oldHeight / newHeight

            # precomputed values depending on x
            ox = [x*factorx for x in range(newWidth)]
            ox0 = [int(o) for o in ox]
            ox1 = [o+1 for o in ox0]
            dx = [ox[i]-ox0[i] for i in range(newWidth)]
            ox1= [min(o, oldWidth-1) for o in ox1]
            sx11 = [ox0[i]*channels for i in range(newWidth)]
            sx12 = [start + channels for start in sx11]
            sx21 = [ox1[i]*channels for i in range(newWidth)]
            sx22 = [start + channels for start in sx21]

            for y in range(newHeight):
                oy = y*factory
                oy0 = int(oy)
                oy1 = oy0+1
                dy = oy-oy0
                oy1 = min(oy1, oldHeight-1)
                for x in range(newWidth):
                    o11 = op[oy0][sx11[x]:sx12[x]]
                    o12 = op[oy0][sx21[x]:sx22[x]]
                    o21 = op[oy1][sx11[x]:sx12[x]]
                    o22 = op[oy1][sx21[x]:sx22[x]]

                    # (o11 * (1-dx) + o12 * dx) * (1-dy) + (o21 * (1-dx) + o22 * dx) * dy
                    # o11 - o11*dx + o12 * dx - o11*dy + o11*dx*dy - o12*dx*dy + o21*dy - o21*dx*dy + o22*dx*dy
                    # o11 + dy*(o21 - o11) + dx*(o12 - o11) + dx*dy*(o11 - o12 - o21 + o22)

                    o = [round(o11[i] +
                               dy   *(o21[i]-o11[i]) +
                               dx[x]*((o12[i]-o11[i]) +
                                      dy*(o11[i]-o12[i]-o21[i]+o22[i]))) for i in range(channels)]

                    #o1 = [o11[i]*(1.-dx[x]) + o12[i]*dx[x] for i in range(channels)]
                    #o2 = [o21[i]*(1.-dx[x]) + o22[i]*dx[x] for i in range(channels)]
                    #o = [round(o1[i]*(1.-dy) + o2[i]*dy) for i in range(channels)]

                    o[-1] = min(o[-1], aMax)
                    np[y][(x*channels):((x+1)*channels)] = array.array('B',o)

        #newWidth=oldWidth
        #newHeight=oldHeight
        #np = op
        w = png.Writer(width=newWidth,
                       height=newHeight,
                       alpha=rgba[3]['alpha'],
                       planes=rgba[3]['planes'])
        filename = getTempFileName()
        png.from_array(np, 'RGBA').save(filename)
        #outfile = open(filename, "wb")
        #w.write(outfile, np)
        #outfile.close()

        filecache[cachekey] = filename

    return filecache[cachekey]

if __name__ == "__main__":
    os.chdir(r"C:\Program Files (x86)\Steam\SteamApps\common\assettocorsa")
    scaleImg(r"C:\Program Files (x86)\Steam\SteamApps\common\assettocorsa\apps\python\ptracker\images\rounded_frame\rounded_frame_uc.png",
             1, 5, 0.3)