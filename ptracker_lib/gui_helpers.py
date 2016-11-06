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

import configparser
import collections
import math
import os.path
import re
import time
import traceback
import functools
import sys
import struct
from threading import Thread
from ptracker_lib import acsim
from ptracker_lib.helpers import *
from ptracker_lib import img_scaler
from ptracker_lib.gui_styles import *
from ptracker_lib.client_server.client_server_impl import PendingResult

try:
    from ptracker_lib import _imagingft
except:
    acwarning("Cannot import imageingft, font size estimation will be of limited quality")
    acwarning(traceback.format_exc())
    class _imagingft:
        def getfont(font, fontsize, index, encoding, fontbytes):
            class FontEstimator:
                def __init__(self, fontsize):
                    self.fontsize = fontsize
                def getsize(self, s):
                    w = len(s)*90/len("Hello World")*self.fontsize/17
                    h = self.fontsize
                    oy = int(5/17*self.fontsize)
                    return ((int(w), int(h)), (0,oy))
            return FontEstimator(fontsize)

acfont = open(r"content\fonts\segoeui.ttf", "rb").read()

class ACFontCache:
    def __init__(self):
        self.font_cache = {}

    def widthEstimator(self, fontSize):
        if not fontSize in self.font_cache:
            def getwidth(t, font=_imagingft.getfont("", fontSize, 0, "", acfont)):
                r = font.getsize(t)
                return r[0][0]+r[1][0]
            self.font_cache[fontSize] = getwidth
        return self.font_cache[fontSize]

acFontCache = ACFontCache()

