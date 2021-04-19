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

from PySide2 import QtCore, QtGui, QtWebEngineWidgets, QtNetwork, QtWidgets
import functools
import time
from ptracker_lib.helpers import *

_qtthread = None
def qtthread():
    return _qtthread

class MyWebPage(QtWebEngineWidgets.QWebEnginePage):
    @callbackDecorator
    def extension(self, extension, option, output):
        if option is None or output is None:
            return False
        if extension == QtWebEngineWidgets.QWebEnginePage.ErrorPageExtension:
            acdebug("Error page called")
            errOption = option
            errPage = """\
<html>
    <head>
        <style>
            html body {
                background: rgba(255,255,255,0.6);
            }
        </style>
    </head>
    <body>
        <h1>
            Page loading error, URL: %(url)s
        </h1>
        <h3>
            Error occurred in the %(domain)s. Code is %(error)s.
        </h3>
        <h4>
            Error text:
        </h4>
        %(errtext)s
    </body>
</html>""" % {
        'url' : errOption.url.toString(),
        'domain' : "network domain" if errOption.domain == QtWebEngineWidgets.QWebEnginePage.QtNetwork else "http domain" if errOption.domain == QtWebEngineWidgets.QWebEnginePage.Http else "webkit domain" if errOption.domain == QtWebEngineWidgets.QWebEnginePage.WebKit else "unknown domain",
        'error' : errOption.error,
        'errtext' : errOption.errorString.replace("\n", "\n<br>"),
        }
            acdebug("%s", repr(output))
            output.baseUrl = errOption.url
            output.content = errPage.encode()
            #// errReturn->contentType = "text/html"
            #// errReturn->encoding = "UTF-8"; // these values are defaults
            return True
        acdebug("don't know how to handle extension")
        return False

    @callbackDecorator
    def supportsExtension(self, extension):
        acdebug("supportsExtension called.")
        if extension == QtWebEngineWidgets.QWebEnginePage.ErrorPageExtension:
            return True
        return QtWebEngineWidgets.QWebEnginePage.supportsExtension(extension)

    @callbackDecorator
    def javaScriptConsoleMessage (self, message, lineNumber, sourceID):
        acdebug("javascript %s:%d: %s", sourceID, lineNumber, message)


