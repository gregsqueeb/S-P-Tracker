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

from threading import Thread
import socket, time, select
from . import ac_server_protocol
from . import ac_server_udp_monitor

class PlausibilityCheckFailed(RuntimeError):
    pass

class ACServerPlugin:

    def __init__(self,
                 rcvPort,
                 sendPort,
                 callbacks,
                 proxyRcvPort=None,
                 proxySendPort=None,
                 proxyDebugFile=None,
                 serverIP="127.0.0.1",
                 log_err_  = lambda *x:print('ERROR:',*x),
                 log_info_ = lambda *x:print('INFO:',*x),
                 log_dbg_  = lambda *x:print('DEBUG:',*x)):
        """
        create a new server plugin instance, given
            - rcvPort      : used to receive the messages from the AC server
            - sendPort     : used to send requests to the AC server
            - callbacks    : a list of callables (or a single callable) called
                             whenever a new message is received from the server
                             the function receives one argument with an instance
                             of the data sent by the server.
                             (see ac_server_protocol for details)
            - proxyRcvPort : (optional) a port where the received messages are
                             forwarded to. With this, a simple chaining of
                             plugins is possible.
            - proxySendPort: (optional) messages sent to this port will be
                             forwarded to the AC server. With this, a simple
                             chaining of plugins is possible.
            - log_err/log_info/log_dbg: (optional) functions to provide user messages
        """
        try:
            _ = iter(callbacks)
        except TypeError:
            callbacks = [callbacks]
        self.callbacks = callbacks
        global log_err, log_info, log_dbg
        log_err = log_err_
        log_info = log_info_
        log_dbg = log_dbg_
        ac_server_protocol.log_err = log_err
        ac_server_protocol.log_info = log_info
        ac_server_protocol.log_dbg = log_dbg
        ac_server_udp_monitor.log_err = log_err
        ac_server_udp_monitor.log_info = log_info
        ac_server_udp_monitor.log_dbg = log_dbg

        self.host = serverIP
        self.sendPort = sendPort
        self.rcvPort = rcvPort

        if not 1024 <= rcvPort <= 65535 or not 1024 <= sendPort <= 65535:
            log_err("Fatal error: Unplausible UDP_PLUGIN_ settings in server_cfg.ini. Specify port numbers between 1024 and 65535.")
            log_err("Configured ports: UDP_PLUGIN_ADDRESS=%d, UDP_PLUGIN_LOCAL_PORT=%d", rcvPort, sendPort)
            raise PlausibilityCheckFailed()

        if rcvPort == sendPort:
            log_err("Fatal error: Unplausible UDP_PLUGIN_ settings in server_cfg.ini. Port numbers must not be equal.")
            log_err("Configured ports: UDP_PLUGIN_ADDRESS=%d, UDP_PLUGIN_LOCAL_PORT=%d", rcvPort, sendPort)
            raise PlausibilityCheckFailed()

        self.acSocket = self.openSocket(self.host, self.rcvPort, self.sendPort, None)
        log_info("Plugin listens to port %d and sends to port %d." % (self.rcvPort, self.sendPort))
        self.udpMonitor = ac_server_udp_monitor.ACUdpMonitor()

        if not proxyRcvPort is None and not proxySendPort is None:
            if not 1024 <= proxyRcvPort <= 65535 or not 1024 <= proxySendPort <= 65535:
                log_err("Fatal error: Unplausible proxy configuration. Specify ports between 1024 and 65535.")
                log_err("Configured ports: proxyRcvPort=%d proxySendPort=%d", proxyRcvPort, proxySendPort)
                raise PlausibilityCheckFailed()
            if proxyRcvPort in [rcvPort, sendPort, proxySendPort] or proxySendPort in [rcvPort, sendPort, proxyRcvPort]:
                log_err("Fatal error: Unplausible proxy configuration. Specify unique ports for the proxy.")
                log_err("Configured ports: proxyRcvPort=%d proxySendPort=%d UDP_PLUGIN_ADDRESS=%d UDP_PLUGIN_LOCAL_PORT=%d",
                        proxyRcvPort, proxySendPort, rcvPort, sendPort)
                raise PlausibilityCheckFailed()
            log_info("Plugin proxy enabled. The proxied plugin shall be configured as if the following lines were in server_cfg.ini:")
            log_info("UDP_PLUGIN_ADDRESS=127.0.0.1:%d"%proxyRcvPort)
            log_info("UDP_PLUGIN_LOCAL_PORT=%d"%proxySendPort)
            self.proxyDebugFile = proxyDebugFile
            self.proxyRcvPort = proxyRcvPort
            self.proxySendPort = proxySendPort
            self.proxySocket = self.openSocket(self.host, self.proxySendPort, self.proxyRcvPort, None)
            self.proxySocketThread = Thread(target=self._performProxy)
            self.proxySocketThread.daemon=True
            self.proxySocketThread.start()
        else:
            self.proxySocket = None

    def openSocket(self, host, rcvp, sendp, s):
        if not s is None: s.close()
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.bind( (host, rcvp) )
        # set up a 0.5s pulse, need this to be able to Ctrl-C the python apps
        s.settimeout(0.5)
        return s

    def processServerPackets(self, timeout=None):
        """
        call this function to process server packets for a given
        timespan (timeout) or forever, if timeout is set to None
        """
        t = time.time()
        while 1:
            try:
                data, addr = self.acSocket.recvfrom(4096)
                r = ac_server_protocol.parse(data)
                if type(r) == ac_server_protocol.ProtocolVersion:
                    self.udpMonitor.reset()
                elif type(r) == ac_server_protocol.ConnectionClosed:
                    self.udpMonitor.reset(carId=r.carId)
                if not self.proxySocket is None and self.udpMonitor.okToSend(1, r):
                    try:
                        if not self.proxyDebugFile is None: self.proxyDebugFile.write("%6.3f: -> %s\n" %(time.time()%10, str(r)))
                        self.proxySocket.sendto(data, ("127.0.0.1", self.proxyRcvPort))
                    except:
                        pass
                if self.udpMonitor.okToSend(0, r):
                    for c in self.callbacks:
                        c(r)
                self.udpMonitor.plausibilityCheck()
            except socket.timeout:
                pass
            except ConnectionResetError:
                # I hate windows :( who would ever get the idea to set WSAECONNRESET on a connectionless protocol ?!?
                # The upshot is this: when we send data to a socket which has no listener attached (yet)
                # windows is giving the connection reset by peer error at the next recv call
                # It seems that the socket is unusable afterwards, so we re-open it :(
                self.acSocket = self.openSocket(self.host, self.rcvPort, self.sendPort, self.acSocket)
            if not timeout is None:
                if time.time()-t > timeout:
                    break

    def getSessionInfo(self, sessionIndex = -1):
        """
        request the session info of the specified session (-1 for current session)
        """
        self.udpMonitor.infoRequest(0, ac_server_protocol.SessionInfo,
            lambda si, sessionIndex=sessionIndex: si.sessionIndex == sessionIndex if sessionIndex >= 0 else lambda si: si.sessionIndex == si.currSessionIndex)
        p = ac_server_protocol.GetSessionInfo(sessionIndex=sessionIndex)
        self.acSocket.sendto(p.to_buffer(), (self.host, self.sendPort))

    def getCarInfo(self, carId):
        """
        request the car info packet from the server
        """
        self.udpMonitor.infoRequest(0, ac_server_protocol.CarInfo, lambda ci, carId=carId: ci.carId == carId)
        p = ac_server_protocol.GetCarInfo(carId=carId)
        self.acSocket.sendto(p.to_buffer(), (self.host, self.sendPort))

    def enableRealtimeReport(self, intervalMS):
        """
        enable the realtime report with a given interval
        """
        newInterval = self.udpMonitor.setIntervals(0, intervalMS)
        if not newInterval is None:
            p = ac_server_protocol.EnableRealtimeReport(intervalMS=newInterval)
            self.acSocket.sendto(p.to_buffer(), (self.host, self.sendPort))
            log_dbg("enableRealtimeReport: using new interval %d"%newInterval)
        else:
            log_dbg("enableRealtimeReport: using higher frequency from the proxy plugin")

    def sendChat(self, carId, message):
        """
        send chat message to a specific car
        """
        p = ac_server_protocol.SendChat(carId=carId, message=message)
        self.acSocket.sendto(p.to_buffer(), (self.host, self.sendPort))

    def broadcastChat(self, message):
        """
        broadcast chat message to all cars
        """
        p = ac_server_protocol.BroadcastChat(message=message)
        d = p.to_buffer()
        self.acSocket.sendto(d, (self.host,self.sendPort))

    def setSessionInfo(self, sessionIndex, sessionName, sessionType, laps, timeSeconds, waitTimeSeconds):
        p = ac_server_protocol.SetSessionInfo(sessionIndex=sessionIndex,
                                              sessionName=sessionName,
                                              sessionType=sessionType,
                                              laps=laps,
                                              timeSeconds=timeSeconds,
                                              waitTimeSeconds=waitTimeSeconds)
        self.acSocket.sendto(p.to_buffer(), (self.host, self.sendPort))

    def kickUser(self, carId):
        p = ac_server_protocol.KickUser(carId=carId)
        self.acSocket.sendto(p.to_buffer(), (self.host, self.sendPort))

    def nextSession(self):
        p = ac_server_protocol.NextSession()
        self.acSocket.sendto(p.to_buffer(), (self.host, self.sendPort))

    def restartSession(self):
        p = ac_server_protocol.RestartSession()
        self.acSocket.sendto(p.to_buffer(), (self.host, self.sendPort))

    def adminCommand(self, command):
        p = ac_server_protocol.AdminCommand(command=command)
        self.acSocket.sendto(p.to_buffer(), (self.host, self.sendPort))

    def _performProxy(self):
        while 1:
            try:
                data, addr = self.proxySocket.recvfrom(4096)
                if addr[0] == "127.0.0.1":
                    r = ac_server_protocol.parse(data)
                    if not self.proxyDebugFile is None: self.proxyDebugFile.write("%6.3f: <- %s\n" %(time.time()%10, str(r)))
                    if type(r) == ac_server_protocol.EnableRealtimeReport:
                        newInterval = self.udpMonitor.setIntervals(1, r.intervalMS)
                        if not newInterval is None:
                            r.intervalMS = newInterval
                            data = r.to_buffer()
                            log_dbg("proxyRealtimeReport: using new interval %d"%newInterval)
                        else:
                            log_dbg("proxyRealtimeReport: using higher frequency from the plugin")
                            # do not pass the request, stay at higher frequency
                            continue
                    elif type(r) == ac_server_protocol.GetCarInfo:
                        self.udpMonitor.infoRequest(1,
                            ac_server_protocol.CarInfo, lambda ci, cid=r.carId: ci.carId == cid)
                    elif type(r) == ac_server_protocol.GetSessionInfo:
                        self.udpMonitor.infoRequest(1,
                            ac_server_protocol.SessionInfo,
                            lambda si, sessionIndex=r.sessionIndex: si.sessionIndex == sessionIndex if sessionIndex >= 0 else lambda si: si.sessionIndex == si.currSessionIndex)
                    self.acSocket.sendto(data, (self.host, self.sendPort))
                    time.sleep(0.2)
            except socket.timeout:
                pass
            except ConnectionResetError:
                # I hate windows :( who would ever get the idea to set WSAECONNRESET on a connectionless protocol ?!?
                self.proxySocket = self.openSocket(self.host, self.proxySendPort, self.proxyRcvPort, self.proxySocket)
                time.sleep(1.0)


# just print all attributes of the event
def print_event(x, v = None, indent = "  "):
    if hasattr(x, "__dict__"):
        for a in x.__dict__:
            print_event(a, getattr(x,a, None), indent + "  ")
    else:
        s = indent + str(x) + " = "
        if type(v) in [tuple, list] and len(v) > 0 and type(v[0]) not in [float, int, str]:
            print(s)
            indent += "  "
            for e in v:
                print(indent+"-")
                print_event(e, None, indent)
        else:
            if not v is None: s += str(v)
            print(s)