class GridLayout:
    ALIGN_TOPLEFT = 0
    ALIGN_CENTER = 1
    ALIGN_BOTTOMRIGHT = 2

    VALIGN_TOP = ALIGN_TOPLEFT
    VALIGN_CENTER = ALIGN_CENTER
    VALIGN_BOTTOM = ALIGN_BOTTOMRIGHT

    HALIGN_LEFT = ALIGN_TOPLEFT
    HALIGN_CENTER = ALIGN_CENTER
    HALIGN_RIGHT = ALIGN_BOTTOMRIGHT

    def __init__(self, x, y, width, height, gap, colWidths, rowHeights, valign, halign, marginX=0, marginY=0, expandingX=False, expandingY=False):
        # Creates a grid layout positioned at (x,y) with size (width,height).
        # The width of the columns is given in the list colWidths. One element
        # in this list is allowed to be None resulting in stretching this element
        # to get all the remaining size.
        # The height of the rows is given in the list rowHeights. One element
        # in this list is allowed to be None resulting in stretching this element
        # to get all the remaining size.
        # The gap argument specifies the space between two elements in pixel.
        # width or height or both might be None, which means autocalculation (if possible).
        self._x = x
        self._y = y
        self._marginX = marginX
        self._marginY = marginY
        self._gap = gap
        self._colWidths = colWidths
        self._rowHeights = rowHeights
        self._width = width
        self._height = height
        self._expandingX = expandingX
        self._expandingY = expandingY
        self._layout_width = width
        self._layout_height = height
        self._posX = None
        self._posY = None
        self._minElemWidths = []
        self._minElemHeights = []
        self._active = False
        self._elements = {}
        self._valign = valign
        self._halign = halign
        self._labelForBkgImg = None
        self._rowBkgElements = []
        self._colBkgElements = []
        self._parents = []
        self._updateCount = 0
        self._zoom = 1.

    def debug(self, prefix=''):
        rows = -1
        cols = -1
        for e in self._elements:
            if e[0] > rows: rows = e[0]
            if e[1] > cols: cols = e[1]
        rows += 1
        cols += 1
        acinfo("%sGridLayout(x=%d,y=%d,numx=%d,numy=%d,mx=%d,my=%d,gap=%d,lw=%s,lh=%s)", prefix,
               self._x, self._y, cols, rows,
               self._marginX, self._marginY, self._gap, self._layout_width, self._layout_height)
        acinfo("%s  posX=%s", prefix, self._posX)
        acinfo("%s  posY=%s", prefix, self._posY)
        if not self._labelForBkgImg is None:
            e = self._labelForBkgImg
            p = e.getPos()
            w = e.getWidth()
            h = e.getHeight()
            acinfo("%s  Frame -> x=%d y=%d w=%d h=%d", prefix, p[0],p[1],w,h)
        acinfo("%s  RowHeights=%s", prefix, self._rowHeights)
        acinfo("%s  ColWidths =%s", prefix, self._colWidths)
        if len(self._rowBkgElements):
            acinfo("%s  RowFrames=", prefix)
            for r,e in enumerate(self._rowBkgElements):
                if not e is None:
                    a = e.active()
                    p = e.getPos()
                    w = e.getWidth()
                    h = e.getHeight()
                    acinfo("%s    (%d) -> active=%d x=%d y=%d w=%d h=%d", prefix, r, a, p[0],p[1],w,h)
        if len(self._colBkgElements):
            acinfo("%s  ColFrames=", prefix)
            for c,e in enumerate(self._colBkgElements):
                if not e is None:
                    a = e.active()
                    p = e.getPos()
                    w = e.getWidth()
                    h = e.getHeight()
                    acinfo("%s    (%d) -> active=%d x=%d y=%d w=%d h=%d", prefix, c, a, p[0],p[1],w,h)
        for r in range(rows):
            for c in range(cols):
                if (r,c) in self._elements:
                    e = self._elements[(r,c)]
                    p = e.getPos()
                    w = e.getWidth()
                    h = e.getHeight()
                    name = getattr(e, '_ID', "unknown")
                    if e.active():
                        acinfo("%s  (%d,%d) -> name=%s x=%d y=%d w=%d h=%d", prefix, r,c,name,p[0],p[1],w,h)
                        if getattr(e, 'debug', False):
                            e.debug(prefix=prefix+'    ')
                    else:
                        acinfo("%s  (%d,%d) -> name=%s (not active)", prefix, r, c, name)

    def setBackgroundElements(self, element, rowElements = [], colElements = []):
        self._labelForBkgImg = element
        self._rowBkgElements = rowElements
        self._colBkgElements = colElements
        if not element is None:
            pos = self.getPos()
            w = self.getWidth()
            h = self.getHeight()
            self._labelForBkgImg.setPos(pos[0], pos[1])
            self._labelForBkgImg.setSize(w, h)
            self._labelForBkgImg.setActive(self._active)

    def _recalculate_min_sizes(self):
        cw = self._colWidths
        rh = self._rowHeights
        myassert((cw is None and rh is None) or (not cw is None and not rh is None))
        if cw is None and rh is None:
            cw = []
            rh = []
            for k in self._elements:
                self._elements[k]._recalculate_min_sizes()
                r,c=k
                while len(cw) <= c:
                    cw.append(0)
                while len(rh) <= r:
                    rh.append(0)
                cw[c] = max(cw[c], self._elements[k].getMinimumWidth())
                rh[r] = max(rh[r], self._elements[k].getMinimumHeight())
        self._minElemWidths = cw
        self._minElemHeights = rh

    def _recalculate_positions(self):
        if not self._active:
            return
        cw = self._minElemWidths
        rh = self._minElemHeights
        self._posX = self.grid_calc(self._x, cw, self._layout_width if not self._layout_width is None else self._width, self._gap, self._halign, self._marginX, self._expandingX)
        self._posY = self.grid_calc(self._y, rh, self._layout_height if not self._layout_height is None else self._height, self._gap, self._valign, self._marginY, self._expandingY)
        myassert (len(self._posX) == len(cw))
        myassert (len(self._posY) == len(rh))
        for k in self._elements:
            r,c = k
            e = self._elements[k]
            if (0 <= c < len(self._posX) and 0 <= r < len(self._posY)):

                cw = self._posX[c][1] - self._posX[c][0]
                rh = self._posY[r][1]-self._posY[r][0]

                if cw == 0 or rh == 0:
                    e.setActive(False)
                else:
                    if cw < 0 or rh < 0:
                        acerror("(%d %d) -> posX=%s posY=%s colWidths=%s rowHeights=%s", r,c,self._posX,self._posY,self._colWidths,self._rowHeights)
                    e.setPos(self._posX[c][0], self._posY[r][0])
                    e.setSize(cw, rh)
                    e.setActive(True)
                    if hasattr(e, "setLayoutSize"):
                        e.setLayoutSize(cw, rh)
                        e._recalculate_positions()
            else:
                e.setActive(False)
        for r in range(min(len(self._posY), len(self._rowBkgElements))):
            e = self._rowBkgElements[r]
            if e is None:
                continue
            if (len(self._posX) <= 0 or self._posX[-1][1] - self._posX[0][0] <= 0 or
                len(self._posY) <= 0 or self._posY[ r][1] - self._posY[r][0] <= 0):
                e.setActive(False)
            else:
                minMarginX, minMarginxY, optMarginX, optMarginY = e.margins()
                x0 = self._posX[0][0] - min(self._marginX, minMarginX)
                if not self._expandingX or self._layout_width is None:
                    x1 = self._posX[-1][1] + min(self._marginX, minMarginX)
                else:
                    x1 = x0 + self._layout_width - self._marginX + min(self._marginX, minMarginX)
                y0 = self._posY[r][0]
                y1 = self._posY[r][1]
                e.setPos(x0,y0)
                e.setSize(x1-x0,y1-y0)
                e.setActive(True)
        for c in range(min(len(self._posX), len(self._colBkgElements))):
            e = self._colBkgElements[c]
            if e is None:
                continue
            if (len(self._posY) <= 0 or self._posY[-1][1] - self._posY[0][0] <= 0 or
                len(self._posX) <= 0 or self._posX[ c][1] - self._posX[c][0] <= 0):
                self._colBkgElements[c].setActive(False)
            else:
                minMarginX, minMarginY, optMarginX, optMarginY = e.margins()
                y0 = self._posY[0][0] - min(self._marginY, minMarginY)
                if not self._expandingY or self._layout_height is None:
                    y1 = self._posY[-1][1] + min(self._marginY, minMarginY)
                else:
                    y1 = y0 + self._layout_height - self._marginY + min(self._marginY, minMarginY)
                x0 = self._posX[c][0]
                x1 = self._posX[c][1]
                e.setPos(x0,y0)
                e.setSize(x1-x0,y1-y0)
                e.setActive(True)
        if not self._labelForBkgImg is None:
            pos = self.getPos()
            x0 = self._posX[0][0] - self._marginX
            x1 = self._posX[-1][1] + self._marginX
            y0 = self._posY[0][0] - self._marginY
            y1 = self._posY[-1][1] + self._marginY
            self._labelForBkgImg.setPos(x0,y0)
            self._labelForBkgImg.setSize(x1-x0,y1-y0)

    def grid_calc(self, start, dimElems, dimTotal, gap, align, margin, expanding):
        # returns as an array the start and end position of one of the grid's dimensions
        numNone = sum(map(lambda x: int(x is None), dimElems + [dimTotal]))
        myassert (numNone <= 1)
        n = len(dimElems)
        sumd = sum(map(lambda x: int(not x is None) and x, dimElems))
        sumd += (len(dimElems)-1)*gap
        currP = start+margin
        res = []
        real_gap = 0
        for i,d in enumerate(dimElems):
            if not d is None:
                if d == 0:
                    res.append([currP,currP])
                else:
                    currP += real_gap
                    res.append([currP,currP+d])
                    currP += d
                    real_gap = gap
            else:
                currP += real_gap
                loc = dimTotal - sumd - 2*margin
                res.append([currP,currP+loc])
                currP += loc
                real_gap = gap

        # expand if configured to
        if expanding and type(expanding) == type([]) and not dimTotal is None:
            spaceLeft = dimTotal - (res[-1][1]-res[0][0]) - 2*margin
            myassert( len(expanding) == 1 )
            if spaceLeft > 0:
                expandingCol = expanding[0]
                res[expandingCol] = (res[expandingCol][0],res[expandingCol][1]+spaceLeft)
                for i in range(expandingCol+1,len(res)):
                    res[i][0] += spaceLeft
                    res[i][1] += spaceLeft

        # assert alignment
        if not dimTotal is None and len(res) > 0:
            if res[-1][1]-res[0][0] > dimTotal-2*margin:
                acerror("assertion:res=%s start=%s gap=%s margin=%s expanding=%s dimTotal=%s dimElems=%s", str(res), str(start), str(gap), str(margin), str(expanding), str(dimTotal), str(dimElems))
                myassert(0)

            spaceLeft = dimTotal - (res[-1][1]-res[0][0]) - 2*margin
            delta = 0
            if align == self.ALIGN_BOTTOMRIGHT:
                delta = spaceLeft
            elif align == self.ALIGN_CENTER:
                delta = spaceLeft // 2
            else:
                delta = 0
            if delta > 0:
                for r in res:
                    r[0] += delta
                    r[1] += delta

        return res

    def setPos(self, x, y):
        if x != self._x or y != self._y:
            self._x = x
            self._y = y

    def setSize(self, width, height, force = False):
        changed = False
        if width != self._width or height != self._height:
            if force or not self._width is None :
                self._width  = width
                myassert(width >= 0)
                changed = True
            if force or not self._height is None:
                self._height = height
                myassert(height >= 0)
                changed = True

    def setColWidth(self, idx, w):
        if self._colWidths[idx] != w:
            self._colWidths[idx] = w

    def updateRowHeights(self, rowHeights):
        changed = False
        for i in range(len(self._rowHeights)):
            if not rowHeights[i] is None:
                if self._rowHeights[i] != rowHeights[i]:
                    self._rowHeights[i] = rowHeights[i]
                    changed = True
        return changed

    def updateLayout(self):
        if self._active:
            myassert( len(self._parents) == 0 )
            self._recalculate_min_sizes()
            self._recalculate_positions()

    def __getitem__(self, k):
        return self._elements[k]

    def __setitem__(self, k, e):
        if self._elements.get(k, None) != e:
            self._elements[k] = e
            if hasattr(e, "setParent"):
                e.setParent(self)

    def setItems(self, items):
        for r in range(len(items)):
            row = items[r]
            for c in range(len(row)):
                self[(r,c)] = row[c]

    def setParent(self, parent):
        self._parents.append(parent)

    def setActive(self, active):
        for k in sorted(self._elements.keys()):
            r,c = k
            activeRow = self._rowHeights is None or (0 <= r < len(self._rowHeights) and self._rowHeights[r] > 0)
            activeCol = self._colWidths is None  or (0 <= c < len(self._colWidths ) and self._colWidths [c] > 0)
            if activeRow and activeCol:
                self._elements[k].setActive(active)
        if active and not self._active:
            self._active = active # make sure that the _active flag is set before calling getWidth / getHeigth
        self._active = active
        if not self._labelForBkgImg is None:
            self._labelForBkgImg.setActive(active)
        if not active:
            for e in self._rowBkgElements:
                if not e is None:
                    e.setActive(active)
            for e in self._colBkgElements:
                if not e is None:
                    e.setActive(active)

    def active(self):
        return self._active

    def getMinimumHeight(self):
        if not self._active:
            return 0
        sh = sum(self._minElemHeights)
        sg = max(sum(map(lambda x: 0 if x == 0 else 1, self._minElemHeights))-1, 0)*self._gap
        return sh + sg + self._marginY*2

    def getMinimumWidth(self):
        if not self._active:
            return 0
        sw = sum(self._minElemWidths)
        sg = max(sum(map(lambda x: 0 if x == 0 else 1, self._minElemWidths))-1, 0)*self._gap
        return sw + sg + self._marginX*2

    def getWidth(self):
        if self._expandingX and not self._layout_width is None:
            return self._layout_width
        else:
            return self.getMinimumWidth()

    def getHeight(self):
        if self._expandingY and not self._layout_height is None:
            return self._layout_height
        else:
            return self.getMinimumHeight()

    def getPos(self):
        return (self._x,self._y)

    def getRowCount(self):
        return len(self._rowHeights)

    def getColCount(self):
        return len(self._colWidths)

    def setLayoutSize(self, width, height):
        myassert(width >= 0 and height >= 0)
        changed = False
        if width != self._layout_width:
            self._layout_width = width
            changed = True
        if height != self._layout_height:
            self._layout_height = height
            changed = True

    def setMargins(self, mx, my):
        if mx != self._marginX or my != self._marginY:
            self._marginX = mx
            self._marginY = my

    def setZoom(self, zoom):
        self._zoom = zoom
        for k in self._elements.keys():
            self._elements[k].setZoom(zoom)
        for e in self._rowBkgElements:
            if not e is None:
                e.setZoom(zoom)
        for e in self._colBkgElements:
            if not e is None:
                e.setZoom(zoom)
        if not self._labelForBkgImg is None:
            self._labelForBkgImg.setZoom(zoom)

    def getZoom(self):
        return self._zoom