class QtThread(QtCore.QObject): #(QtCore.QThread):
    def __init__(self):
        QtCore.QObject.__init__(self)
        global _qtthread
        assert _qtthread is None
        _qtthread = self
        self.hook = None
        self.lastCheckTime = time.time()
        self.cnt = 0
        self.lastMousePos = QtCore.QPoint()
        self.imgMutex = QtCore.QMutex(QtCore.QMutex.Recursive)
        self.size = QtCore.QSize(640, 480)
        self.img = QtGui.QImage(self.size, QtGui.QImage.Format_ARGB32)
        self.loading = None

        def handler(msg_type, msg_string, *a):
            try:
                if msg_type == QtCore.QtMsgType.QtDebugMsg:
                    acdebug("Qt Message Handler: %s", msg_string)
                if msg_type == QtCore.QtMsgType.QtWarningMsg:
                    acwarning("Qt Message Handler: %s", msg_string)
                if msg_type == QtCore.QtMsgType.QtCriticalMsg:
                    acerror("Qt Message Handler: %s", msg_string)
                if msg_type == QtCore.QtMsgType.QtFatalMsg:
                    acerror("Qt Message Handler: %s", msg_string)
            except:
                acdebug("%s %s %s", msg_type, msg_string, a)
        QtCore.qInstallMessageHandler(handler)

        self.newSize = self._newSize
        self.clickEvent = self._clickEvent
        self.newPage = self._newPage
        self.page = None
        self.run()

    def getImage(self):
        lock = QtCore.QMutexLocker(self.imgMutex)
        res = self.img.copy()
        return res

    @callbackDecorator
    def check(self, mousePos):
        lock = QtCore.QMutexLocker(self.imgMutex)
        self.lastCheckTime = time.time()
        if mousePos != self.lastMousePos:
            self.lastMousePos = mousePos
            self.app.postEvent(self.page, QtGui.QMouseEvent(QtCore.QEvent.MouseMove, mousePos, QtCore.Qt.NoButton, QtCore.Qt.NoButton, QtCore.Qt.NoModifier))
        return self.cnt

    @callbackDecorator
    def active(self):
        return time.time() - self.lastCheckTime < 2.

    @callbackDecorator
    def render(self, *args):
        if not self.active():
            return
        #acdebug("qtbrowser: rendering %d", self.cnt)
        self.page.setViewportSize(self.size)
        img = QtGui.QImage(self.size, QtGui.QImage.Format_ARGB32_Premultiplied)
        img.fill(QtCore.Qt.transparent)
        palette = QtWidgets.QApplication.palette()
        palette.setBrush(QtGui.QPalette.Base, QtCore.Qt.transparent)
        self.page.setPalette(palette)
        painter = QtGui.QPainter(img)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        painter.setRenderHint(QtGui.QPainter.TextAntialiasing)
        painter.setRenderHint(QtGui.QPainter.SmoothPixmapTransform)
        self.page.mainFrame().render(painter)
        painter.end()
        lock = QtCore.QMutexLocker(self.imgMutex)
        self.cnt += 1
        self.img = img

    @callbackDecorator
    def renderRect(self, dirtyrect):
        if not self.active():
            return
        # avoid a lock over the whole (sometimes quite long lasting) rendering of the page
        # we make a copy of the image at the start, unlock everything
        # and when ready with rednering we can lock ourselfs again
        lock = QtCore.QMutexLocker(self.imgMutex)
        img = QtGui.QImage(self.img)
        lock.unlock()
        #acdebug("qtbrowser: rendering rect %d / %s", self.cnt, dirtyrect)
        painter = QtGui.QPainter(img)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        painter.setRenderHint(QtGui.QPainter.TextAntialiasing)
        painter.setRenderHint(QtGui.QPainter.SmoothPixmapTransform)
        painter.setCompositionMode(QtGui.QPainter.CompositionMode_Clear)
        painter.fillRect(dirtyrect, QtCore.Qt.transparent)
        painter.setCompositionMode(QtGui.QPainter.CompositionMode_SourceOver)
        self.page.mainFrame().render(painter, dirtyrect)
        painter.end()
        lock.relock()
        self.cnt += 1
        self.img = img

    @callbackDecorator
    @QtCore.Slot(int, int)
    def _newSize(self, w, h, zoom):
        lock = QtCore.QMutexLocker(self.imgMutex)
        w = round(w*zoom)
        h = round(h*zoom)
        acdebug("qtbrowser: setting browser size: %d %d", w, h)
        self.size = QtCore.QSize(w,h)
        self.page.mainFrame().setZoomFactor(zoom)
        self.render()

    @callbackDecorator
    @QtCore.Slot(int, int)
    def _clickEvent(self, x,y):
        if not self.active():
            return
        lock = QtCore.QMutexLocker(self.imgMutex)
        # emulate a mouse click on a position
        pos = QtCore.QPoint(x,y)
        self.app.sendEvent(self.page, QtGui.QMouseEvent(QtCore.QEvent.MouseButtonPress, pos, QtCore.Qt.LeftButton, QtCore.Qt.LeftButton, QtCore.Qt.NoModifier))
        self.app.sendEvent(self.page, QtGui.QMouseEvent(QtCore.QEvent.MouseButtonRelease, pos, QtCore.Qt.LeftButton, QtCore.Qt.LeftButton, QtCore.Qt.NoModifier))

    @callbackDecorator
    def _mouseHook(self,e,x,y,mouseData):
        # we must make sure to be quick here. Avoid any locking...
        if (not self.active() or
          self.lastMousePos.x() < 0 or self.lastMousePos.x() > self.size.width() or
          self.lastMousePos.y() < 0 or self.lastMousePos.y() > self.size.height() ):
            #acdebug("filtered event (%s %s) not in range", self.lastMousePos.x(), self.lastMousePos.y())
            return
        #acdebug("mouse event")
        if e == self.hook.MOUSE_WHEEL:
            #acdebug("mouse wheel event %d %d", self.lastMousePos.x(), self.lastMousePos.y())
            self.app.postEvent(self.page, QtGui.QWheelEvent(self.lastMousePos, mouseData, QtCore.Qt.NoButton, QtCore.Qt.NoModifier))

    @callbackDecorator
    def _keyEvent(self, event_type, key):
        if not self.active():
            return
        lock = QtCore.QMutexLocker(self.imgMutex)
        cMods = self.hook.get_current_mods()
        try:
            if not "Shift" in cMods and len(key) == 1:
                key = key.lower()
            qkey = QtGui.QKeySequence(key)[0]
            qtype = QtCore.QEvent.KeyPress if event_type == self.hook.KEY_DOWN else QtCore.QEvent.KeyRelease
            qmod = QtCore.Qt.KeyboardModifiers()
            for m in cMods:
                if m == "Shift":
                    qmod = qmod | QtCore.Qt.ShiftModifier
                if m == "Alt":
                    qmod = qmod | QtCore.Qt.AltModifier
                if m == "Ctrl":
                    qmod = qmod | QtCore.Qt.ControlModifier
            e = QtGui.QKeyEvent(qtype, qkey, qmod, key)
            acdebug("QtKeyEvent for '%s': %d %d %d '%s'", key, e.key(), int(e.modifiers()), qtype, e.text())
            if len(key) == 1 or qkey in [QtCore.Qt.Key_Backspace,
                                         QtCore.Qt.Key_Return,
                                         QtCore.Qt.Key_Enter,
                                         QtCore.Qt.Key_Delete,
                                         QtCore.Qt.Key_Home,
                                         QtCore.Qt.Key_End,
                                         QtCore.Qt.Key_Left,
                                         QtCore.Qt.Key_Up,
                                         QtCore.Qt.Key_Down,
                                         QtCore.Qt.Key_Right]:
                self.app.postEvent(self.page, e)
                return
        except:
            pass
        acdebug("Ignoring key %s", key)


    @callbackDecorator
    @QtCore.Slot(str, object)
    def _newPage(self, url, ptsInfo):
        acdebug("qtbrowser: newPage %s", url)
        lock = QtCore.QMutexLocker(self.imgMutex)
        if self.hook is None:
            from ptracker_lib import hooked
            self.hook = hooked.hook()
            self.hook.MouseHandler(self._mouseHook)
            self.hook.RawKeyboardHandler(callback=self._keyEvent, callID=self)
        self.page = MyWebPage()
        # connect signals
        self.page.loadStarted.connect(self.loadStarted)
        self.page.loadFinished.connect(self.loadFinished)
        self.page.loadFinished.connect(self.render)
        self.page.contentsChanged.connect(self.render)
        self.page.repaintRequested.connect(self.renderRect)
        self.page.frameCreated.connect(self.render)
        self.page.scrollRequested.connect(self.render)
        self.page.mainFrame().javaScriptWindowObjectCleared.connect(functools.partial(self.addJavaScriptObjects, page=self.page, ptsInfo=ptsInfo))
        # create a network manager for the page
        #acdebug("creating network manager")
        self.ptsManager = ptsInfo.PtsNetworkAccessManager(self.page.networkAccessManager(), ptsInfo.http_server, ptsInfo.ptracker)
        #acdebug("setting network manager")
        self.page.setNetworkAccessManager(self.ptsManager)
        # load the new url
        #acdebug("load url")
        self.page.mainFrame().load(url)
        # post an event that the page gets the focus (for keyboard inputs)
        self.app.postEvent(self.page, QtGui.QFocusEvent(QtCore.QEvent.FocusIn, QtCore.Qt.MouseFocusReason))

    @callbackDecorator
    def isLoading(self):
        lock = QtCore.QMutexLocker(self.imgMutex)
        return time.time() - self.loading if not self.loading is None else None

    @callbackDecorator
    def loadStarted(self):
        lock = QtCore.QMutexLocker(self.imgMutex)
        #acdebug("loadStarted")
        self.loading = time.time()

    @callbackDecorator
    def loadFinished(self, ok):
        lock = QtCore.QMutexLocker(self.imgMutex)
        #acdebug("loadFinished")
        self.loading = None

    @callbackDecorator
    def addJavaScriptObjects(self, page, ptsInfo):
        acdebug("add ptracker to java script objects")
        self.ptracker = ptsInfo.ptracker_wrapper
        page.mainFrame().addToJavaScriptWindowObject('ptracker', self.ptracker)

    def run(self):
        self.app = QtWidgets.QApplication([])

        acdebug("qtbrowser: run")
        self.app.exec_()

