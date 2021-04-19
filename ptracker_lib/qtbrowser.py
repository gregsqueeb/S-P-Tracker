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

from PySide2 import QtCore,  QtGui, QtWebEngineWidgets, QtNetwork
from ptracker_lib.helpers import *
from ptracker_lib.gui_helpers import Label
from ptracker_lib.qtbrowser_common import qtthread
from ptracker_lib.message_types import *
from ptracker_lib.ps_protocol import ProtocolHandler
import tempfile
import traceback
import os

http_server = None
protocol = 'pts'

query_cnt = 0

class PtsReplyBase(QtNetwork.QNetworkReply):
    def __init__(self, parent, url):
        super().__init__(parent)
        self.setUrl(url)
        self.open(self.ReadOnly | self.Unbuffered)
        self.content = None
        self.offset = 0

    @callbackDecorator
    def abort(self):
        pass

    @callbackDecorator
    def isSequential(self):
        return True

    @callbackDecorator
    def bytesAvailable(self):
        if not self.content is None:
            return len(self.content)
        return 0

    @callbackDecorator
    def readData(self, maxLen):
        l = min(maxLen, len(self.content)-self.offset)
        r = self.content[self.offset:self.offset+l]
        self.offset += l
        if self.offset == len(self.content):
            # acdebug("finished %s", self.url().toString())
            self.finished.emit()
            self.close()
        else:
            #acdebug("inter %s (%d/%d)", self.url().toString(), self.offset, len(self.content))
            pass
        return r

class PtsReplyLocal(PtsReplyBase):
    construct = QtCore.Signal(str, object)

    def __init__(self, parent, url, http_server):
        super().__init__(parent, url)
        if not self.construct.connect(self.do_construct, QtCore.Qt.QueuedConnection):
            acerror("Cannot connect signal, things are going to be bad: %s", "".join(traceback.format_stack()))
        # delayed construction of this object
        self.construct.emit(url.toString(), http_server)

    @callbackDecorator
    def do_construct(self, url, http_server):
        try:
            content, header, cacheable = http_server.serve_pts(url)
            self.content = content
            self.setHeader(QtNetwork.QNetworkRequest.ContentTypeHeader, header)
            self.setHeader(QtNetwork.QNetworkRequest.ContentLengthHeader, len(self.content))
            self.setHeader(QtNetwork.QNetworkRequest.LocationHeader, url)
            self.readyRead.emit()
        except:
            e = traceback.format_exc()
            acerror(e)
            self.setError(QtNetwork.QNetworkReply.ContentNotFoundError, e)
            self.error.emit(QtNetwork.QNetworkReply.ContentNotFoundError)
            self.finished.emit()

class PtsReplyRemote(PtsReplyBase):
    construct = QtCore.Signal(str, object)
    active_connections = []

    def __init__(self, parent, url, ptracker):
        super().__init__(parent, url)
        if not self.construct.connect(self.do_construct, QtCore.Qt.QueuedConnection):
            acerror("Cannot connect signal, things are going to be bad: %s", "".join(traceback.format_stack()))
        # delayed construction of this object
        self.construct.emit(url.toString(), ptracker)

    @callbackDecorator
    def do_construct(self, url, ptracker):
        try:
            self.ptracker = ptracker
            if (not hasattr(ptracker, "ptClient") or ptracker.ptClient is None or not ptracker.ptClient.isOnline()):
                raise RuntimeWarning("No remote connection available.")
            elif not ptracker.ptClient.capabilities() & ProtocolHandler.CAP_PTS_PROTOCOL:
                raise RuntimeWarning("Stracker version too old to browse statistics.")
            else:
                self.handle = ptracker.remoteDB.getPtsResponse(url)
                PtsReplyRemote.active_connections.append(self)
                self.ptsid = None
                self.timer = QtCore.QTimer()
                self.timer.timeout.connect(self.checkForAnswer)
                self.timer.start(100)
        except RuntimeWarning as ex:
            e = str(ex)
            acinfo("Remote connection not available: %s", e)
            self.setError(QtNetwork.QNetworkReply.HostNotFoundError, e)
            self.error.emit(QtNetwork.QNetworkReply.HostNotFoundError)
            self.finished.emit()
        except:
            e = traceback.format_exc()
            acerror("PtsReplyRemote exception: %s", e)
            self.setError(QtNetwork.QNetworkReply.ContentNotFoundError, e)
            self.error.emit(QtNetwork.QNetworkReply.ContentNotFoundError)
            self.finished.emit()

    @callbackDecorator
    def checkForAnswer(self):
        if self.ptsid is None:
            a = self.handle()
            if not a is None:
                self.ptsid = a
        elif self.content is None:
            while not self.ptracker.ptClient.ptsReplies.empty():
                found = False
                ptsreply = self.ptracker.ptClient.ptsReplies.get()
                # make a copy of the list, so there is no risk of "list changed while iteration" error
                ac = PtsReplyRemote.active_connections[:]
                for prr in ac:
                    if prr.ptsid == ptsreply[3]:
                        prr.setPtsReply(ptsreply)
                        found = True
                        break
                if not found:
                    acdebug("could not find matching PtsReplyRemote instance for ptsreply -> assuming it will be available at next check.")
                    self.ptracker.ptClient.ptsReplies.put(ptsreply)
                    break

    @callbackDecorator
    def abort(self):
        try:
            PtsReplyRemote.active_connections.remove(self)
        except ValueError:
            pass

    @callbackDecorator
    def setPtsReply(self, ptsreply):
        self.content = ptsreply[0]
        self.setHeader(QtNetwork.QNetworkRequest.ContentTypeHeader, ptsreply[1])
        self.setHeader(QtNetwork.QNetworkRequest.ContentLengthHeader, len(self.content))
        self.setHeader(QtNetwork.QNetworkRequest.LocationHeader, self.url().toString())
        PtsReplyRemote.active_connections.remove(self)
        self.readyRead.emit()


