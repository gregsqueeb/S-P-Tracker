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

import functools
import time
import datetime
import math
import re
import traceback

from ptracker_lib import gui_helpers
from ptracker_lib.gui_helpers import AppWindow, Button, Label, GridLayout, Spinner
from ptracker_lib.gui_helpers import EnumSelector, CheckBox, HorizontalPane, GenericTableDisplay
from ptracker_lib.gui_helpers import Frame, genericAcCallback, acFontCache
from ptracker_lib import qtbrowser
from ptracker_lib.Chat import Chat

from ptracker_lib.gui_styles import *
from ptracker_lib.GuiStatistics import LapStatDisplay
from ptracker_lib.config import config
from ptracker_lib.helpers import *
from ptracker_lib.message_types import *
from ptracker_lib import img_scaler
from ptracker_lib import acsim

LeaderboardDisplay = functools.partial(GenericTableDisplay,
    colToNameMappings=[["lblLBPositions","lblLBDriverState","lblLBBadge","lblLBTyre","lblLBTeam","lblLBNames","lblLBLaps","lblLBDelta","lblLBLapTime","lblMR"]])

MessageDisplay = functools.partial(GenericTableDisplay,
    colToNameMappings=[["lblMessage"]])

class Gui:
    # lastLayout values
    LY_RACE = 0
    LY_QUAL = 1
    LY_HOTLAP = 2

    # session types known
    SESSION_PRACTICE = 0
    SESSION_QUALIFY = 1
    SESSION_RACE = 2
    SESSION_HOTLAP = 3

    # dynamic display
    DYNDIS_LIVE = 0
    DYNDIS_SPLIT = 1
    DYNDIS_PIT = 2

    # lap stat display requests
    LSD_NOCHANGE = 0
    LSD_NORMALSHOW = 1
    LSD_SETUPSHOW = 2

    def __init__(self, appWindow, ptracker):
        global gui
        gui = self

        self.appWindow = AppWindow(acID=appWindow, ID='ptracker').setClickEventHandler(self.onClickApp)
        self.msgWindow = AppWindow(ID='ptracker-messages', doNotHide=True)
        self.msgWindow.hideACElements()

        self.popupMenu = AppWindow(ID='ptracker-popup')
        self.popupMenu.hideACElements()
        self.popupFrame = Frame(self.popupMenu)
        self.lblPmDriver = Label(self.popupMenu)
        self.btnPmFocus = Button(self.popupMenu)
        self.btnPmFocus.setClickEventHandler(self.focusClickedDriver)
        self.btnPmChat = Button(self.popupMenu)
        self.btnPmChat.setClickEventHandler(self.chatClickedDriver)
        self.btnPmSendSet = Button(self.popupMenu)
        self.btnPmSendSet.setClickEventHandler(self.sendSetClickedDriver)
        self.btnPmKick = Button(self.popupMenu)
        self.btnPmKick.setClickEventHandler(self.kickClickedDriver)
        self.btnPmBan = Button(self.popupMenu)
        self.btnPmBan.setClickEventHandler(self.banClickedDriver)
        self.btnPmCancel = Button(self.popupMenu)
        self.btnPmCancel.setClickEventHandler(self.cancelClickedDriver)
        self.pmConfirmationCnt = (0,0)

        self.chat = Chat(ptracker, self.appWindow)

        self.hotlapLineFrame = Frame(self.appWindow)
        self.leaderboardFrame = Frame(self.appWindow)
        self.messageboardFrame = Frame(self.msgWindow)

        self.leaderboardRowFrames = [Frame(self.appWindow) for i in range(40)]
        self.messageRowFrames = [Frame(self.msgWindow) for i in range(30)]

        self.ptracker = ptracker
        self.lastTimeClicked = None
        self.lblDBMsg = Label(self.appWindow, "dbmsg")

        self.lblLiveDelta = Label(self.appWindow, "liveDelta")
        self.lblCmpSplit = Label(self.appWindow, "cmpSplit")
        self.lblSplitDelta = Label(self.appWindow, "splitDelta")
        self.lblCmpSector = Label(self.appWindow, "cmpSector")
        self.lblSectorDelta = Label(self.appWindow, "sectorDelta")
        validImg = [r"apps\python\ptracker\images\invalid.png",
                    r"apps\python\ptracker\images\valid.png"]
        self.lblValidity = EnumSelector(self.appWindow, ["",""], 0, ID="validity", images=validImg, userChange=False)
        self.lblValidityReason = Label(self.appWindow, "validityReason")
        self.lblLapTime = Label(self.appWindow, "lapTime")
        self.lblSplitTime = Label(self.appWindow, "splitTime")
        self.lblSectorTime = Label(self.appWindow, "sectorTime")
        self.lblValidityDesc = Label(self.appWindow, "validityDesc")
        self.lblLiveDesc = Label(self.appWindow, "liveDesc")
        self.lblSplitDesc = Label(self.appWindow, "splitDesc")
        self.lblSectorDesc = Label(self.appWindow, "sectorDesc")
        self.lblSessionDisplay = Label(self.appWindow, "sessionDisplay")
        fuelImg = [r"apps\python\ptracker\images\fuel.png", r"apps\python\ptracker\images\fuel_warn.png", r"apps\python\ptracker\images\fuel_dng.png"]
        self.lblFuelIcon = EnumSelector(self.appWindow, ["","","",""], 0, ID="fuelIcon", images=fuelImg, userChange=False)
        self.lblFuelIcon.setClickEventHandler(self.changeFuelDisplay)
        self.lblFuel = Label(self.appWindow, "fuelPrediction")
        connStatusImg = [r"apps\python\ptracker\images\disconnected.png",
                         r"apps\python\ptracker\images\connected.png",
                         r"apps\python\ptracker\images\connected_setup.png",
                         r"apps\python\ptracker\images\connection_in_progress.png",]
        self.lblStrackerDisplay = EnumSelector(self.appWindow, ["","","",""], 0, ID="strackerStatus", images=connStatusImg, userChange=False)
        self.lblStrackerDisplay.setClickEventHandler(self.showSetupDialog)
        self.lblPitTime = Label(self.appWindow, "pitTimeDisplay")

        self.lbDisplay = LeaderboardDisplay(self.appWindow)
        self.lbDisplay.addClickCallback(self.driverClicked)
        self.lbMsgDisplay = MessageDisplay(self.msgWindow)

        self.lapStatDisplay = None
        self.showLapStatDisplay = self.LSD_NOCHANGE

        self.lastLayout = None
        self.dynamicDisplay = self.DYNDIS_LIVE
        self.raceOrQualLastN = None
        self.lastFuelIconChange = time.time()

        self.reinit()

        if config.GLOBAL.time_display_accuracy == config.ACCURACY_HUNDREDTH:
            self.format_time = format_time
        else:
            self.format_time = format_time_ms

    def setupPopupMenuLayout(self):
        self.popupFrame.read_ini_file(wstyle2frame[config.GLOBAL.window_style])
        minMarginX, minMarginY, optMarginX, optMarginY = self.popupFrame.margins()
        self.popupFrame.setBackgroundOpacity(0.7)
        WE = acFontCache.widthEstimator(config.LAYOUT_HOTLAP_LINE.font_size)
        self.popup_ly = GridLayout(
            x=0,
            y=0,
            width=None,
            height=None,
            gap=1,
            colWidths=[max(WE("Spectate"), WE("Confirm Ban"))],
            rowHeights=[25]*7,
            valign=GridLayout.VALIGN_TOP,
            halign=GridLayout.HALIGN_LEFT,
            marginX=optMarginX,
            marginY=optMarginY,
            expandingX=1)
        self.popup_ly.setZoom(config.GLOBAL.zoom_gui)
        self.popup_ly[(0,0)] = self.lblPmDriver
        self.popup_ly[(1,0)] = self.btnPmChat
        self.popup_ly[(2,0)] = self.btnPmFocus
        self.popup_ly[(3,0)] = self.btnPmKick
        self.popup_ly[(4,0)] = self.btnPmBan
        self.popup_ly[(5,0)] = self.btnPmSendSet
        self.popup_ly[(6,0)] = self.btnPmCancel
        self.popup_ly.setBackgroundElements(self.popupFrame)
        self.popup_ly.setActive(1)
        self.popup_ly.updateLayout()
        s = (self.popup_ly.getWidth()*self.popup_ly.getZoom(),self.popup_ly.getHeight()*self.popup_ly.getZoom())
        self.popupMenu.setSize(*s)

    def pmResetTexts(self):
        self.btnPmChat.setText('Start chat')
        self.btnPmFocus.setText('Spectate')
        self.btnPmKick.setText('Kick')
        self.btnPmBan.setText('Ban')
        self.btnPmSendSet.setText('Send Setup')
        self.btnPmCancel.setText('(hide)')

    def showPopupMenu(self, driver):
        self.lblPmDriver.setText(driver).setFontSize(config.LAYOUT_MESSAGE_BOARD.font_size).setFontAlignment('left').setTextLengthMode(Label.TM_ELLIPSIS).setFontColor(config.COLORS_LAP_STATS.ui_label_color)
        self.btnPmChat.setFontSize(config.LAYOUT_MESSAGE_BOARD.font_size).setFontAlignment('left').setTextLengthMode(Label.TM_NOCHECK).setFontColor(config.COLORS_LAP_STATS.ui_control_color)
        self.btnPmFocus.setFontSize(config.LAYOUT_MESSAGE_BOARD.font_size).setFontAlignment('left').setTextLengthMode(Label.TM_NOCHECK).setFontColor(config.COLORS_LAP_STATS.ui_control_color)
        self.btnPmKick.setFontSize(config.LAYOUT_MESSAGE_BOARD.font_size).setFontAlignment('left').setTextLengthMode(Label.TM_NOCHECK).setFontColor(config.COLORS_LAP_STATS.ui_control_color)
        self.btnPmBan.setFontSize(config.LAYOUT_MESSAGE_BOARD.font_size).setFontAlignment('left').setTextLengthMode(Label.TM_NOCHECK).setFontColor(config.COLORS_LAP_STATS.ui_control_color)
        self.btnPmSendSet.setFontSize(config.LAYOUT_MESSAGE_BOARD.font_size).setFontAlignment('left').setTextLengthMode(Label.TM_NOCHECK).setFontColor(config.COLORS_LAP_STATS.ui_control_color)
        self.btnPmCancel.setFontSize(config.LAYOUT_MESSAGE_BOARD.font_size).setFontAlignment('left').setTextLengthMode(Label.TM_NOCHECK).setFontColor(config.COLORS_LAP_STATS.ui_control_color)
        self.btnPmBan.setFontColor(config.COLORS_LAP_STATS.ui_control_color if self.ptracker.actKickBan.available(self.popupMenuCarId) else config.COLORS_LAP_STATS.ui_label_color)
        self.btnPmKick.setFontColor(config.COLORS_LAP_STATS.ui_control_color if self.ptracker.actKickBan.available(self.popupMenuCarId) else config.COLORS_LAP_STATS.ui_label_color)
        self.btnPmSendSet.setFontColor(config.COLORS_LAP_STATS.ui_control_color if self.ptracker.actSendSet.available(self.popupMenuCarId) else config.COLORS_LAP_STATS.ui_label_color)
        self.pmResetTexts()
        self.setupPopupMenuLayout()
        self.popupMenu.setActive(True, autoCloseSeconds = 10)

    def chatClickedDriver(self, *args):
        self.chat.start_chat('@' + self.ptracker.lapCollectors[self.popupMenuCarId].name + ": ")
        self.hidePopupMenu()

    def focusClickedDriver(self, *args):
        acsim.ac.focusCar(self.popupMenuCarId)
        self.hidePopupMenu()

    def kickClickedDriver(self, *args):
        if not self.ptracker.actKickBan.available(self.popupMenuCarId):
            return
        if self.btnPmKick.getText() == 'Kick':
            for i in range(1,self.popup_ly.getRowCount()):
                self.popup_ly[(i,0)].setText('')
            self.btnPmKick.setText('Cancel Kick')
            self.btnPmCancel.setText('Confirm Kick')
        else:
            self.pmResetTexts()

    def banClickedDriver(self, *args):
        if not self.ptracker.actKickBan.available(self.popupMenuCarId):
            return
        if self.btnPmBan.getText() == 'Ban':
            for i in range(1,self.popup_ly.getRowCount()):
                self.popup_ly[(i,0)].setText('')
            self.btnPmBan.setText('Cancel Ban')
            self.btnPmCancel.setText('Confirm Ban')
        else:
            self.pmResetTexts()

    def cancelClickedDriver(self, *args):
        t = self.btnPmCancel.getText()
        if t == 'Confirm Kick':
            self.ptracker.actKickBan.commit(self.popupMenuCarId, 0)
        elif t == 'Confirm Ban':
            self.ptracker.actKickBan.commit(self.popupMenuCarId, config.GLOBAL.initial_ban_days)
        self.hidePopupMenu()

    def sendSetClickedDriver(self, *args):
        if not self.ptracker.actSendSet.available(self.popupMenuCarId):
            return
        self.ptracker.actSendSet.commit(self.popupMenuCarId)
        self.hidePopupMenu()

    def hidePopupMenu(self, *args):
        self.popupMenu.setActive(False)

    def driverClicked(self, row, col):
        if self.popupMenu.active():
            return
        # row r has been clicked
        self.popupMenuCarId = self.displayedDrivers[row]
        lbl = self.lbDisplay.getLabel(row,col)
        if lbl is None or self.popupMenuCarId is None:
            return
        self.pmConfirmationCnt = (0,0)
        acsim.ac.setPositionTuple2(self.popupMenu.getAcID(), lbl.getPos(), self.appWindow.getPos())
        self.showPopupMenu(self.ptracker.lapCollectors[self.popupMenuCarId].name)

    def shutdown(self):
        img_scaler.shutdown()
        qtbrowser.shutdown()

    def reinit(self):
        if hasattr(self, 'race_ly'):
            self.setAllInactive()

        self.hotlapLineFrame.read_ini_file(wstyle2frame[config.GLOBAL.window_style])
        self.leaderboardFrame.read_ini_file(wstyle2frame[config.GLOBAL.window_style])
        self.messageboardFrame.read_ini_file(wstyle2frame[config.GLOBAL.window_style])

        self.hotlapLineFrame.setBackgroundOpacity(config.GLOBAL.background_opacity)
        self.leaderboardFrame.setBackgroundOpacity(config.GLOBAL.background_opacity)
        self.messageboardFrame.setBackgroundOpacity(config.GLOBAL.background_opacity)

        tframes = tstyle2frames[config.GLOBAL.leaderboard_style]
        for i,f in enumerate(self.leaderboardRowFrames):
            f.setBackgroundOpacity(config.GLOBAL.table_opacity).read_ini_file(tframes[i%len(tframes)])

        tframes = tstyle2frames[config.GLOBAL.messageboard_style]
        for i,f in enumerate(self.messageRowFrames):
            f.setBackgroundOpacity(config.GLOBAL.table_opacity).read_ini_file(tframes[i%len(tframes)])

        self.chat.reinit()

        # frames need to be setup'ed first
        minMarginX, minMarginY, optMarginX, optMarginY = self.hotlapLineFrame.margins()

        WE = acFontCache.widthEstimator(config.LAYOUT_HOTLAP_LINE.font_size)
        if config.GLOBAL.time_display_accuracy == config.ACCURACY_MILLI:
            delta_test_str = "+000.000"
            time_test_str = "00:00.000"
        else:
            delta_test_str = "+00.00"
            time_test_str = "00:00.00"
        rem_test_str = "000/000"

        self.hotlap_line_ly = GridLayout(
            x=0,
            y=0,
            width=None,
            height=None,
            gap=config.LAYOUT_HOTLAP_LINE.hotlap_line_gap,
            colWidths=[WE(time_test_str)+4 if config.LAYOUT_HOTLAP_LINE.show_live_delta else 0,
                       config.LAYOUT_HOTLAP_LINE.hotlap_row_height if config.LAYOUT_HOTLAP_LINE.show_validity else 0,
                       config.LAYOUT_HOTLAP_LINE.width_validity_reason,
                       WE(time_test_str)+4 if config.LAYOUT_HOTLAP_LINE.show_split_delta else 0,
                       WE(time_test_str)+4 if config.LAYOUT_HOTLAP_LINE.show_sector_delta else 0,
                       config.LAYOUT_HOTLAP_LINE.hotlap_row_height if config.LAYOUT_HOTLAP_LINE.show_stracker_display else 0,
                       WE(rem_test_str)+4 if config.LAYOUT_HOTLAP_LINE.show_session_display else 0,
                       config.LAYOUT_HOTLAP_LINE.hotlap_row_height if config.LAYOUT_HOTLAP_LINE.show_fuel_icon else 0,
                       WE("100.0")+4 if config.LAYOUT_HOTLAP_LINE.show_fuel_amount else 0,
                       ],
            rowHeights=[config.LAYOUT_HOTLAP_LINE.hotlap_row_height if config.LAYOUT_HOTLAP_LINE.show_cmp_values else 0,
                        0,
                        config.LAYOUT_HOTLAP_LINE.hotlap_row_height],
            valign=GridLayout.VALIGN_TOP,
            halign=GridLayout.HALIGN_CENTER,
            marginX=optMarginY,
            marginY=minMarginY,
            expandingX=config.LAYOUT.hexpand)

        minMarginX, minMarginY, optMarginX, optMarginY = self.leaderboardFrame.margins()
        rMinMarginX, rMinMarginY, rOptMarginX, rOptMarginY = self.leaderboardRowFrames[0].margins()
        lbMarginX = min(optMarginX, rMinMarginX+minMarginX)

        WE_laptime = acFontCache.widthEstimator(config.LAYOUT_RACE.font_size_laps)
        WE_delta = acFontCache.widthEstimator(config.LAYOUT_RACE.font_size_deltas)
        WE_pos = acFontCache.widthEstimator(config.LAYOUT_RACE.font_size_positions)
        WE_name = acFontCache.widthEstimator(config.LAYOUT_RACE.font_size_names)
        if config.LAYOUT.leaderboard_num_char > 0:
            name_width = WE_name("W"*config.LAYOUT.leaderboard_num_char)
        else:
            name_width = config.LAYOUT_RACE.width_name
        team_width = WE_name("W"*config.LAYOUT.team_num_char)

        self.race_ly_leaderboard = GridLayout(
            x=0,
            y=0,
            width=None,
            height=None,
            gap=config.LAYOUT_RACE.leaderboard_gap,
            colWidths=[WE_pos("00."),
                       WE_pos(chr(0x1f3c1)) if config.CONFIG_RACE.show_driver_status else 0,
                       config.LAYOUT_RACE.leaderboard_row_height if config.LAYOUT.leaderboard_show_badge else 0,
                       config.LAYOUT_RACE.leaderboard_row_height if config.LAYOUT.leaderboard_show_tyre else 0,
                       config.LAYOUT_RACE.leaderboard_row_height if config.LAYOUT.leaderboard_show_mr_rating else 0,
                       team_width,
                       name_width,
                       WE_pos("000")+4 if config.CONFIG_RACE.leaderboard_show_lap_count else 0,
                       WE_delta(delta_test_str)+4 if config.CONFIG_RACE.show_deltas else 0,
                       WE_laptime(time_test_str)+4 if config.CONFIG_RACE.lap_time_mode != config.LT_NONE else 0],
            rowHeights=[config.LAYOUT_RACE.leaderboard_row_height]*config.LAYOUT_RACE.leaderboard_num_rows,
            valign=GridLayout.VALIGN_TOP,
            halign=config.LAYOUT.halign,
            marginX=lbMarginX,
            marginY=optMarginY,
            expandingX=[6] if config.LAYOUT.hexpand else False)

        self.race_ly = GridLayout(
            x=0,
            y=0,
            width=None,
            height=None,
            gap=config.LAYOUT_RACE.space_to_hotlap_line,
            colWidths=None,
            rowHeights=None,
            valign=config.LAYOUT.valign,
            halign=config.LAYOUT.halign)

        WE_laptime = acFontCache.widthEstimator(config.LAYOUT_QUAL.font_size_laps)
        WE_delta = acFontCache.widthEstimator(config.LAYOUT_QUAL.font_size_deltas)
        WE_pos = acFontCache.widthEstimator(config.LAYOUT_QUAL.font_size_positions)
        WE_name = acFontCache.widthEstimator(config.LAYOUT_QUAL.font_size_names)
        if config.LAYOUT.leaderboard_num_char > 0:
            name_width = WE_name("W"*config.LAYOUT.leaderboard_num_char)
        else:
            name_width = config.LAYOUT_RACE.width_name

        self.qual_ly_leaderboard = GridLayout(
            x=0,
            y=0,
            width=None,
            height=None,
            gap=config.LAYOUT_QUAL.leaderboard_gap,
            colWidths=[WE_pos("00."),
                       WE_pos(chr(0x1f3c1)) if config.CONFIG_RACE.show_driver_status else 0,
                       config.LAYOUT_QUAL.leaderboard_row_height if config.LAYOUT.leaderboard_show_badge else 0,
                       config.LAYOUT_QUAL.leaderboard_row_height if config.LAYOUT.leaderboard_show_tyre else 0,
                       config.LAYOUT_RACE.leaderboard_row_height if config.LAYOUT.leaderboard_show_mr_rating else 0,
                       team_width,
                       name_width,
                       WE_laptime(time_test_str)+4],
            rowHeights=[config.LAYOUT_QUAL.leaderboard_row_height]*config.LAYOUT_QUAL.leaderboard_num_rows,
            valign=GridLayout.VALIGN_TOP,
            halign=config.LAYOUT.halign,
            marginX=lbMarginX,
            marginY=optMarginY,
            expandingX=[6] if config.LAYOUT.hexpand else False)

        self.qual_ly = GridLayout(
            x=0,
            y=0,
            width=None,
            height=None,
            gap=config.LAYOUT_QUAL.space_to_hotlap_line,
            colWidths=None,
            rowHeights=None,
            valign=config.LAYOUT.valign,
            halign=config.LAYOUT.halign)

        minMarginX, minMarginY, optMarginX, optMarginY = self.messageboardFrame.margins()
        self.messageboard_ly = GridLayout(
            x=0,
            y=0,
            width=None,
            height=None,
            gap=config.LAYOUT_QUAL.leaderboard_gap,
            colWidths=[config.LAYOUT_MESSAGE_BOARD.width],
            rowHeights=[config.LAYOUT_MESSAGE_BOARD.row_height]*config.LAYOUT_MESSAGE_BOARD.num_rows,
            valign=GridLayout.VALIGN_TOP,
            halign=config.LAYOUT.halign,
            marginX=optMarginX,
            marginY=optMarginY,
            expandingX=[0] if config.LAYOUT.hexpand else False)

        #self.hotlap_line_ly_container = GridLayout(
        #    valign=GridLayout.VALIGN_CENTER,halign=GridLayout.HALIGN_CENTER,x=0,y=0,width=None,height=None,gap=0,colWidths=None,rowHeights=None)
        #self.race_ly_leaderboard_container = GridLayout(
        #    valign=GridLayout.VALIGN_CENTER,halign=GridLayout.HALIGN_LEFT,x=0,y=0,width=None,height=None,gap=0,colWidths=None,rowHeights=None)
        #self.qual_ly_leaderboard_container = GridLayout(
        #    valign=GridLayout.VALIGN_CENTER,halign=GridLayout.HALIGN_LEFT,x=0,y=0,width=None,height=None,gap=0,colWidths=None,rowHeights=None)
        #self.messageboard_ly_container = GridLayout(
        #    valign=GridLayout.VALIGN_CENTER,halign=GridLayout.HALIGN_LEFT,x=0,y=0,width=None,height=None,gap=0,colWidths=None,rowHeights=None)

        #self.hotlap_line_ly_container[(0,0)] = self.hotlap_line_ly
        #self.race_ly_leaderboard_container[(0,0)] = self.race_ly_leaderboard
        #self.qual_ly_leaderboard_container[(0,0)] = self.qual_ly_leaderboard
        #self.messageboard_ly_container[(0,0)] = self.messageboard_ly

        if config.LAYOUT.valign in [GridLayout.VALIGN_CENTER, GridLayout.VALIGN_TOP]:
            k = 0
            if config.LAYOUT_HOTLAP_LINE.hotlap_row_height > 0:
                self.qual_ly[(k,0)] = self.race_ly[(k,0)] = self.hotlap_line_ly
                k += 1
            if config.CONFIG_RACE.show_leaderboard:
                self.race_ly[(k,0)] = self.race_ly_leaderboard
                self.qual_ly[(k,0)] = self.qual_ly_leaderboard
                k += 1
            if config.CONFIG_MESSAGE_BOARD.enabled and config.LAYOUT_MESSAGE_BOARD.attached:
                self.race_ly[(k,0)] = self.messageboard_ly
                self.qual_ly[(k,0)] = self.messageboard_ly
        else:
            k = 0
            if config.CONFIG_MESSAGE_BOARD.enabled and config.LAYOUT_MESSAGE_BOARD.attached:
                self.race_ly[(k,0)] = self.messageboard_ly
                self.qual_ly[(k,0)] = self.messageboard_ly
                k += 1
            if config.CONFIG_RACE.show_leaderboard:
                self.race_ly[(k,0)] = self.race_ly_leaderboard
                self.qual_ly[(k,0)] = self.qual_ly_leaderboard
                k += 1
            self.qual_ly[(k,0)] = self.race_ly[(k,0)] = self.hotlap_line_ly

        self.race_ly_leaderboard.setBackgroundElements(self.leaderboardFrame, self.leaderboardRowFrames)
        self.qual_ly_leaderboard.setBackgroundElements(self.leaderboardFrame, self.leaderboardRowFrames)
        self.messageboard_ly.setBackgroundElements(self.messageboardFrame, self.messageRowFrames)

        self.hotlap_line_ly[(2,0)] = self.lblLiveDelta
        self.hotlap_line_ly[(2,1)] = self.lblValidity
        self.hotlap_line_ly[(2,2)] = self.lblValidityReason
        self.hotlap_line_ly[(0,3)] = self.lblCmpSplit
        self.hotlap_line_ly[(2,3)] = self.lblSplitDelta
        self.hotlap_line_ly[(0,4)] = self.lblCmpSector
        self.hotlap_line_ly[(2,4)] = self.lblSectorDelta
        self.hotlap_line_ly[(2,5)] = self.lblStrackerDisplay
        self.hotlap_line_ly[(2,6)] = self.lblSessionDisplay
        self.hotlap_line_ly[(2,7)] = self.lblFuelIcon
        self.hotlap_line_ly[(2,8)] = self.lblFuel

        self.hotlap_line_ly.setBackgroundElements(self.hotlapLineFrame)

        numLeaderboardRows = max(config.LAYOUT_QUAL.leaderboard_num_rows,
                                 config.LAYOUT_RACE.leaderboard_num_rows)

        self.lbDisplay.expand(numLeaderboardRows)
        for i in range(numLeaderboardRows):
            self.race_ly_leaderboard[(i,0)] = self.lbDisplay.lblLBPositions[i]
            self.race_ly_leaderboard[(i,1)] = self.lbDisplay.lblLBDriverState[i]
            self.race_ly_leaderboard[(i,2)] = self.lbDisplay.lblLBBadge[i]
            self.race_ly_leaderboard[(i,3)] = self.lbDisplay.lblLBTyre[i]
            self.race_ly_leaderboard[(i,4)] = self.lbDisplay.lblMR[i]
            self.race_ly_leaderboard[(i,5)] = self.lbDisplay.lblLBTeam[i]
            self.race_ly_leaderboard[(i,6)] = self.lbDisplay.lblLBNames[i]
            self.race_ly_leaderboard[(i,7)] = self.lbDisplay.lblLBLaps[i]
            self.race_ly_leaderboard[(i,8)] = self.lbDisplay.lblLBDelta[i]
            self.race_ly_leaderboard[(i,9)] = self.lbDisplay.lblLBLapTime[i]

            self.qual_ly_leaderboard[(i,0)] = self.lbDisplay.lblLBPositions[i]
            self.qual_ly_leaderboard[(i,1)] = self.lbDisplay.lblLBDriverState[i]
            self.qual_ly_leaderboard[(i,2)] = self.lbDisplay.lblLBBadge[i]
            self.qual_ly_leaderboard[(i,3)] = self.lbDisplay.lblLBTyre[i]
            self.qual_ly_leaderboard[(i,4)] = self.lbDisplay.lblMR[i]
            self.qual_ly_leaderboard[(i,5)] = self.lbDisplay.lblLBTeam[i]
            self.qual_ly_leaderboard[(i,6)] = self.lbDisplay.lblLBNames[i]
            self.qual_ly_leaderboard[(i,7)] = self.lbDisplay.lblLBLapTime[i]

            l = self.lbDisplay.lblLBNames[i]
            if config.LAYOUT.leaderboard_num_char > 0:
                l.setMaxTextLength(config.LAYOUT.leaderboard_num_char)
                l.setTextLengthMode(Label.TM_CLIP)
            else:
                l.setMaxTextLength(None)
                l.setTextLengthMode(Label.TM_ELLIPSIS)

            l = self.lbDisplay.lblLBTeam[i]
            l.setMaxTextLength(config.LAYOUT.team_num_char)
            l.setTextLengthMode(Label.TM_CLIP)

        self.lbMsgDisplay.expand(config.LAYOUT_MESSAGE_BOARD.num_rows)
        for i in range(config.LAYOUT_MESSAGE_BOARD.num_rows):
            self.messageboard_ly[(i,0)] = self.lbMsgDisplay.lblMessage[i]
            self.lbMsgDisplay.lblMessage[i].setFontSize(config.LAYOUT_MESSAGE_BOARD.font_size).setFontAlignment('left')

        # set zoom value to all top level layouts
        self.qual_ly.setZoom(config.GLOBAL.zoom_gui)
        self.race_ly.setZoom(config.GLOBAL.zoom_gui)
        self.messageboard_ly.setZoom(config.GLOBAL.zoom_gui)
        self.lblSplitTime.setZoom(config.GLOBAL.zoom_gui)
        self.lblPitTime.setZoom(config.GLOBAL.zoom_gui)

        # determine maximum size of race, hotlap and qual layout
        h = []
        w = []
        for l in [self.qual_ly, self.race_ly]:
            l.setActive(True)
            l.updateLayout()
            h.append(l.getHeight())
            w.append(l.getWidth())
            self.setAllInactive()
        h = max(h)
        w = max(w)
        for l in [self.qual_ly, self.race_ly]:
            l.setSize(w,h,True)

        self.displayedMessageTimes = []
        self.displayedDrivers = []
        self.needsReInit = False

    def setAllInactive(self):
        self.qual_ly.setActive(False)
        self.race_ly.setActive(False)
        self.lblPitTime.setActive(False)
        self.lastLayout = None

    def setActiveLayout(self, lyt):
        lyt.setActive(True)
        lyt.updateLayout()
        s = (lyt.getWidth()*lyt.getZoom(),lyt.getHeight()*lyt.getZoom())
        self.appWindow.setSize(*s)
        if not config.LAYOUT_MESSAGE_BOARD.attached:
            self.messageboard_ly.setActive(True)
            self.messageboard_ly.updateLayout()
            s = (self.messageboard_ly.getWidth()*self.messageboard_ly.getZoom(),
                 self.messageboard_ly.getHeight()*self.messageboard_ly.getZoom())
            self.msgWindow.setSize(*s)
        else:
            self.msgWindow.setSize(1,1)
        #lyt.debug()

    def setupRaceLayout(self):
        self.setupRaceOrQualLayout(self.race_ly_leaderboard.getRowCount(), config.LAYOUT_RACE)
        self.setActiveLayout(self.race_ly)

    def setupQualLayout(self):
        self.setupRaceOrQualLayout(self.qual_ly_leaderboard.getRowCount(), config.LAYOUT_QUAL)
        self.setActiveLayout(self.qual_ly)

    def setupRaceOrQualLayout(self, n, cfg):
        self.dynamicDisplay = None
        # left most display
        self.lblSplitTime.setFontSize(config.LAYOUT_HOTLAP_LINE.font_size).setFontAlignment('left').setTextLengthMode(Label.TM_NOCHECK)
        self.lblPitTime.setFontSize(config.LAYOUT_HOTLAP_LINE.font_size).setFontAlignment('left').setTextLengthMode(Label.TM_NOCHECK)
        self.lblLiveDelta.setFontSize(config.LAYOUT_HOTLAP_LINE.font_size).setFontAlignment('left').setTextLengthMode(Label.TM_NOCHECK)
        # inner displayers
        self.lblSplitTime.setFontSize(config.LAYOUT_HOTLAP_LINE.font_size).setFontAlignment('right').setTextLengthMode(Label.TM_NOCHECK)
        self.lblCmpSplit.setFontSize(config.LAYOUT_HOTLAP_LINE.font_size).setFontAlignment('right')
        self.lblCmpSplit.setFontColor(config.COLORS_HOTLAP.cmp_time_color).setTextLengthMode(Label.TM_NOCHECK)
        self.lblSplitDelta.setFontSize(config.LAYOUT_HOTLAP_LINE.font_size).setFontAlignment('right').setTextLengthMode(Label.TM_NOCHECK)
        self.lblSectorTime.setFontSize(config.LAYOUT_HOTLAP_LINE.font_size).setFontAlignment('right').setTextLengthMode(Label.TM_NOCHECK)
        self.lblCmpSector.setFontSize(config.LAYOUT_HOTLAP_LINE.font_size).setFontAlignment('right')
        self.lblCmpSector.setFontColor(config.COLORS_HOTLAP.cmp_time_color).setTextLengthMode(Label.TM_NOCHECK)
        self.lblSectorDelta.setFontSize(config.LAYOUT_HOTLAP_LINE.font_size).setFontAlignment('right').setTextLengthMode(Label.TM_NOCHECK)
        self.lblValidity.setFontSize(config.LAYOUT_HOTLAP_LINE.font_size).setFontAlignment('center').setTextLengthMode(Label.TM_NOCHECK)
        self.lblValidityReason.setFontSize(config.LAYOUT_HOTLAP_LINE.font_size_reason).setFontAlignment('center')
        self.lblSessionDisplay.setFontSize(config.LAYOUT_HOTLAP_LINE.font_size).setFontAlignment('right').setTextLengthMode(Label.TM_CLIP)
        self.lblSessionDisplay.setFontColor(config.COLORS_HOTLAP.session_display_color).setMaxTextLength(len("000/000"))
        self.lblStrackerDisplay.setFontSize(config.LAYOUT_HOTLAP_LINE.font_size).setFontAlignment('center').setTextLengthMode(Label.TM_NOCHECK)
        self.lblFuel.setFontSize(config.LAYOUT_HOTLAP_LINE.font_size).setFontAlignment('center').setMaxTextLength(len("100.0")).setTextLengthMode(Label.TM_CLIP)
        for r in range(n):
            self.lbDisplay.lblLBPositions[r].setFontSize(cfg.font_size_positions).setFontAlignment('right').setTextLengthMode(Label.TM_NOCHECK)
            self.lbDisplay.lblLBDriverState[r].setFontSize(cfg.font_size_positions).setFontAlignment('left').setTextLengthMode(Label.TM_NOCHECK)
            self.lbDisplay.lblLBTeam[r].setFontSize(cfg.font_size_names).setFontAlignment('left').setTextLengthMode(Label.TM_CLIP)
            if config.LAYOUT.leaderboard_num_char > 0:
                tlMode = Label.TM_CLIP
            else:
                tlMode = Label.TM_ELLIPSIS
            self.lbDisplay.lblLBNames[r].setFontSize(cfg.font_size_names).setFontAlignment('left').setTextLengthMode(tlMode)
            self.lbDisplay.lblLBLaps[r].setFontSize(cfg.font_size_names).setFontAlignment('right').setTextLengthMode(Label.TM_CLIP)
            self.lbDisplay.lblLBDelta[r].setFontSize(cfg.font_size_deltas).setFontAlignment('right').setTextLengthMode(Label.TM_NOCHECK)
            self.lbDisplay.lblLBLapTime[r].setFontSize(cfg.font_size_laps).setFontAlignment('right').setTextLengthMode(Label.TM_NOCHECK)
        self.raceOrQualLastN = n
        self.setAllInactive()

    def getNIndicesAroundI(self, l, i, n, idxToShow):
        if len(l) <= n:
            return list(range(len(l)))
        res = set(idxToShow)
        res.add(i)
        z = -1
        while len(res) < n:
            if 0 <= i+z < len(l):
                res.add(i+z)
            if z < 0:
                z = -z
            else:
                z = -z-1
        return sorted(res)

    def raceItemCallback(self, lcIdx, racePosition, selfPosition):
        lc = self.ptracker.lapCollectors[lcIdx]
        name = lc.name
        badge = lc.badge
        delta = lc.delta_self
        lap_delta = lc.lap_delta
        tyre = lc.tyre
        mr = lc.mr_rating
        team = lc.team
        bestTimeInt = lc.bestLapTime
        lastTimeInt = lc.lastLapTime
        lapCount = lc.samples[-1].lapCount if len(lc.samples) > 0 else 0
        myassert(type(name) == type(""))
        if lap_delta == 0:
            # only for opponents
            if delta > 99990:
                delta = 99990
            elif delta < -99990:
                delta = -99990
            delta = self.format_time(delta, True)
        else:
            delta = "%+d L" % lap_delta
        if config.CONFIG_RACE.coloring_mode == config.CM_RACE_ORDER:
            if racePosition < selfPosition:
                dcolor = config.COLORS_RACE.race_order_before_color
            else:
                dcolor = config.COLORS_RACE.race_order_after_color
        else:
            if config.CONFIG_RACE.delta_reference == config.DR_EGO:
                good_color = config.COLORS_RACE.race_quicker_color
                bad_color = config.COLORS_RACE.race_slower_color
            else:
                bad_color = config.COLORS_RACE.race_quicker_color
                good_color = config.COLORS_RACE.race_slower_color
            deltaShown = lc.showCountdown > 0.0
            if lc.delta_self_2nd > 10 and deltaShown:
                dcolor = good_color
            elif lc.delta_self_2nd < -10 and deltaShown:
                dcolor = bad_color
            else:
                dcolor = config.COLORS_RACE.race_equal_color
        if config.CONFIG_RACE.delta_coloring == config.DC_ALL_COLUMNS:
            rcolor = dcolor
        elif config.CONFIG_RACE.delta_coloring == config.DC_NO_COLUMNS:
            dcolor = config.COLORS_RACE.race_equal_color
            rcolor = dcolor
        else:
            rcolor = config.COLORS_RACE.race_equal_color
        if racePosition == selfPosition:
            rcolor = config.COLORS_RACE.race_order_self_color
            if config.CONFIG_RACE.delta_coloring == config.DC_NO_COLUMNS:
                dcolor = rcolor
        if lc.showCountdown <= 0:
            delta = ""
        # transparent
        btcolor = (0.0, 0.0, 0.0, 0.0)
        bestTime = ''
        if config.CONFIG_RACE.lap_time_mode in [config.LT_ALL, config.LT_FASTEST]:
            bestTime = self.format_time(bestTimeInt, False)
            if not bestTimeInt is None and self.ptracker.sessionBestTime == bestTimeInt:
                btcolor = config.COLORS_RACE.best_time_color
            else:
                if config.CONFIG_RACE.lap_time_mode == config.LT_ALL:
                    btcolor = config.COLORS_RACE.norm_time_color
        else:
            bestTime = self.format_time(lastTimeInt, False)
            if config.CONFIG_RACE.lap_time_mode == config.LT_LAST:
                btcolor = config.COLORS_RACE.norm_time_color
                if not lastTimeInt is None:
                    if self.ptracker.sessionBestTime == lastTimeInt:
                        btcolor = config.COLORS_RACE.best_time_color
                    elif bestTimeInt == lastTimeInt:
                        btcolor = config.COLORS_RACE.pers_best_time_color
        if not lc.connected:
            dcolor = config.COLORS_RACE.notconnected
            btcolor = config.COLORS_RACE.notconnected
        return name, badge, delta, bestTime, dcolor, btcolor, tyre, mr, team, lapCount, rcolor, lc.carId, lc.raceFinished

    def raceItemIsBestTime(self, lcIdx):
        lc = self.ptracker.lapCollectors[lcIdx]
        bestTimeInt = lc.bestLapTime
        return not bestTimeInt is None and bestTimeInt == self.ptracker.sessionBestTime

    def qualItemCallback(self, resultIdx, racePosition, selfPosition):
        k = list(self.ptracker.results.keys())[resultIdx]
        lci = self.ptracker.results[k][2]
        lc = self.ptracker.lapCollectors[lci]
        name = k[1]
        if lc.name != name:
            lc = None
        if not lc is None:
            badge = lc.badge
            tyre = lc.tyre
            mr = lc.mr_rating
            team = lc.team
            carId = lc.carId
        else:
            carId = None
            badge = None
            tyre = None
            mr = None
            team = ""
        delta = ""
        r = self.ptracker.results[k]
        bestTimeInt = r[1][1]
        if (config.GLOBAL.lap_times_as_delta
                and not bestTimeInt is None
                and not self.ptracker.sessionBestTime is None
                and not self.ptracker.sessionBestTime == bestTimeInt):
            bestTime = self.format_time(bestTimeInt - self.ptracker.sessionBestTime, True)
        else:
            bestTime = self.format_time(bestTimeInt, False)
        if racePosition < selfPosition:
            dcolor = config.COLORS_QUAL.race_order_before_color
        elif racePosition > selfPosition:
            dcolor = config.COLORS_QUAL.race_order_after_color
        else:
            dcolor = config.COLORS_QUAL.race_order_self_color
        if not bestTimeInt is None and self.ptracker.sessionBestTime == bestTimeInt:
            btcolor = config.COLORS_QUAL.best_time_color
        else:
            btcolor = config.COLORS_QUAL.norm_time_color
        if lc is None or not lc.connected:
            dcolor = config.COLORS_RACE.notconnected
            btcolor = config.COLORS_RACE.notconnected
        return name, badge, delta, bestTime, dcolor, btcolor, tyre, mr, team, 0, dcolor, carId, False

    def qualItemIsBestTime(self, resultIdx):
        k = list(self.ptracker.results.keys())[resultIdx]
        r = self.ptracker.results[k]
        bestTimeInt = r[1][1]
        return not bestTimeInt is None and bestTimeInt == self.ptracker.sessionBestTime

    def renderRaceOrQual(self, itemCallback, itemIsBestTimeCallback, ly_leaderboard, ly):
        n = ly_leaderboard.getRowCount()
        layoutNeedsUpdate = False
        permutation = self.ptracker.opponents_order
        specId = acsim.ac.getFocusedCar()
        if itemCallback != self.qualItemCallback:
            lbIdxToCarId = lambda idx: permutation[idx] if idx >= 0 and idx < len(permutation) else None
            # race
            try:
                selfIndex = permutation.index(specId)
            except ValueError:
                try:
                    selfIndex = permutation.index(0)
                    acwarning("Cannot find spectated car in list, use ego car instead.")
                except ValueError:
                    selfIndex = 0
                    acwarning("Neither spectated nor ego car in list. Use first car.")
        else:
            lbIdxToCarIdMap = {}
            selfIndex = None
            for pidx,i in enumerate(permutation):
                k = list(self.ptracker.results.keys())[i]
                (guid,name,isAI) = k
                lcIdx = self.ptracker.results[k][2]
                lc = self.ptracker.lapCollectors[lcIdx]
                if lc.name != name:
                    # this is a player who already left the server, can't be spectated
                    continue
                carId = lc.carId
                lbIdxToCarIdMap[pidx] = carId
                if carId == specId and selfIndex is None:
                    selfIndex = pidx
            if selfIndex is None:
                try:
                    selfIndex = permutation.index(0)
                    acwarning("Cannot find spectated car in list, use ego car instead.")
                except ValueError:
                    selfIndex = 0
                    acwarning("Neither spectated nor ego car in list. Use first car.")
            lbIdxToCarId = lambda idx: lbIdxToCarIdMap.get(idx, None)
        idxToShow = set()
        idxToShow.add(selfIndex)
        if config.CONFIG_RACE.always_show_leader:
            idxToShow.add(0)
        specTP = self.ptracker.trackPositions.get(specId, None)
        nextCarI = None
        lastCarI = None
        next2CarI = None
        last2CarI = None
        for i in range(len(permutation)):
            ip = permutation[i]
            if config.CONFIG_RACE.lap_time_mode == config.LT_FASTEST and itemIsBestTimeCallback(ip):
                idxToShow.add(i)
                break
            carId = lbIdxToCarId(i)
            tp = self.ptracker.trackPositions.get(carId,None)
            if not tp is None and not specTP is None:
                if tp - specTP == 1 and config.CONFIG_RACE.show_cars_around_ego in [config.SCAE_NEXT, config.SCAE_NEXT_AND_LAST, config.SCAE_TWONEXT_AND_LAST, config.SCAE_TWONEXT_AND_TWO_LAST]:
                    if len(idxToShow) < n: idxToShow.add(i)
                    nextCarI = i
                elif tp - specTP == -1 and config.CONFIG_RACE.show_cars_around_ego in [config.SCAE_NEXT_AND_LAST, config.SCAE_TWONEXT_AND_LAST, config.SCAE_TWONEXT_AND_TWO_LAST]:
                    if len(idxToShow) < n: idxToShow.add(i)
                    lastCarI = i
                elif tp - specTP == 2 and config.CONFIG_RACE.show_cars_around_ego in [config.SCAE_TWONEXT_AND_LAST, config.SCAE_TWONEXT_AND_TWO_LAST]:
                    if len(idxToShow) < n: idxToShow.add(i)
                    next2CarI = i
                elif tp - specTP == -2 and config.CONFIG_RACE.show_cars_around_ego in [config.SCAE_TWONEXT_AND_TWO_LAST]:
                    if len(idxToShow) < n: idxToShow.add(i)
                    last2CarI = i
        indicesToShow = self.getNIndicesAroundI(permutation, selfIndex, n, idxToShow)
        lcShown = []
        row = 0
        if config.LAYOUT.valign == GridLayout.VALIGN_BOTTOM:
            row = n-max(1,len(indicesToShow))
        rowHeights = [0]*n
        for i in range(row, row+len(indicesToShow)):
            rowHeights[i] = config.LAYOUT_RACE.leaderboard_row_height
        if (len(indicesToShow),config.LAYOUT.valign) != self.raceOrQualLastN:
            if ly_leaderboard.updateRowHeights(rowHeights):
                layoutNeedsUpdate = True
            self.raceOrQualLastN = (len(indicesToShow),config.LAYOUT.valign)
        #logstr = ""
        self.displayedDrivers = [None]*n
        for i in indicesToShow:
            if i < 0 or i >= len(permutation):
                continue
            ip = permutation[i]
            name, badge, delta, bestTime, dcolor, btcolor, tyre, mr, team, lapCount, rcolor, carId, finished = itemCallback(ip, i, selfIndex)
            pos = "%d." % (i+1)
            driverState = ""
            if finished:
                driverState = chr(0x1f3c1) # checkered flag
            elif not carId is None:
                tp = self.ptracker.trackPositions.get(carId,None)
                if i == nextCarI:
                    driverState = chr(0x2191) # arrow upwards
                    if config.CONFIG_RACE.colorize_track_positions:
                        rcolor = config.COLORS_RACE.next_track_color
                elif i == lastCarI:
                    driverState = chr(0x2193) # arrow downwards
                    if config.CONFIG_RACE.colorize_track_positions:
                        rcolor = config.COLORS_RACE.last_track_color
                elif i == next2CarI:
                    driverState = chr(0x21c8) # double arrow upwards
                elif i == last2CarI:
                    driverState = chr(0x21ca) # double arrow downwards
                if acsim.ac.isCarInPit(carId):
                    driverState = "P"
                elif acsim.ac.isCarInPitlane(carId):
                    driverState = "p"
            self.lbDisplay.lblLBPositions[row].setText(pos).setFontColor(rcolor)
            self.lbDisplay.lblLBDriverState[row].setText(driverState).setFontColor(rcolor)
            self.lbDisplay.lblLBBadge[row].setBackgroundImage(badge)
            self.lbDisplay.lblLBTyre[row].setBackgroundImage(tyre)
            self.lbDisplay.lblMR[row].setBackgroundImage(mr)
            self.lbDisplay.lblLBTeam[row].setText(team).setFontColor(rcolor)
            self.lbDisplay.lblLBNames[row].setText(name).setFontColor(rcolor)
            self.lbDisplay.lblLBLaps[row].setText("%d" % lapCount).setFontColor(rcolor)
            self.lbDisplay.lblLBDelta[row].setText(delta).setFontColor(dcolor)
            self.lbDisplay.lblLBLapTime[row].setText(bestTime).setFontColor(btcolor)
            if itemCallback != self.qualItemCallback:
                self.displayedDrivers[row] = ip
            else:
                k = list(self.ptracker.results.keys())[ip]
                lcIdx = self.ptracker.results[k][2]
                lc = self.ptracker.lapCollectors[lcIdx]
                if lc.name != name:
                    # this is a player who already left the server, can't be spectated
                    self.displayedDrivers[row] = -1
                else:
                    self.displayedDrivers[row] = lc.carId
            #logstr += "%s %5s %s;" % (pos, name[:5], delta)
            row += 1
        if config.LAYOUT_HOTLAP_LINE.hotlap_row_height > 0:
            # hotlap line enabled ...
            if self.ptracker.pitLaneTimeShowCountdown > 0.0 and specId == 0:
                if not self.dynamicDisplay == self.DYNDIS_PIT:
                    self.dynamicDisplay = self.DYNDIS_PIT
                    self.lblSplitTime.setActive(False)
                    self.lblLiveDelta.setActive(False)
                    self.lblPitTime.setActive(True)
                    self.hotlap_line_ly[(2,0)] = self.lblPitTime
                    layoutNeedsUpdate = True
            elif self.ptracker.lapTimeShowCountdown > 0.0:
                if not self.dynamicDisplay == self.DYNDIS_SPLIT:
                    self.dynamicDisplay = self.DYNDIS_SPLIT
                    self.lblSplitTime.setActive(True)
                    self.lblLiveDelta.setActive(False)
                    self.lblPitTime.setActive(False)
                    self.hotlap_line_ly[(2,0)] = self.lblSplitTime
                    layoutNeedsUpdate = True
            elif self.ptracker.lapTimeShowCountdown <= 0.0:
                if not self.dynamicDisplay == self.DYNDIS_LIVE:
                    self.dynamicDisplay = self.DYNDIS_LIVE
                    self.lblSplitTime.setActive(False)
                    self.lblLiveDelta.setActive(True)
                    self.lblPitTime.setActive(False)
                    self.hotlap_line_ly[(2,0)] = self.lblLiveDelta
                    layoutNeedsUpdate = True
        rowHeights = [0]*config.LAYOUT_MESSAGE_BOARD.num_rows
        if config.CONFIG_MESSAGE_BOARD.enabled:
            msg = self.ptracker.messages
            current_time = time.time()
            if current_time - self.chat.scrollingStart < config.CHAT.scroll_timeout:
                tStart, tStop = self.chat.scrollPosition
                msg = list(filter(lambda x: tStart < x['timestamp'] < tStop, msg))
                if len(msg) > config.LAYOUT_MESSAGE_BOARD.num_rows:
                    msg = msg[-config.LAYOUT_MESSAGE_BOARD.num_rows:]
                if len(msg) == 0:
                    self.chat.scrollingStart = -100000
            else:
                if len(msg) > config.LAYOUT_MESSAGE_BOARD.num_rows:
                    msg = msg[-config.LAYOUT_MESSAGE_BOARD.num_rows:]
                if self.chat.mode == self.chat.MODE_TIMED:
                    min_time = current_time - config.CONFIG_MESSAGE_BOARD.time_to_show
                    msg = filter(lambda x: x['timestamp'] >= min_time, msg)
                elif self.chat.mode == self.chat.MODE_STATIC:
                    pass
                    # no filtering applies here

            # split into multi-line messages
            if config.LAYOUT.valign == GridLayout.VALIGN_BOTTOM:
                lbl = self.lbMsgDisplay.lblMessage[config.LAYOUT_MESSAGE_BOARD.num_rows - 1]
            else:
                lbl = self.lbMsgDisplay.lblMessage[0]

            new_msg = []
            for m in msg:
                splitted = lbl.split(m['text'])
                for i,s in enumerate(splitted):
                    new_msg.append( dict(text=s,
                                         leading=(i==0),
                                         color=m.get('color', (1.0,1.0,1.0,1.0)),
                                         timestamp=m['timestamp']) )
            msg = new_msg

            if len(msg) > config.LAYOUT_MESSAGE_BOARD.num_rows:
                msg = msg[-config.LAYOUT_MESSAGE_BOARD.num_rows:]

            if config.LAYOUT.valign == GridLayout.VALIGN_BOTTOM:
                row = config.LAYOUT_MESSAGE_BOARD.num_rows - len(msg)
            else:
                row = 0

            self.displayedMessageTimes = []
            for i,m in enumerate(msg):
                self.displayedMessageTimes.append(m['timestamp'])
                c = m['color']
                t = m['text']
                rowHeights[i+row] = config.LAYOUT_MESSAGE_BOARD.row_height
                self.lbMsgDisplay.lblMessage[i+row].setText(t).setFontColor(c)
                if m['leading']:
                    self.lbMsgDisplay.lblMessage[i+row].setFontAlignment('left')
                else:
                    self.lbMsgDisplay.lblMessage[i+row].setFontAlignment('right')

            if len(msg) == 0:
                self.messageboard_ly.setActive(False)
            else:
                self.messageboard_ly.setActive(True)
        if self.messageboard_ly.updateRowHeights(rowHeights):
            layoutNeedsUpdate = True
        if layoutNeedsUpdate:
            ly.updateLayout()
            if not config.LAYOUT_MESSAGE_BOARD.attached:
                self.messageboard_ly.updateLayout()
            #ly.debug()

    def doRenderHotlap(self):
        # update label about validity of lap
        if self.ptracker.lapValid:
            self.lblValidity.setValue(1)
            self.lblValidityReason.setText("")
        else:
            self.lblValidity.setValue(0)
            self.lblValidityReason.setText("%s" % self.ptracker.invalidReason)
        # update live comparison
        lcSpec = self.ptracker.lapCollectors[acsim.ac.getFocusedCar()]
        if len(lcSpec.samples) > 0:
            t = format_time_s(lcSpec.samples[-1].lapTime)
        else:
            t = format_time_s(None)
        self.lblLapTime.setText(t)
        t = self.format_time(self.ptracker.comparison, True)
        if not self.ptracker.comparison is None and self.ptracker.comparison > 10:
            color = config.COLORS_HOTLAP.slow_time_color
        elif not self.ptracker.comparison is None and self.ptracker.comparison < -10:
            color = config.COLORS_HOTLAP.fast_time_color
        else:
            color = config.COLORS_HOTLAP.equal_time_color
        self.lblLiveDelta.setText(t).setFontColor(color)
        # update split time
        splitDelta,splitCurr,splitBest,splitName = self.ptracker.splitComparison
        deltaText = self.format_time(splitDelta, True)
        splitText = self.format_time(splitCurr, False)
        splitCmpText = self.format_time(splitBest, False)
        if splitDelta is None or abs(splitDelta) < 10:
            color = config.COLORS_HOTLAP.equal_time_color
        elif splitDelta < 0:
            color = config.COLORS_HOTLAP.fast_time_color
        else:
            color = config.COLORS_HOTLAP.slow_time_color
        self.lblSplitDesc.setText(splitName)
        self.lblSplitTime.setText(splitText)
        self.lblCmpSplit.setText(splitCmpText)
        self.lblSplitDelta.setText(deltaText).setFontColor(color)
        #msg = splitName + ": " + splitText + "  " + deltaText + "    "
        # update sector time
        sectorDelta,sectorCurr,sectorBest,sectorName = self.ptracker.sectorComparison
        deltaText = self.format_time(sectorDelta, True)
        sectorText = self.format_time(sectorCurr, False)
        sectorCmpText = self.format_time(sectorBest, False)
        if sectorDelta is None or abs(sectorDelta) < 10:
            color = config.COLORS_HOTLAP.equal_time_color
        elif sectorDelta < 0:
            color = config.COLORS_HOTLAP.fast_time_color
        else:
            color = config.COLORS_HOTLAP.slow_time_color
        self.lblSectorDesc.setText(sectorName)
        self.lblSectorTime.setText(sectorText)
        self.lblCmpSector.setText(sectorCmpText)
        self.lblSectorDelta.setText(deltaText).setFontColor(color)
        pitLaneTime = self.ptracker.pitLaneTime
        self.lblPitTime.setText(self.format_time(pitLaneTime, True)).setFontColor(config.COLORS_HOTLAP.pit_time_color)
        #msg += sectorName + ": " + sectorText + "  " + deltaText
        # update session display
        nl = self.ptracker.sim_info_obj.graphics.numberOfLaps
        if nl > 0:
            lc = 0
            if len(lcSpec.samples) > 0:
                lc = lcSpec.samples[-1].lapCount
            if nl < 100:
                t = "%d / %d" % (lc+1, nl) # semantics are current lap number / total lap numbers
            else:
                t = "%d/%d" % (lc+1,nl)
        else:
            t = format_time_s(self.ptracker.sim_info_obj.graphics.sessionTimeLeft)
        self.lblSessionDisplay.setText(t)
        # update stracker connection display
        connStatus = 0
        if self.ptracker.hasRemoteConnection():
            setup_av = False
            for guid in self.ptracker.serverData:
                sd = self.ptracker.serverData[guid]
                if 'setup' in sd:
                    setup_av = True
                    break
            if setup_av:
                connStatus = 2
            else:
                connStatus = 1
        elif self.ptracker.isConnecting():
            connStatus = 3
        self.lblStrackerDisplay.setValue(connStatus)
        if config.LAYOUT_HOTLAP_LINE.fuel_display_mode == config.FAD_LAPS_LEFT:
            if self.ptracker.fuelPrediction is None:
                fuel_p = "-"
            else:
                fuel_p = "%.1f" % self.ptracker.fuelPrediction
            self.lblFuel.setText(fuel_p)
        elif config.LAYOUT_HOTLAP_LINE.fuel_display_mode == config.FAD_ADD_FUEL_NEEDED:
            if self.ptracker.additionalFuelNeeded is None:
                fuel_a = "-"
            else:
                fuel_a = "%d l" % math.ceil(self.ptracker.additionalFuelNeeded)
            self.lblFuel.setText(fuel_a)
        else:
            if self.ptracker.fuelLeft is None:
                fuel_l = "-"
            else:
                fuel_l = "%d l" % math.floor(self.ptracker.fuelLeft)
            self.lblFuel.setText(fuel_l)
        if self.ptracker.fuelPrediction is None or self.ptracker.fuelPrediction >= 3.1:
            self.lblFuelIcon.setValue(0)
        elif self.ptracker.fuelPrediction >= 1.1:
            self.lblFuelIcon.setValue(1)
        else:
            ct = time.time()
            if ct - self.lastFuelIconChange > 1.0:
                self.lastFuelIconChange = ct
                v = self.lblFuelIcon.getValue()
                v = (v%2)+1
                self.lblFuelIcon.setValue(v)

    def renderRace(self):
        if self.lastLayout != self.LY_RACE:
            self.setupRaceLayout()
            self.lastLayout = self.LY_RACE
        self.renderRaceOrQual(self.raceItemCallback, self.raceItemIsBestTime,
                              self.race_ly_leaderboard, self.race_ly)
        self.doRenderHotlap()

    def renderQual(self):
        if self.lastLayout != self.LY_QUAL:
            self.setupQualLayout()
            self.lastLayout = self.LY_QUAL
        self.renderRaceOrQual(self.qualItemCallback, self.qualItemIsBestTime,
                              self.qual_ly_leaderboard, self.qual_ly)
        self.doRenderHotlap()

    def render(self, sessionType):
        if self.needsReInit:
            self.reinit()

        if not self.ptracker.sqliteDB.dbReady():
            self.lblDBMsg.setPos(5, 5)
            self.lblDBMsg.setSize(5, 5)
            self.lblDBMsg.setFontColor((1.0, 0.3, 0.3, 1.0))
            self.lblDBMsg.setText("ptracker: Opening/migrating database. Please wait ...")
            self.lblDBMsg.setTextLengthMode(Label.TM_NOCHECK)
            self.lblDBMsg.setFontSize(14)
            self.lblDBMsg.setActive(True)
            return
        else:
            self.lblDBMsg.setActive(False)

        if config.LAYOUT_MESSAGE_BOARD.attached:
            p = self.appWindow.getPos()
            self.msgWindow.setPos(p[0], p[1])
            self.msgWindow.setActive(self.appWindow.renderingActive())
        if sessionType == self.SESSION_RACE:
            # race mode
            self.renderRace()
        else:
            self.renderQual()

    def createLapStatDisplay(self):
        if self.lapStatDisplay is None:
            self.lapStatDisplay = LapStatDisplay(self)

    def onClickApp(self, *args):
        ltc = self.lastTimeClicked
        self.lastTimeClicked = time.time()
        if not ltc is None and self.lastTimeClicked - ltc < 0.2:
            self.showLapStatDisplay = self.LSD_NORMALSHOW

    def changeFuelDisplay(self, *args):
        config.LAYOUT_HOTLAP_LINE.fuel_display_mode = (config.LAYOUT_HOTLAP_LINE.fuel_display_mode + 1) % 3
        self.ptracker.addMessage(text='Changed remaining fuel display to %s' % config.getFuelDisplayMode.getSettingStrings()[config.LAYOUT_HOTLAP_LINE.fuel_display_mode],
                                 color=(1.0,1.0,1.0,1.0), mtype=MTYPE_LOCAL_FEEDBACK)

    def showSetupDialog(self, *args):
        self.showLapStatDisplay = self.LSD_SETUPSHOW

    def update(self, dt):
        # It looks like sometimes AC doesn't like to create the ptracker-stats window
        # in the callback functions. Therefore, we try to create them in the main thread
        if self.showLapStatDisplay != self.LSD_NOCHANGE:
            try:
                self.createLapStatDisplay()
                if self.showLapStatDisplay == self.LSD_SETUPSHOW:
                    self.lapStatDisplay.setMode(self.lapStatDisplay.MODE_SETUPS)
                self.lapStatDisplay.appWindow.setActive(True)
            except:
                acerror(traceback.format_exc())
            self.showLapStatDisplay = self.LSD_NOCHANGE
        self.chat.update(dt)