def Centered(x):
    l = GridLayout(0,0,None,None,0,None,None,GridLayout.VALIGN_CENTER,GridLayout.HALIGN_CENTER)
    l[(0,0)] = x
    return l

class VertSep(GridLayout):
    def __init__(self,appWindow):
        f = Frame(appWindow, seperators['vert'])
        mmx, mmy, omx, omy = f.margins()
        GridLayout.__init__(self,0,0,None,None,0,[omx],[1],GridLayout.VALIGN_TOP,GridLayout.HALIGN_CENTER,expandingY=[0], marginY=mmy)
        self.setBackgroundElements(None,[],[f])
        self.setActive(True)

class HorSep(GridLayout):
    def __init__(self,appWindow):
        f = Frame(appWindow, seperators['hor'])
        mmx, mmy, omx, omy = f.margins()
        GridLayout.__init__(self,0,0,None,None,0,[1],[omy],GridLayout.VALIGN_CENTER,GridLayout.HALIGN_LEFT,expandingX=[0], marginX=mmx)
        self.setBackgroundElements(None,[f],[])
        self.setActive(True)

lblCounter = 0
lblActiveCounter = 0

class BaseGuiElem:
    def __init__(self, ID = None, doNotHide = False, parent = None):
        global lblCounter, lblActiveCounter
        lblCounter += 1
        if not doNotHide:
            acsim.ac.setVisible(self._acl, 0)
            self._active = False
        else:
            self._active = None
        self._ID = ID
        self._currentColor = None
        self._bkgOp = 0.0
        self._pos = (0,0)
        self._size = (0,0)
        self._zoom = 1.
        self._lastSetPosArgs = None
        self._lastSetSizeArgs = None
        self._lastSetFontSizeArgs = None
        self._lastSetFontAlignmentArgs = None
        self._lastSetBackgroundColorArgs = None
        self._parent = parent
        acsim.ac.setBackgroundOpacity(self._acl, 0.0)
        #if type(self._acl) != type(0) or self._acl < 0:
        #    acwarning("acl of gui element seems to be invalid: %s", str(self._acl))
        #    #acwarning("".join(traceback.format_stack()))

    def setActive(self, active):
        global lblCounter, lblActiveCounter
        if active != self._active:
            acsim.ac.setVisible(self._acl, int(active))
            self._active = active
            if active:
                lblActiveCounter += 1
            else:
                lblActiveCounter -= 1

    def active(self):
        return self._active

    def setPos(self, *args):
        if type(args[0]) in [float,int]:
            x = args[0]
            y = args[1]
            self._pos = (x,y)
            a = (x*self._zoom, y*self._zoom)
            if a != self._lastSetPosArgs:
                self._lastSetPosArgs = a
                acsim.ac.setPosition(self._acl, *a)
        elif len(args) == 1 and type(args[0]) == PendingResult:
            assert( self._zoom == 1. )
            self._lastSetPosArgs = args[0]
            acsim.ac.setPositionTuple(self._acl, args[0])
        else:
            acwarning("setPos(.) unknown argument")
            raise NotImplementedError

        return self

    def getPos(self):
        return self._pos

    def getGlobalPos(self):
        pp = self._parent.getGlobalPos() if not self._parent is None else (0,0)
        return (self._pos[0]*self._zoom + pp[0], self._pos[1]*self._zoom + pp[1])

    def setZoom(self, zoom):
        self._zoom = zoom

    def getBoundingRect(self):
        return (self._pos[0], self._pos[1], self._size[0], self._size[1])

    def setSize(self, w, h):
        self._size = (w,h)
        a = (w*self._zoom, h*self._zoom)
        if a != self._lastSetSizeArgs:
            self._lastSetSizeArgs = a
            acsim.ac.setSize(self._acl,*a)
        self.onSizeChanged(w,h,self._zoom)
        return self

    def onSizeChanged(self, w, h, zoom):
        pass

    def getWidth(self):
        return self._size[0]

    def getHeight(self):
        return self._size[1]

    def setBackgroundColor(self, color):
        if color != self._lastSetBackgroundColorArgs:
            self._lastSetBackgroundColorArgs = color
            acsim.ac.setBackgroundColor(self._acl, *color)
        return self

    def setBackgroundOpacity(self, op):
        if op != self._bkgOp:
            self._bkgOp = op
            acsim.ac.setBackgroundOpacity(self._acl, op)
        return self

    def setFontColor(self, c):
        if c != self._currentColor:
            self._currentColor = c
            acsim.ac.setFontColor(self._acl, *c)
        return self

    def setFontSize(self, s):
        if s != self._lastSetFontSizeArgs:
            self._lastSetFontSizeArgs = s
            acsim.ac.setFontSize(self._acl, s)
        return self

    def setFontAlignment(self, a):
        if a != self._lastSetFontAlignmentArgs:
            self._lastSetFontAlignmentArgs = a
            acsim.ac.setFontAlignment(self._acl, a)
        return self

    def getAcID(self):
        return self._acl