class PtsNetworkAccessManager(QtNetwork.QNetworkAccessManager):
    def __init__(self, old_manager, http_server, ptracker):
        QtNetwork.QNetworkAccessManager.__init__(self)
        self.old_manager = old_manager
        self.http_server = http_server
        self.ptracker = ptracker
        self.setCache(old_manager.cache())
        self.setCookieJar(old_manager.cookieJar())
        self.setProxy(old_manager.proxy())
        self.setProxyFactory(old_manager.proxyFactory())
        self.finished.connect(self._request_finished)

    @callbackDecorator
    def _request_finished(self, reply):
        if reply.error() != QtNetwork.QNetworkReply.NoError:
            acdebug("%s: finished: reply.error()=%s reply.errorString()=%s", reply.url().toString(), reply.error(), reply.errorString())
        else:
            acdebug("%s: finished, no error.", reply.url().toString())

    #@callbackDecorator
    def createRequest(self, operation, request, device):
        #acdebug("ptsnam: createRequest %s %s %s", operation, request, device)
        if 1 and request.url().scheme() == protocol and operation == self.GetOperation:
            try:
                if request.url().host() == 'local':
                    r = PtsReplyLocal(self, request.url(), self.http_server)
                else:
                    r = PtsReplyRemote(self, request.url(), self.ptracker)
                return r
            except:
                acwarning("Error: %s", traceback.format_exc())
        acwarning("ptsnam: unexpected request, using base class manager")
        return QtNetwork.QNetworkAccessManager.createRequest(self, operation, request, device)

cleanup_temp_files = False
def tempfile_gen(suffix):
    with tempfile.TemporaryDirectory(prefix='ptracker_browser_') as d:
        acinfo("Generated temporary directory %s", d)
        filecnt = 0
        generated_files = []
        while not cleanup_temp_files:
            while len(generated_files) > 3:
                to_del = generated_files[0]
                generated_files = generated_files[1:]
                try:
                    os.remove(to_del)
                except:
                    pass
            res = os.path.join(d, "%d%s" % (filecnt,suffix))
            generated_files.append(res)
            yield res
            filecnt += 1

pngTemps = tempfile_gen('.png')

def shutdown():
    global cleanup_temp_files
    cleanup_temp_files = True
    try:
        next(pngTemps)
    except StopIteration:
        pass

def getTempFileName():
    return next(pngTemps)

