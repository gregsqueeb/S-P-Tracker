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

import os
import re
import time
import traceback
import win32process,win32gui

from ptracker_lib import gui_helpers
from ptracker_lib.gui_helpers import AppWindow, GridLayout, Frame, genericAcCallback, LineEdit, ChatReceiver
from ptracker_lib.gui_styles import *
from ptracker_lib.config import config
from ptracker_lib import acsim
from ptracker_lib.helpers import *
from ptracker_lib.ac_ini_files import VideoIniFile
from ptracker_lib.message_types import *
from ptracker_lib import hooked

class Chat:
    def __init__(self, ptracker, ptracker_app_window):
        self.chatEditorAppWindow = AppWindow(ID='ptracker-chat-editor')
        self.chatEditorAppWindow.hideACElements()
        self.chatEditorFrame = Frame(self.chatEditorAppWindow)
        self.chatEditor = LineEdit(self.chatEditorAppWindow)
        self.chatEditor.addOnValueChangeListener(self.sendChatMessage)
        self.showChatEditorCountdown = None
        self.firstChatShow = True
        self.chatReceiver = ChatReceiver()
        self.chatReceiver.add_receive_callback(ptracker_app_window, self.rcvChatMessage)
        self.ptracker_app_window = ptracker_app_window
        self.hook = None
        self.ptracker = ptracker
        self.displayedChatHelp = False
        self.MODE_TIMED = 0
        self.MODE_STATIC = 1
        self.NUM_MODES = 2
        self.mode = self.MODE_TIMED
        self.chat_colors = [(1.0,1.0,0.3,1.0), #yellow
                            (0.3,1.0,1.0,1.0), #cyan
                            ]
        self.lastChatColor = 0
        self.initialText = ""
        self.chatfilter = None
        self.chatfilter_re = None
        self.scrollingStart = -100000
        self.scrollPosition = None

    @callbackDecorator
    def scroll(self, direction):
        t = time.time()
        self.scrollingStart = t
        dmt = self.ptracker.gui.displayedMessageTimes
        if len(dmt) == 0:
            dmt = [t]
        if direction < 0:
            self.scrollPosition = (0, dmt[0])
        else:
            self.scrollPosition = (dmt[-1], t)
        acinfo("Scrolling -> scrollingStart = %f, scrollPos=%s", self.scrollingStart, self.scrollPosition)

    def reinit(self):
        self.chatEditorFrame.read_ini_file(wstyle2frame[config.GLOBAL.window_style])
        self.chatEditorFrame.setBackgroundOpacity(config.GLOBAL.background_opacity)
        minMarginX, minMarginY, optMarginX, optMarginY = self.chatEditorFrame.margins()
        self.chatEditor_ly = GridLayout(
            x=0,
            y=0,
            width=None,
            height=None,
            gap=0,
            colWidths=[360],
            rowHeights=[30],
            valign=GridLayout.VALIGN_TOP,
            halign=GridLayout.HALIGN_CENTER,
            marginX=optMarginX,
            marginY=optMarginY)
        self.chatEditor_ly[(0,0)] = self.chatEditor
        self.chatEditor_ly.setBackgroundElements(self.chatEditorFrame)
        self.chatEditor_ly.setActive(True)
        self.chatEditor_ly.setZoom(config.GLOBAL.zoom_gui)
        self.chatEditor_ly.updateLayout()
        if self.firstChatShow:
            self.firstChatShow = False
            self.repositionEditor()

    def update(self, dt):
        if self.hook is None:
            self.create_keyboard_hook()
        self.update_chat_editor(dt)

    def update_chat_editor(self, dt):
        if not self.showChatEditorCountdown is None:
            self.showChatEditorCountdown -= dt
            if self.showChatEditorCountdown < 0:
                self.showChatEditorCountdown = None
                self.chatEditor.setText(self.initialText)
                self.initialText = ""
                if not self.chatEditorAppWindow.active():
                    self.chatEditorAppWindow.setActive(True)
                    self.chatEditor.setFocus(1)
                    self.chatEditor.setFontSize(18)
                    self.chatEditor.setBackgroundOpacity(0.5)

    def repositionEditor(self):
        z = self.chatEditor_ly.getZoom()
        aw = round(self.chatEditor_ly.getWidth()*z)
        ah = round(self.chatEditor_ly.getHeight()*z)
        self.chatEditorAppWindow.setSize(aw, ah)
        res = VideoIniFile().resolution()
        dw = res['width']
        dh = res['height']
        newPos = None
        if config.CHAT.text_input_auto_position == config.CHATPOS_CENTER:
            newPos = ((dw-aw)*0.5, (dh-ah)*0.5)
        elif config.CHAT.text_input_auto_position == config.CHATPOS_TOP:
            newPos = ((dw-aw)*0.5, (dh-ah)*0.2)
        elif config.CHAT.text_input_auto_position == config.CHATPOS_BOTTOM:
            newPos = ((dw-aw)*0.5, (dh-ah)*0.8)
        if not newPos is None:
            self.chatEditorAppWindow.setPos(*newPos)

    def create_keyboard_hook(self):

        self.hook = hooked.hook()
        self.update_keyboard_shortcuts()

    def checkCurrentMode(self, f):
        @callbackDecorator
        def new_f(*args):
            if self.ptracker_app_window.renderingActive():
                return f(*args)
            else:
                acinfo("Dismissed shortcut, rendering not active...")
        return new_f

    def update_keyboard_shortcuts(self):
        self.hook.clear()
        if config.CONFIG_MESSAGE_BOARD.enable_msg_chat != config.MSG_DISABLED:
            self.hook.Hotkey(config.CHAT.shortcut_talk, self.checkCurrentMode(self.start_talk), args=())
            self.hook.Hotkey(config.CHAT.shortcut_mode, self.checkCurrentMode(self.changeMode), args=())
            self.hook.Hotkey(config.CHAT.shortcut_pgup, self.checkCurrentMode(self.scroll), args=(-1,))
            self.hook.Hotkey(config.CHAT.shortcut_pgdown, self.checkCurrentMode(self.scroll), args=(+1,))
            if not self.displayedChatHelp:
                self.displayedChatHelp = True
                self.ptracker.addMessage(text="Press " + " ".join(config.CHAT.shortcut_talk) + " to enter chat messages.",
                                         color=(1.,1.,1.,1.),
                                         mtype=MTYPE_LOCAL_FEEDBACK)
            for i in range(1,10):
                shortcut = getattr(config.CHAT, "msg_%d_shortcut" % i)
                msg = getattr(config.CHAT, "msg_%d_text" % i)
                self.hook.Hotkey(shortcut, self.checkCurrentMode(self.onShortcutMessage), args=(msg,))
        else:
            if not self.displayedChatHelp:
                self.displayedChatHelp = True
                self.ptracker.addMessage(text="Chat is disabled. Use the configuration dialog to enable it.",
                                         color=(1.,1.,1.,1.),
                                         mtype=MTYPE_LOCAL_FEEDBACK)

    def start_chat(self, initialText):
        self.initialText = initialText
        self.showChatEditorCountdown = 0.1

    @callbackDecorator
    def start_talk(self):
        if not self.chatEditorAppWindow.active():
            self.start_chat("")
        else:
            self.chatEditorAppWindow.setActive(False)

    @callbackDecorator
    def onShortcutMessage(self, msg):
        if not self.chatEditorAppWindow.renderingActive():
            if config.CHAT.msg_shortcut_send_direct:
                self.sendChatMessage(msg)
            else:
                self.start_chat(msg)

    @callbackDecorator
    def sendChatMessage(self, msg):
        self.chatEditorAppWindow.setActive(False)
        acsim.ac.sendChatMessage(msg)
        self.showChatEditorCountdown = None

    @callbackDecorator
    def rcvChatMessage(self, msg, author):
        if msg.strip() == "":
            return
        cf = config.CHAT.chat_filter.strip()
        if cf != self.chatfilter:
            self.chatfilter = cf
            self.chatfilter_re = None
            if cf != '':
                try:
                    self.chatfilter_re = re.compile(cf)
                except:
                    acwarning('Ignoring invalid chat filter "%s"', cf)
                    acwarning(traceback.format_exc())
        if not self.chatfilter_re is None:
            filtered = not self.chatfilter_re.search(msg) is None
        else:
            filtered = False
        if not filtered:
            acinfo("new chat msg (%s, %s)", msg, author)
            self.lastChatColor = (self.lastChatColor+1)%len(self.chat_colors)
            self.ptracker.addMessage(text="%s: %s" % (author, msg),
                                     color=self.chat_colors[self.lastChatColor],
                                     mtype=MTYPE_CHAT)
        else:
            acinfo("filtered chat msg (%s, %s)", msg, author)
        if author == "SERVER" and msg == "stracker has been restarted.":
            self.ptracker.connectToStracker()

    @callbackDecorator
    def requestNewShortcut(self, callback, *args):
        if self.hook is None:
            self.create_keyboard_hook()
        self.hook.clear()
        self.hook.Hotkey([], lambda self=self, callback=callback: [callback(list(self.hook.get_current_keys()),*args),
                                                                   self.update_keyboard_shortcuts()])

    @callbackDecorator
    def changeMode(self):
        self.mode = self.mode + 1
        if self.mode >= self.NUM_MODES:
            self.mode = 0