class Label(BaseGuiElem):
    TM_CLIP = 0
    TM_ELLIPSIS = 1
    TM_NOCHECK = 2

    def __init__(self, appWindow, ID = None, acButton = False):
        self.appWindowAcID = appWindow.getAcID()
        if not acButton:
            self._acl = acsim.ac.addLabel(self.appWindowAcID, "")
        else:
            self._acl = acsim.ac.addButton(self.appWindowAcID, "")
        self._text = ""
        self._maxTextLength = None
        self._textLengthMode = Label.TM_ELLIPSIS
        self._imgpath = None
        self._fontSize = None
        self._enabledDisabledIcons = None
        self._enabled = True
        self._click_callback = None
        self._registered_click_callback = False
        self._lastSetTextArgs = None
        self._lastClickArg = None
        acsim.ac.setText(self._acl, "")
        BaseGuiElem.__init__(self, ID, parent=appWindow)
        self.setFontSize(14)

    def setMaxTextLength(self, maxTextLength):
        self._maxTextLength = maxTextLength
        self._redisplay()
        return self

    def setTextLengthMode(self, mode):
        self._textLengthMode = mode
        self._redisplay()
        return self

    def _redisplay(self):
        if self._textLengthMode == Label.TM_ELLIPSIS:
            text = self.ellipsis(self._text)
        elif self._textLengthMode == Label.TM_CLIP:
            text = self.clip(self._text)
        else:
            text = self._text
        if text != self._lastSetTextArgs:
            self._lastSetTextArgs = text
            acsim.ac.setText(self._acl, text)

    def setText(self, text):
        text = str(text)
        if text != self._text:
            self._text = text
            self._redisplay()
        return self

    def getText(self):
        return self._text

    def ellipsis(self, text):
        return self.assertTextLength(text, "...")

    def clip(self, text):
        return self.assertTextLength(text, "")

    def split(self, text, atWS = True):
        res = []
        if atWS:
            text = text.strip()
        while len(text) > 0:
            clipped = self.clip(text)
            if atWS and len(clipped) != len(text):
                p = clipped.rfind(" ")
                if p > 0:
                    clipped = clipped[:p]
            res.append(clipped)
            text = text[len(clipped):]
            if atWS:
                text = text.strip()
        return res

    def assertTextLength(self, text, signalStr):
        if not self._maxTextLength is None:
            if len(text) > self._maxTextLength:
                el = min(self._maxTextLength, len(signalStr))
                tl = self._maxTextLength - el
                res = text[:tl] + signalStr[:el]
            else:
                res = text
            return res
        w = self.getBoundingRect()[2]
        getw = acFontCache.widthEstimator(self._fontSize)
        if getw(text) <= w:
            return text
        tW = getw(text[:3]+signalStr)
        if  tW > w:
            apstr = ""
            fitW = 0
        else:
            apstr = signalStr
            fitW = tW
        fitL = 0
        fitW = 0
        nonFitL = len(text)
        nonFitW = w
        while fitL < nonFitL - 1:
            tL = (fitL + nonFitL)//2
            tW = getw(text[:tL]+apstr)
            if tW <= w:
                fitL = tL
                fitW = tW
            else:
                nonFitL = tL
                nonFitW = tW
        res = text[:fitL]+apstr
        return res

    def clickCallbackWrapper(self, x, y):
        if self._enabled and self._active:
            self._lastClickArg = (x/self._zoom,y/self._zoom)
            self._click_callback(*self._lastClickArg)

    def getLastClickPos(self):
        return self._lastClickArg

    def setClickEventHandler(self, callback):
        if not self._registered_click_callback:
            self._registered_click_callback = True
            acsim.ac.addOnClickedListener(self.getAcID(), genericAcCallback(self.clickCallbackWrapper))
        self._click_callback = callback
        return self

    def hide(self):
        return self.setBackgroundOpacity(0.0).setText("").setBackgroundImage(None)

    def setBackgroundImage(self, imgpath):
        if self._imgpath != imgpath:
            self._imgpath = imgpath
            if imgpath is None:
                acsim.ac.setBackgroundTexture(self._acl, transparentIcon)
            else:
                acsim.ac.setBackgroundTexture(self._acl, imgpath)
        return self

    def setFontSize(self, fs):
        self._fontSize = fs
        return BaseGuiElem.setFontSize(self, fs*self._zoom)

    def setZoom(self, zoom):
        BaseGuiElem.setZoom(self, zoom)
        self.setFontSize(self._fontSize)

    def setSize(self, w, h):
        res = BaseGuiElem.setSize(self, w, h)
        self._redisplay()
        return res

    def setEnabledDisabledIcons(self, iconDisabled, iconEnabled):
        if not iconEnabled is None and not iconDisabled is None:
            self._enabledDisabledIcons = [iconEnabled, iconDisabled]
        else:
            self._enabledDisabledIcons = None
        return self

    def setEnabled(self, v):
        if v != self._enabled:
            self._enabled = v
            if not self._enabledDisabledIcons is None:
                self.setBackgroundImage(self._enabledDisabledIcons[v])
        return self

Button = Label

class Spinner(BaseGuiElem):
    def __init__(self, appWindow, currVal, minVal, maxVal, stepSize, ID = None):
        self._acl = acsim.ac.addSpinner(appWindow.getAcID(), "")
        self.value = currVal
        acsim.ac.setRange(self._acl, minVal, maxVal)
        acsim.ac.setValue(self._acl, currVal)
        acsim.ac.setStep(self._acl, stepSize)
        BaseGuiElem.__init__(self, ID, parent=appWindow)
        self.setFontSize(14)
        self.callbacks = []
        acsim.ac.addOnValueChangeListener(self._acl, genericAcCallback(self._newValueCallback))

    def setValue(self, value):
        if value != self.value:
            self.value = value
            for c in self.callbacks:
                c(value)
        acsim.ac.setValue(self._acl, value)
        return self

    def _newValueCallback(self, value):
        if value != self.value:
            self.value = value
            for c in self.callbacks:
                c(value)

    def addOnValueChangeListener(self, callback):
        self.callbacks.append(callback)
        return self

    def setFontSize(self, fs):
        self._fontSize = fs
        return BaseGuiElem.setFontSize(self, fs*self._zoom)

    def setZoom(self, zoom):
        BaseGuiElem.setZoom(self, zoom)
        self.setFontSize(self._fontSize)