class WebBrowser(Label):

    def __init__(self, appWindow, ID = None):
        Label.__init__(self, appWindow, ID)
        self.setClickEventHandler(self.onClicked)
        self._parent.addRenderCallback(self.check)
        self.loadIndicator = Label(appWindow)
        self.loadIndicator.setFontSize(14).setFontColor((.03,.5,.03,1.)).setBackgroundOpacity(0.)
        self.browser = qtthread()
        # i don't want webbrowser to inherit qobject...
        class SignalEmitter(QtCore.QObject):
            sizeChanged = QtCore.Signal(int,int,float)
            clicked = QtCore.Signal(int,int)
            pageChanged = QtCore.Signal(str, object)
        self.qobject = SignalEmitter()
        self.sethread = QtCore.QThread()

        self.qobject.moveToThread(self.sethread)
        if not self.qobject.sizeChanged.connect(self.browser.newSize, QtCore.Qt.QueuedConnection):
            acerror("WebBrowser: connect not succeeded!")
        else:
            acinfo("WebBrowser: connect ok")
        if not self.qobject.clicked.connect(self.browser.clickEvent, QtCore.Qt.QueuedConnection):
            acerror("WebBrowser: connect not succeeded!")
        else:
            acinfo("WebBrowser: connect ok")
        if not self.qobject.pageChanged.connect(self.browser.newPage, QtCore.Qt.QueuedConnection):
            acerror("WebBrowser: connect not succeeded!")
        else:
            acinfo("WebBrowser: connect ok")
        self.lastCnt = None
        global http_server
        if http_server is None:
            from stracker_lib import http_server_base as http_server_module
            from stracker_lib.config import config
            config.HTTP_CONFIG.enable_paypal_link = False
            http_server = http_server_module.StrackerPublicBase()
            class PtsProtocolInfo(object):
                def __init__(self):
                    pass
            ptsInfo = PtsProtocolInfo()
            ptsInfo.http_server = http_server

            class PtrackerSlots(QtCore.QObject):
                def __init__(self, ptracker):
                    super().__init__()
                    self.ptracker = ptracker

                @QtCore.Slot(int, int, str)
                @callbackDecorator
                def setCompareLapId(self, lapId, remote, track):
                    if track != self.ptracker.getTrackName():
                        self.ptracker.addMessage(text="Cannot compare laps from different tracks. (%s != %s)" % (track, self.ptracker.getTrackName()),
                                                 color=(1.0,1.0,1.0,1.0), mtype=MTYPE_LOCAL_FEEDBACK)
                    self.ptracker.queryLapInfoForLapComparison(lapId, remote)

                @QtCore.Slot()
                @callbackDecorator
                def resetCompareLap(self):
                    self.ptracker.setCompareLap(None)

            ptsInfo.ptracker_wrapper = PtrackerSlots(http_server_module.ptracker)
            ptsInfo.ptracker = http_server_module.ptracker
            acinfo("Created http server. Elements: %s", str(dir(http_server)))
            QtWebEngineWidgets.QWebEngineSecurityOrigin.addLocalScheme('pts:')
            ptsInfo.PtsNetworkAccessManager = PtsNetworkAccessManager
            self.ptsInfo = ptsInfo
            self.qobject.pageChanged.emit(protocol+"://local/lapstat", self.ptsInfo)

    @callbackDecorator
    def loadUrl(self, url):
        url = protocol + "://" + url.split("://")[-1]
        self.qobject.pageChanged.emit(url, self.ptsInfo)

    @callbackDecorator
    def onSizeChanged(self, w, h, zoom):
        Label.onSizeChanged(self, w, h, zoom)
        #acdebug("WebBrowser: sizeChanged %d %d", w, h)
        self.qobject.sizeChanged.emit(w, h, zoom)

    @callbackDecorator
    def onClicked(self, x, y, *args):
        #acdebug("clicked (%d %d)", x, y)
        self.qobject.clicked.emit(x*self._zoom,y*self._zoom)

    # needs to be called cyclically
    @callbackDecorator
    def check(self, *args):
        if not self.active():
            return
        sp = QtGui.QCursor.pos() # global screen coordinates of mouse position
        gp = self.getGlobalPos()
        lp = QtCore.QPoint(sp.x() - gp[0], sp.y() - gp[1])
        nc = self.browser.check(lp)
        dt = self.browser.isLoading()
        if not dt is None:
            self.loadIndicator.setActive(1)
            lp = self.getPos()
            self.loadIndicator.setPos(lp[0]+7, lp[1]+7)
            self.loadIndicator.setSize(20, 20)
            s = int(((dt % 1.0)/1.0)*4.0)
            s = max(0, min(3, s))
            self.loadIndicator.setText("/-\|"[s])
        else:
            self.loadIndicator.setActive(False)
        if self.lastCnt != nc:
            self.lastCnt = nc
            img = self.browser.getImage()
            imgName = getTempFileName()
            res = img.save(imgName)
            #acdebug("WebBrowser: new rendered image, size=(%d,%d) (ok=%s): %s", img.width(), img.height(), res, imgName)
            self.setBackgroundImage(imgName)