class LineEdit(BaseGuiElem):
    def __init__(self, appWindow, ID = None):
        self._acl = acsim.ac.addTextInput(appWindow.getAcID(), "")
        BaseGuiElem.__init__(self, ID, parent=appWindow)
        self.setFontSize(14)

    def addOnValueChangeListener(self, callback):
        acsim.ac.addOnValidateListener(self._acl,genericAcCallback(callback))
        return self

    def setFocus(self, focusEnabled):
        ret = acsim.ac.setFocus(self._acl, focusEnabled)
        return self

    def setText(self, text):
        acsim.ac.setText(self._acl, text)
        return self

    def setValue(self, value):
        return self.setText(value)

    def setFontSize(self, fs):
        self._fontSize = fs
        return BaseGuiElem.setFontSize(self, fs*self._zoom)

    def setZoom(self, zoom):
        BaseGuiElem.setZoom(self, zoom)
        self.setFontSize(self._fontSize)

class EnumSelector(Button):
    def __init__(self, appWindow, enumValues, initValue = 0, ID = None, images=None, userChange=True):
        Label.__init__(self, appWindow, ID)
        self.enumValues = enumValues
        self._state = None
        self._images = images
        if userChange:
            self.setClickEventHandler(genericAcCallback(self.clicked))
        self.onValueChange = []
        self.setValue(initValue)

    def addOnValueChangeListener(self, callback):
        self.onValueChange.append(callback)
        return self

    def setValue(self, v):
        try:
            self.enumValues[v]
        except TypeError:
            try:
                v = self.enumValues.index(v)
            except ValueError:
                v = 0
        if v != self._state:
            self._state = v
            for f in self.onValueChange: f(self._state)
            self.setText(self.enumValues[self._state])
            if not self._images is None:
                self.setBackgroundImage(self._images[self._state])
        return self

    def getValue(self):
        return self._state

    def clicked(self, *args):
        newstate = self._state + 1
        if newstate == len(self.enumValues): newstate = 0
        return self.setValue(newstate)

CheckBox = functools.partial(EnumSelector, enumValues = ["no", "yes"])

class MultiSelector(GridLayout):
    def __init__(self, appWindow, values, enabled, width, height, color_label, color_control, color_control_highlight, bkgOp):
        n = len(values)
        GridLayout.__init__(self, 0, 0, None, None, 2, [width]*len(values), [height]*2, GridLayout.VALIGN_TOP, GridLayout.HALIGN_LEFT)
        self._values = values
        self._enabled = enabled
        self._color_label = color_label
        self._color_control = color_control
        self._color_control_highlight = color_control_highlight
        self._textMapping = {0 : "no", 1 : "yes"}
        self._callbacks = []
        for i in range(n):
            self[(0,i)] = Label(appWindow).setText(values[i]).setBackgroundOpacity(bkgOp).setFontColor(self._color_label)
            self[(1,i)] = (Button(appWindow).setText(self._textMapping[int(enabled[i])]).setBackgroundOpacity(bkgOp).
                             setFontColor(self._color_control).setClickEventHandler(functools.partial(self.changeValue, index=i)))

    def addOnValueChangeListener(self, callback):
        self._callbacks.append(callback)
        return self

    def changeValue(self, a1, a2, index):
        self._enabled[index] = not self._enabled[index]
        self[(1,index)].setText(self._textMapping[int(self._enabled[index])])
        for f in self._callbacks:
            f(self._enabled)

class AppWindow(BaseGuiElem):
    def __init__(self, acID=None, ID=None, doNotHide=None):
        if not acID is None:
            self._acl = acID
            if doNotHide is None:
                doNotHide = True
        else:
            myassert(not ID is None)
            self._acl = acsim.ac.newApp(ID)
            acsim.ac.setSize(self._acl, 1, 1)
            if doNotHide is None:
                doNotHide = False
        BaseGuiElem.__init__(self, ID, doNotHide=doNotHide)
        self.lastRendering = 0.0
        acsim.ac.addRenderCallback(self._acl, genericAcCallback(self.render))
        self.renderCallbacks = []
        self.activateCallback = None
        self.deactivateCallback = None
        self.checkActiveThread = None
        self.deactivationTime = time.time()
        self.autoCloseSeconds = None
        self._trackedPos = (0,0)
        self._trackedPosHelp = acsim.ac.getPosition(self._acl)

    def setClickEventHandler(self, callback):
        acsim.ac.addOnClickedListener(self._acl, genericAcCallback(callback))
        return self

    def setActivateCallback(self, callback):
        self.activateCallback = callback
        return self

    def setDeactivateCallback(self, callback):
        self.deactivateCallback = callback
        if not callback is None:
            self.checkActiveThread = Thread(target=self.checkActive, daemon=True)
            self.checkActiveThread.start()

    def addRenderCallback(self, callback):
        self.renderCallbacks.append(callback)
        return self

    def renderingActive(self):
        return time.time() - self.lastRendering < 1.

    def render(self, *args):
        if not self._active and self.deactivationTime - time.time() > 1.:
            BaseGuiElem.setActive(self, True)
            acdebug("SetActive(%s->TRUE)", self._ID)
        ctime = time.time()
        if not self.activateCallback is None and ctime - self.lastRendering > 2.0:
            self.activateCallback()
        if not self.autoCloseSeconds is None:
            self.autoCloseSeconds -= ctime - self.lastRendering
            if self.autoCloseSeconds < 0:
                self.autoCloseSeconds = None
                self.setActive(False)
        try:
            self._trackedPos = self._trackedPosHelp()
            self._trackedPosHelp = acsim.ac.getPosition(self._acl)
        except RuntimeError:
            acdebug("type error while tracking app position: %s", traceback.format_exc())
        self.lastRendering = ctime
        acsim.ac.setBackgroundOpacity(self._acl, self._bkgOp)
        acsim.ac.drawBorder(self._acl, 0)
        for c in self.renderCallbacks: c(*args)

    def setActive(self, active, autoCloseSeconds = None):
        # check rendering activity
        if active and self._active and time.time() - self.lastRendering > 1.:
            # make sure that the state of the element is reset to false
            BaseGuiElem.setActive(self, False)
        if active:
            self.autoCloseSeconds = autoCloseSeconds
            self.lastRendering = time.time()
        if not active:
            self.deactivationTime = time.time()
        return BaseGuiElem.setActive(self, active)

    def hideACElements(self):
        acsim.ac.setTitle(self._acl, "")
        acsim.ac.setIconPosition(self._acl, 0, -9000)

    def getPos(self):
        # app windows might be moved by the user -> we need to query the position from AC
        return self._trackedPos

    def getGlobalPos(self):
        return self._trackedPos

# list box is not working as documented, the _acl returned is always -1 :-(
class ListBox(BaseGuiElem):
    def __init__(self, appWindow, ID = None):
        self._acl = acsim.ac.addListBox(appWindow.getAcID())
        acsim.ac.setAllowMultiSelection(self._acl, 0)
        self.lbIdToItemId = {}
        self.itemIdToLbId = {}
        self.autoId = 0
        self.itemNumberPerPage = None
        self.selectionCallbacks = []
        BaseGuiElem.__init__(self, ID, parent=appWindow)
        acsim.ac.addOnListBoxSelectionListener(self._acl, genericAcCallback(self.selectionListener))
        acsim.ac.addOnListBoxDeselectionListener(self._acl, genericAcCallback(self.selectionListener))
        self.setItemNumberPerPage(10)

    def selectionListener(self, *args):
        selItems = acsim.ac.getSelectedItems(self._acl)
        if type(selItems) == type([]):
            if len(selItems) == 0:
                selected = None
            else:
                lbId = selItems[0]
                selected = self.lbIdToItemId[lbId]
            for c in self.selectionCallbacks:
                c(selected)
        return self

    def idToName(self, itemId):
        return self.itemIdToLbId.get(itemId,(None,None))[1]

    def setItemNumberPerPage(self, n):
        if self.itemNumberPerPage != n:
            self.itemNumberPerPage = n
            acsim.ac.setItemNumberPerPage(self._acl, n)
        return self

    def addItem(self, name, itemId=None):
        if itemId is None:
            while self.autoId in self.itemIdToLbId:
                self.autoId += 1
            itemId = self.autoId
        lbId = acsim.ac.addItem(self._acl, name)
        if lbId >= 0:
            self.lbIdToItemId[lbId] = itemId
            self.itemIdToLbId[itemId] = (lbId, name)
        return itemId

    def removeItem(self, itemId):
        if itemId in self.itemIdToLbId:
            lbId = self.itemIdToLbId[itemId][0]
            acsim.ac.removeItem(self._acl, lbId)
            del self.itemIdToLbId[itemId]
            del self.lbIdToItemId[lbId]

    def clear(self):
        itemIds = list(self.itemIdToLbId.keys())
        for itemId in itemIds:
            self.removeItem(itemId)

    def addCallback(self, c):
        self.selectionCallbacks.append(c)
        return self

class HorizontalPane(GridLayout):

    def __init__(self, contents, text, changeCallback, appWindow, button_width, button_height, buttonBkgOp, buttonColor, useFrame = True):
        self._paneShown = False
        if useFrame:
            frame = Frame(appWindow, tabviewStyles['content'])
            minMargX,minMargY,optMargX,optMargY = frame.margins()
        else:
            frame = None
            minMargX = minMargY = optMargX = optMargY = 0
        GridLayout.__init__(self, 0, 0, None, None, 4, None, None, GridLayout.VALIGN_TOP, GridLayout.HALIGN_LEFT, marginX=optMargY, marginY=optMargY)
        self._paneButton = Button(appWindow).setBackgroundImage(paneIcons['closed']).setClickEventHandler(self.paneButtonClicked)
        self._paneLabel = Label(appWindow).setText('%s'%text).setClickEventHandler(self.paneButtonClicked).setFontColor(buttonColor)
        self._pane_ly = GridLayout(0, 0, None, None, 4, [button_height, button_width], [button_height], GridLayout.VALIGN_TOP, GridLayout.HALIGN_LEFT)
        self._pane_ly[(0,0)] = self._paneButton
        self._pane_ly[(0,1)] = self._paneLabel
        self.setBackgroundElements(frame)
        self._changeCallback = changeCallback
        self._contents = contents
        self._text = text
        self.setPaneVisible(self._paneShown)

    def setPaneVisible(self, visible):
        self.setActive(False)
        self._elements.clear()
        self[(0,0)] = self._pane_ly
        if visible:
            self[(0,1)] = self._contents
            self._paneButton.setBackgroundImage(paneIcons['opened'])
        else:
            self._paneButton.setBackgroundImage(paneIcons['closed'])

    def paneButtonClicked(self, *args):
        self._paneShown = not self._paneShown
        self.setPaneVisible(self._paneShown)
        if self._changeCallback: self._changeCallback()

class GenericTableDisplay:
    def __init__(self, appWindow, colToNameMappings):
        self._appWindow = appWindow
        self._colToNameMappings = colToNameMappings
        self._numCols = 0
        self._numRows = 0
        self._labels = {}
        self.getColSize = lambda name: (name[-1] != "]" and 1) or int(re.search(r"\[([0-9]+)\]", name).group(1))
        self.resetMapping()
        self.callbacks = []

    def resetMapping(self):
        names = set()
        for mapping in self._colToNameMappings:
            self._numCols = max(self._numCols, self.getMappingNCols(mapping))
            for name in mapping:
                a = name.split("[")[0]
                myassert(not a in names)
                names.add(a)
                setattr(self, a, [])

    def addClickCallback(self, callback):
        if len(self.callbacks) == 0:
            for c in self._labels:
                l = self._labels[c]
                l.setClickEventHandler(functools.partial(self.internalCallback, coord=c))
        self.callbacks.append(callback)

    def setAllInactive(self):
        for c in self._labels: self._labels[c].setActive(False)

    def getMappingNCols(self, mapping):
        n = 0
        for name in mapping:
            n += self.getColSize(name)
        return n

    def getNumRows(self):
        return self._numRows

    def getLabel(self, row, col):
        return self._labels.get((row,col), None)

    def expand(self, n):
        if n > self._numRows:
            for r in range(self._numRows, n):
                for c in range(self._numCols):
                    self._labels[(r,c)] = Label(self._appWindow, 'pos %d,%d'%(r,c))
                for mapping in self._colToNameMappings:
                    c = 0
                    for name in mapping:
                        s = self.getColSize(name)
                        if s == 1:
                            getattr(self, name).append(self._labels[(r,c)])
                            c += 1
                        else:
                            a = []
                            for i in range(s):
                                a.append(self._labels[(r,c)])
                                c += 1
                            getattr(self, name.split("[")[0]).append(a)
            self._numRows = n
        for r in range(n):
            for c in range(self._numCols):
                if len(self.callbacks) > 0:
                    self._labels[(r,c)].setClickEventHandler(functools.partial(self.internalCallback, coord=(r,c)))

    def internalCallback(self, a1, a2, coord):
        r,c = coord
        for callback in self.callbacks:
            callback(r,c)

class TableView(GridLayout):
    def __init__(self, appWindow, columnDefinition, rowHeight, numRows, rowGap):
        self.table = GenericTableDisplay(appWindow, [["lblItem%d"%i for i in range(len(columnDefinition))]])
        self.rowToItemId = {}
        self.colDef = columnDefinition
        self.rowHeight = rowHeight
        self.numRows = numRows
        self.items = collections.OrderedDict()
        self.autoId = 0
        self.pageOffset = 0
        self.colorHeader = (1.0, 1.0, 1.0, 1.0)
        self.colorItem = (0.6, 0.6, 0.6, 1.0)
        self.colorActiveButton = (1.0, 1.0, 0.0, 1.0)
        self.colorInactiveButton = (0.6, 0.6, 0.6, 1.0)
        self.fontSize = 16
        self.backgroundOpacity = 0.0
        self.bkgOpacity = 0.3
        self.itemClickCallback = None
        colWidths = list(map(lambda x: x['width'], self.colDef))
        GridLayout.__init__(self, 0, 0, None, None, rowGap, colWidths, [self.rowHeight]*self.numRows, GridLayout.VALIGN_TOP, GridLayout.HALIGN_LEFT)
        self.resetLayout()
        self.table.addClickCallback(self.clicked)

    def setStyle(self, **kw):
        for a in ['colorHeader', 'colorItem', 'colorActiveButton', 'colorInactiveButton', 'fontSize', 'backgroundOpacity']:
            if a in kw:
                setattr(self, a, kw[a])
        return self

    def clicked(self, r, c):
        if self.itemClickCallback and r in self.rowToItemId:
            self.itemClickCallback(self.rowToItemId[r], c)
        elif r == self.rowUp:
            self.pageOffset -= 1
            self.update()
        elif r == self.rowDown:
            self.pageOffset += 1
            self.update()

    def setItemClickedCallback(self, c):
        self.itemClickCallback = c
        return self

    def resetLayout(self):
        self.table.expand(self.numRows)
        for r in range(self.numRows):
            for c in range(len(self.colDef)):
                self[(r,c)] = getattr(self.table, "lblItem%d" % c)[r]
        self.update()
        return self

    def addItem(self, cols, itemId = None):
        if itemId is None:
            while self.autoId in self.items:
                self.autoId += 1
            itemId = self.autoId
        else:
            myassert(not itemId in self.items)
        self.items[itemId] = cols
        self.update()
        return itemId

    def getItem(self, itemId):
        return self.items[itemId]

    def clear(self):
        self.items = collections.OrderedDict()
        self.update()
        return self

    def update(self):
        self.rowToItemId = {}
        self.rowUp = None
        self.rowDown = None
        header = list(map(lambda x: x.get('header', None), self.colDef))
        maxTextLength = list(map(lambda x: x.get('maxTextLength', None), self.colDef))
        nRows = self.numRows
        r = 0
        if not None in header:
            nRows -= 1
            for c in range(len(self.colDef)):
                cd = self.colDef[c]
                color = cd['headerColor'] if 'headerColor' in cd else self.colorHeader
                self[(r,c)].setText(header[c]).setFontColor(color).setFontSize(self.fontSize)
            r += 1
        if len(self.items) > nRows:
            nRows -= 2
            for c in range(len(self.colDef)):
                if self.pageOffset > 0:
                    color = self.colorActiveButton
                    self.rowUp = r
                else:
                    color = self.colorInactiveButton
                text = "(up)" if c == 0 else ""
                self[(r,c)].setText(text).setFontColor(color).setFontSize(self.fontSize)

                if self.pageOffset < len(self.items)-nRows:
                    color = self.colorActiveButton
                    self.rowDown = self.numRows-1
                else:
                    color = self.colorInactiveButton
                text = "(down)" if c == 0 else ""
                self[(self.numRows-1,c)].setText(text).setFontColor(color).setFontSize(self.fontSize)
            r += 1
        keys = list(self.items.keys())
        for cntR in range(nRows):
            kidx = cntR+self.pageOffset
            if 0 <= kidx < len(keys):
                itemId = keys[kidx]
                cols = self.items[itemId]
                self.rowToItemId[r+cntR] = itemId
                for c in range(len(self.colDef)):
                    item = cols[c]
                    if type(item) == type(""):
                        text = item
                        color = self.colorItem
                    else:
                        text = item['text']
                        color = item['color']
                    self[(r+cntR, c)].setText(text).setFontColor(color).setFontSize(self.fontSize).setMaxTextLength(maxTextLength[c])
            else:
                for c in range(len(self.colDef)):
                    self[(r+cntR, c)].setText("").setFontSize(self.fontSize)

class Frame:
    def __init__(self, appWindow, ini_file = None):
        self._labels = {}
        for y in ['u','c','l']:
            for x in ['l','c','r']:
                l = Label(appWindow)
                self._labels[(y,x)] = l
        # need a special label for no background, because
        # it seems impossible to reset a background image
        self.noFrameLabel = Label(appWindow)
        self._x = 0
        self._y = 0
        self._w = 10
        self._h = 10
        self._zoom = 1.
        self._alpha = 0.5
        self._active = False
        self._ini_file = -1
        self.read_ini_file(ini_file)

    def read_ini_file(self, ini_file):
        if ini_file == self._ini_file:
            return
        self._ini_file = ini_file
        if ini_file is None:
            self._frameWidthX = 1
            self._frameWidthY = 1
            self._minFrameWidthX = 1
            self._minFrameWidthY = 1
            self._margins = (0, 0, 5, 5)
            self._basepath = None
        else:
            try:
                p = configparser.ConfigParser()
                p.read([ini_file])
                self._basepath = os.path.join(os.path.dirname(ini_file),
                                             p.get("FRAME", "base_path"))
                self._frameWidthX = p.getint("FRAME","cornerX")
                self._frameWidthY = p.getint("FRAME","cornerY")
                self._minFrameWidthX = p.getint("FRAME", "minCornerWidth")
                self._minFrameWidthY = p.getint("FRAME", "minCornerHeight")
                self._margins = (p.getint("FRAME", "MinMarginX"),
                                 p.getint("FRAME", "MinMarginY"),
                                 p.getint("FRAME", "OptMarginX"),
                                 p.getint("FRAME", "OptMarginY"))
            except:
                acwarning("Error while applying frame ini file %s, continueing with no frame.", ini_file)
                return self.read_ini_file(None)
        self.recalc()
        return self

    def margins(self):
        return self._margins

    def setBackgroundOpacity(self, alpha):
        if alpha != self._alpha:
            self._alpha = alpha
            self.recalc()
        return self

    def setPos(self, x, y):
        if x != self._x or y != self._y:
            self._x = x
            self._y = y
            self.recalc()
        return self

    def getPos(self):
        return (self._x, self._y)

    def getWidth(self):
        return self._w

    def getHeight(self):
        return self._h

    def active(self):
        active = self._active and self._w >= 2*self._minFrameWidthX and self._h >= 2*self._minFrameWidthY
        return active

    def setSize(self, w, h):
        if w != self._w or h != self._h:
            self._w = w
            self._h = h
            self.recalc()
        return self

    def recalc(self):
        active = self.active()
        for k in self._labels.keys():
            r,c = k
            a = active and (r == 'c' or self._frameWidthY > 0)
            self._labels[k].setActive(a and not self._basepath is None)
        self.noFrameLabel.setActive(a and self._basepath is None)
        if not active:
            return
        def setGeom(labels, ly, lx, x, y, w, h, basepath, alpha):
            l = labels[(ly,lx)]
            l.setPos(x,y)
            l.setSize(w,h)
            if w > 0 and h > 0:
                if not self._basepath is None:
                    imgPath = img_scaler.scaleImg(basepath + "_" + ly + lx + ".png", w, h, alpha)
                    l.setBackgroundImage(imgPath)
                    l.setBackgroundOpacity(0.0)
                else:
                    l.setActive(False)
        if self._basepath is None:
            self.noFrameLabel.setPos(self._x, self._y)
            self.noFrameLabel.setSize(self._w, self._h)
            self.noFrameLabel.setBackgroundOpacity(self._alpha)
        else:
            fw = self._frameWidthX
            fh = self._frameWidthY
            zw = round(self._w*self._zoom)
            zh = round(self._h*self._zoom)
            scale = 1.
            if fh > 0 and fw > 0:
                if 2*fw > zw or 2*fh > zh:
                    scale = min(zw/(2.*fw), zh/(2.*fh))
            elif fh < 0:
                scale = zh/(1.*(-fh))
                # we search for a scale factor such that
                #  fwn = fw*scale is an integer
                # and
                #  fhn = fh*scale - h is minimal
                fwn = round(fw*scale)
                scale = fwn/fw
                fh = 0
            elif fw < 0:
                scale = zw/(1.*(-fw))
                # we search for a scale factor such that
                #  fwn = fw*scale is an integer
                # and
                #  fhn = fh*scale - h is minimal
                fhn = round(fh*scale)
                scale = fhn/fh
                fw = 0
            else:
                acinfo("basepath=%s fw=%d fh=%d", self._basepath, fw, fh)
                myassert(0)
            fw = round(fw*scale)
            fh = round(fh*scale)
            x0 = round(self._x*self._zoom)
            y0 = round(self._y*self._zoom)
            x1 = x0+fw
            x2 = x0+zw-fw
            y1 = y0+fh
            y2 = y0+zh-fh
            cw = zw-2*fw
            ch = zh-2*fh
            if fw > 0:
                if fh > 0:
                    setGeom(self._labels, 'u','l',x0,y0,fw,fh, self._basepath, self._alpha)
                    setGeom(self._labels, 'u','c',x1,y0,cw,fh, self._basepath, self._alpha)
                    setGeom(self._labels, 'u','r',x2,y0,fw,fh, self._basepath, self._alpha)
                    setGeom(self._labels, 'l','l',x0,y2,fw,fh, self._basepath, self._alpha)
                    setGeom(self._labels, 'l','c',x1,y2,cw,fh, self._basepath, self._alpha)
                    setGeom(self._labels, 'l','r',x2,y2,fw,fh, self._basepath, self._alpha)
                setGeom(self._labels, 'c','l',x0,y1,fw,ch, self._basepath, self._alpha)
                setGeom(self._labels, 'c','c',x1,y1,cw,ch, self._basepath, self._alpha)
                setGeom(self._labels, 'c','r',x2,y1,fw,ch, self._basepath, self._alpha)
            else:
                setGeom(self._labels, 'u','c',x1,y0,cw,fh, self._basepath, self._alpha)
                setGeom(self._labels, 'c','c',x1,y1,cw,ch, self._basepath, self._alpha)
                setGeom(self._labels, 'l','c',x1,y2,cw,fh, self._basepath, self._alpha)

        return self

    def setActive(self, active):
        if active != self._active:
            self._active = active
            self.recalc()
        return self

    def setZoom(self, zoom):
        if zoom != self._zoom:
            self._zoom = zoom
            self.noFrameLabel.setZoom(zoom)
            self.recalc()

class TabView(GridLayout):
    def __init__(self, appWindow, tabHeight, horGap, vertGap, tabDefinition, props):
        self.activeIndex = -1
        self.buttons = []
        self.colFrames = []
        self.frameLower = Frame(appWindow, tabviewStyles['content'])
        self.update(appWindow, tabHeight, horGap, vertGap, tabDefinition, props)

    def update(self, appWindow, tabHeight, horGap, vertGap, tabDefinition, props):
        GridLayout.__init__(self, x=0, y=0, width=None, height=None, gap=0,
                            colWidths=None, rowHeights=None, valign=GridLayout.VALIGN_TOP, halign=GridLayout.HALIGN_LEFT)
        tabWidths = list(map(lambda x: x['tabWidth'], tabDefinition))
        self.tab_ly = GridLayout(
            x=0,
            y=0,
            width=None,
            height=None,
            gap=horGap,
            colWidths=None,
            rowHeights=None,
            valign=GridLayout.VALIGN_CENTER,
            halign=GridLayout.HALIGN_LEFT)
        self.content_ly = GridLayout(
            x=0,
            y=0,
            width=None,
            height=None,
            gap=horGap,
            colWidths=None,
            rowHeights=None,
            valign=GridLayout.VALIGN_TOP,
            halign=GridLayout.HALIGN_LEFT,
            expandingX=[0],
            expandingY=[0])
        cMinMarginX, cMinMarginY, coptMarginX, coptMarginY = self.frameLower.margins()
        self.content_ly.setMargins(coptMarginX, coptMarginY)
        self.content_ly.setBackgroundElements(self.frameLower)
        self[(0,0)] = self.tab_ly
        self[(1,0)] = self.content_ly
        # set margins and frame fro lower content
        self.content = []
        self.activationCallbacks = {}
        for i,t in enumerate(tabDefinition):
            if i < len(self.buttons):
                f = self.colFrames[i]
                b = self.buttons[i]
            else:
                f = Frame(appWindow)
                self.colFrames.append(f)
                b = Button(appWindow)
                self.buttons.append(b)
                b.setFontAlignment('center')
            f.read_ini_file(tabviewStyles[False])
            if 'text' in t: b.setText(t['text'])
            if 'image' in t: b.setBackgroundImage(t['image'])
            if 'activateCallback' in t: self.activationCallbacks[i] = t['activateCallback']
            b.setClickEventHandler(functools.partial(self.activate, index=i))
            self.content.append(t['content'])
            # set up a container for the button (using the margins of the column frames
            minMarginX, minMarginY, optMarginX, optMarginY = self.colFrames[0].margins()
            buttonContainer = GridLayout(0, 0, None, None, 0, [tabWidths[i]], [tabHeight], valign=GridLayout.VALIGN_CENTER, halign=GridLayout.HALIGN_CENTER,
                                         marginX = optMarginX, marginY = optMarginY)
            buttonContainer[(0,0)] = b
            self.tab_ly[(0,i)] = buttonContainer
        self.tab_ly.setBackgroundElements(None, [], self.colFrames)
        self.activeIndex = min(len(self.content)-1, self.activeIndex)
        self.props = props
        self.setZoom(self._zoom)
        if len(self.content) > 0 and self.activeIndex < 0:
            self.activate(index=0)

    def activate(self, *args, **kw):
        idx = kw['index']
        if idx != self.activeIndex:
            self.content_ly[(0,0)] = self.content[idx]
            for i,b in enumerate(self.buttons):
                if 'fontColor' in self.props:
                    b.setFontColor(self.props['fontColor'][i == idx])
                if 'image' in self.props:
                    b.setFontColor(self.props['image'][i == idx])
                self.content[i].setActive(False)
            if 0 <= idx < len(self.content):
                self.content[idx].setActive(True)
            if idx in self.activationCallbacks: self.activationCallbacks[idx]()
        self.updateLayout()

    def setActive(self, active):
        if active != self._active:
            if active:
                idx = self.activeIndex
                self.activeIndex = -1
                self.activate(index=idx)
        return GridLayout.setActive(self, active)

    def setZoom(self, zoom):
        GridLayout.setZoom(self, zoom)
        for c in self.content:
            c.setZoom(zoom)
        for c in self.colFrames:
            c.setZoom(zoom)

class ChatReceiver:
    def __init__(self):
        pass

    def add_receive_callback(self, appWindow, callback):
        acsim.ac.addOnChatMessageListener(appWindow.getAcID(), genericAcCallback(callback))

