# -*- coding: utf-8 -*-

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
import traceback
import os.path
from ptracker_lib import acsim
from ptracker_lib import gui_helpers
from ptracker_lib.gui_helpers import AppWindow, Button, Label, GridLayout, Spinner, EnumSelector, MultiSelector, CheckBox, TableView, HorizontalPane
from ptracker_lib.gui_helpers import GenericTableDisplay, genericAcCallback, Frame, TabView, Centered, HorSep, VertSep, acFontCache, LineEdit
from ptracker_lib.qtbrowser import WebBrowser
from ptracker_lib.config import config
from ptracker_lib.helpers import *
from ptracker_lib.constants import *
from ptracker_lib.expand_ac import expand_ac
from ptracker_lib.ps_protocol import ProtocolHandler
from ptracker_lib.message_types import *
from ptracker_lib.gui_styles import *
from ptracker_lib import sound
from ptracker_lib.ac_ini_files import GamePlayIniFile

StatisticsDisplay = functools.partial(GenericTableDisplay,
    colToNameMappings=[["lblConNames", "btnConSendSetup", "btnConSaveSetup", "btnBan"],
                       ["lblComboInfo", "lblLapInfo", "lblSessionInfo", "lblAidInfo"],
                      ])

class ConfigOptionAdapter:
    def __init__(self, option_str, gui_elem, gui, onChange):
        self.option_str = option_str
        self.gui_elem = gui_elem
        self.gui_elem.addOnValueChangeListener(self.syncOption)
        if not type(onChange) in [type(()), type([])]:
            onChange = [onChange]
        self.onChange = onChange

    def syncGui(self):
        try:
            onChangeOrig = self.onChange
            self.onChange = []
            v = eval(self.option_str)
            v = self.option_to_gui_value(v)
            self.gui_elem.setValue(v)
        finally:
            self.onChange = onChangeOrig

    def syncOption(self, v):
        v = self.gui_value_to_option(v)
        exec(self.option_str + " = v")
        self.doOnChange()

    def doOnChange(self):
        for f in self.onChange:
            f()

    def option_to_gui_value(self, v):
        return v

    def gui_value_to_option(self, v):
        return v

class Percentage(ConfigOptionAdapter):
    def __init__(*args):
        ConfigOptionAdapter.__init__(*args)

    def option_to_gui_value(self, v):
        return v*100

    def gui_value_to_option(self, v):
        return v*0.01

class FalseTo0TrueToDefault(ConfigOptionAdapter):
    def __init__(self, *args):
        ConfigOptionAdapter.__init__(self, *args)
        ol = self.option_str.split(".")
        myassert(ol[0] == "config")
        self.section = ol[1]
        self.option = ol[2]

    def option_to_gui_value(self, v):
        return v != 0

    def gui_value_to_option(self, v):
        if v:
            v = config.sections[self.section][self.option][0]
        else:
            v = 0
        return v

class KeyboardShortcut:
    def __init__(self, option_str, gui_elem, gui, onChange):
        self.option_str = option_str
        self.gui_elem = gui_elem
        self.gui = gui
        self.gui_elem.setClickEventHandler(self.selectNewShortcut)
        myassert( len(onChange) == 0 )

    def syncGui(self):
        v = eval(self.option_str) # -> gives a list of strings
        v = " ".join(v)
        self.gui_elem.setText(v)

    def selectNewShortcut(self, *args):
        self.gui_elem.setText("(press shortcut key)")
        self.gui.chat.requestNewShortcut(self.newMsgShortcutCallback)

    def newMsgShortcutCallback(self, shortcut):
        v = " ".join(shortcut)
        self.gui_elem.setText(v)
        exec(self.option_str + " = shortcut")

class LapStatDisplay:
    # the different layouts (self.lastLayout values)
    LY_BROWSER = 2
    LY_CONFIG = 4
    LY_SETUPS = 5
    LY_LAP = 6
    LY_DATABASE = 7

    # the different GUI modes
    MODE_LOCAL_STATS = 1
    MODE_CONFIGURATION = 2
    MODE_REMOTE_STATS = 3
    MODE_SETUPS = 4
    MODE_LAP = 5
    MODE_DATABASE = 6

    # page allocations
    PAGE_FIRST = 0
    PAGE_UP = 1
    PAGE_ME = 2
    PAGE_DOWN = 3
    PAGE_LAST = 4

    # database page states
    DBPAGE_STATE_CLEAR = 0
    DBPAGE_STATE_COMPRESS_ALL = 1
    DBPAGE_STATE_COMPRESS_OTHER = 2
    DBPAGE_STATE_COMPRESS_SLOW = 3
    DBPAGE_STATE_WAIT = 4

    def __init__(self, gui):
        self.gui = gui
        self.ptracker = gui.ptracker

        self.needsReInit = False
        self.needsReLoad = False

        if GamePlayIniFile().allowAppsOverlapping() in [0, False]:
            self.ptracker.addMessage(text="Apps overlapping is disabled in options; consider to enable it in options/video/view",
                                     color=(1.0,0.3,0.3,1.0),
                                     mtype=MTYPE_LOCAL_FEEDBACK)

        self.mode = None
        self.lastLayout = None
        self.remote = config.GLOBAL.use_server_stats_if_available
        self.dbNavActive = False
        self.lapIdToDisplay = None
        self.dbPageState = None
        self.dbPageStateRes = lambda: None

        self.appWindow = AppWindow(ID="ptracker-stats")
        self.appWindow.addRenderCallback(self.render)
        self.appWindow.setActivateCallback(lambda: self.setMode(self.mode, force=True))

        self.appWindowFrame = Frame(self.appWindow)
        self.filterTableSeq = HorSep(self.appWindow)

        self.setupVertSeps = [VertSep(self.appWindow) for i in range(2)]

        self.browser = WebBrowser(self.appWindow)

        # will be updated later on
        self.tabView = TabView(self.appWindow,12,0,0,[],{})

        self.btnCleanupAutosave = Button(self.appWindow, 'cleanup', acButton = True).setText('Autosave cleanup').setClickEventHandler(self.cleanSetupsClicked).setFontColor(config.COLORS_LAP_STATS.ui_control_color)
        self.btnConnectToStracker = Button(self.appWindow, 'reconnect', acButton = True).setText('Manual connect').setClickEventHandler(self.ptracker.connectToStracker).setFontColor(config.COLORS_LAP_STATS.ui_control_color)

        self.tblSetupDeposit = TableView(self.appWindow,
                                         [dict(header="Server's Setup Deposit", width=200, maxTextLength=30), dict(header="", width=50), dict(header="", width=50)],
                                         config.LAYOUT_LAP_STATS.stat_table_row_height,
                                         10,
                                         config.LAYOUT_LAP_STATS.stat_table_gap)
        self.tblSetupDeposit.setStyle(backgroundOpacity = config.GLOBAL.background_opacity,
                                      fontSize = config.LAYOUT_SETUPS.font_size,
                                      #colorHeader = config.COLORS_LAP_STATS.ui_label_color,
                                      colorItem = config.COLORS_LAP_STATS.ui_control_color,
                                      colorActiveButton = config.COLORS_LAP_STATS.ui_control_color,
                                      colorInactiveButton = config.COLORS_LAP_STATS.ui_label_color)
        self.tblSetupDeposit.setItemClickedCallback(self.setupDepositClicked)
        self.tblSetupDeposit.addItem([{'text':"test (group::sender)",'color':config.COLORS_LAP_STATS.ui_label_color}, "Get", "Del"])

        self.tblGroups = TableView(self.appWindow,
                                   [dict(header="Server's Groups", width=150), dict(header="",width=80)],
                                   config.LAYOUT_LAP_STATS.stat_table_row_height,
                                   10,
                                   config.LAYOUT_LAP_STATS.stat_table_gap)
        self.tblGroups.setStyle(backgroundOpacity = config.GLOBAL.background_opacity,
                                      fontSize = config.LAYOUT_SETUPS.font_size,
                                      #colorHeader = config.COLORS_LAP_STATS.ui_label_color,
                                      colorItem = config.COLORS_LAP_STATS.ui_control_color,
                                      colorActiveButton = config.COLORS_LAP_STATS.ui_control_color,
                                      colorInactiveButton = config.COLORS_LAP_STATS.ui_label_color)
        self.tblGroups.setItemClickedCallback(self.publishToGroupClicked)
        self.tblGroups.addItem([{'text':"group name",'color':config.COLORS_LAP_STATS.ui_label_color}, "Publish Set"])

        # actions when options change
        def playsound(sound_file_setting = None):
            if sound_file_setting is None:
                sound_file = config.SOUND_FILE_CRASH
            else:
                sound_file = getattr(config.CONFIG_MESSAGE_BOARD, sound_file_setting)
            if not sound_file == config.SOUND_FILE_NONE:
                sound.playsound(sound_file, config.CONFIG_MESSAGE_BOARD.sound_volume)

        def guiAndSelfneedsReInit(self=self):
            self.needsReInit = True
            self.gui.needsReInit = True

        def guiNeedsReInit(self=self):
            self.gui.needsReInit = True

        def selfNeedsReLoad(self=self):
            self.needsReLoad = True

        def timeAccuracyChanged(self=self):
            if config.GLOBAL.time_display_accuracy == config.ACCURACY_HUNDREDTH:
                self.format_time = format_time
                self.gui.format_time = format_time
            else:
                self.format_time = format_time_ms
                self.gui.format_time = format_time_ms
            self.gui.needsReInit = True
            self.needsReInit = True

        def tempUnitChanged(self=self):
            setFormatUnits( "km/h" if config.GLOBAL.velocity_unit == config.UNIT_VEL_KMH else "mph",
                            "°C" if config.GLOBAL.temperature_unit == config.UNIT_TEMP_CELSIUS else "°F")

        def velUnitChanged(self=self):
            setFormatUnits( "km/h" if config.GLOBAL.velocity_unit == config.UNIT_VEL_KMH else "mph",
                            "°C" if config.GLOBAL.temperature_unit == config.UNIT_TEMP_CELSIUS else "°F")

        def enableMsgChat(self=self):
            self.gui.chat.update_keyboard_shortcuts()

        def logVerbosityChanged(self=self):
            from ptracker_lib import helpers
            helpers.restore_loggers(config.GLOBAL.log_verbosity)

        # sync gui to current settings
        timeAccuracyChanged()
        tempUnitChanged()
        velUnitChanged()
        logVerbosityChanged()

        # config gui elements
        options = [
            # name : (gui element, gui element's constructor arguments, config's attribute, [Translator=unity])
            ('Vert. Alignment'                       , (EnumSelector, (['top', 'center', 'bottom'],), 'config.LAYOUT.valign', None, guiNeedsReInit)),
            ('Hor. Alignment'                        , (EnumSelector, (['left', 'center', 'right'],), 'config.LAYOUT.halign', None, guiNeedsReInit)),
            ('Horizontally expand layout'            , (CheckBox, (), 'config.LAYOUT.hexpand', None, guiNeedsReInit)),
            ('Displayed time accuracy'               , (EnumSelector, (["hundredths","milliseconds"],), 'config.GLOBAL.time_display_accuracy', None, timeAccuracyChanged)),
            ('Unit for temperature display'          , (EnumSelector, (["°C","°F"],), 'config.GLOBAL.temperature_unit', None, tempUnitChanged)),
            ('Unit for velocity display'             , (EnumSelector, (["km/h","mph"],), 'config.GLOBAL.velocity_unit', None, velUnitChanged)),
            ('Window style'                          , (EnumSelector, (["Rounded frame", "Rounded", "Rect. frame", "none"],), 'config.GLOBAL.window_style', None, guiAndSelfneedsReInit)),
            ('Window transparency'                   , (Spinner, (50, 0, 100, 1), 'config.GLOBAL.background_opacity', Percentage, guiAndSelfneedsReInit)),
            ('Zoom ptracker window'                  , (Spinner, (100, 25, 400, 1), 'config.GLOBAL.zoom_gui', Percentage, guiNeedsReInit)),
            ('Zoom dialogs'                          , (Spinner, (100, 25, 400, 1), 'config.GLOBAL.zoom_dialog', Percentage, guiAndSelfneedsReInit)),
            ('FPS mode'                              , (EnumSelector, (["accuracy", "high fps"],), 'config.GLOBAL.fps_mode', None)),
            ('Log verbosity'                         , (EnumSelector, (["error","warning","info","debug","dump"],), 'config.GLOBAL.log_verbosity', None, logVerbosityChanged)),
            HorSep,
            ('Show hotlap line'                      , (CheckBox, (), 'config.LAYOUT_HOTLAP_LINE.hotlap_row_height', FalseTo0TrueToDefault, guiNeedsReInit)),
            ('Hotlap line show live delta'           , (CheckBox, (), 'config.LAYOUT_HOTLAP_LINE.show_live_delta', None, guiNeedsReInit)),
            ('Hotlap line show personal best'        , (CheckBox, (), 'config.LAYOUT_HOTLAP_LINE.show_cmp_values', None, guiNeedsReInit)),
            ('Hotlap line show split delta'          , (CheckBox, (), 'config.LAYOUT_HOTLAP_LINE.show_split_delta', None, guiNeedsReInit)),
            ('Hotlap line show sector delta'         , (CheckBox, (), 'config.LAYOUT_HOTLAP_LINE.show_sector_delta', None, guiNeedsReInit)),
            ('Hotlap line show lap validity'         , (CheckBox, (), 'config.LAYOUT_HOTLAP_LINE.show_validity', None, guiNeedsReInit)),
            ('Hotlap line show stracker connection'  , (CheckBox, (), 'config.LAYOUT_HOTLAP_LINE.show_stracker_display', None, guiNeedsReInit)),
            ('Hotlap line show session data'         , (CheckBox, (), 'config.LAYOUT_HOTLAP_LINE.show_session_display', None, guiNeedsReInit)),
            ('Hotlap line show fuel icon'            , (CheckBox, (), 'config.LAYOUT_HOTLAP_LINE.show_fuel_icon', None, guiNeedsReInit)),
            ('Hotlap line show fuel amount    '      , (CheckBox, (), 'config.LAYOUT_HOTLAP_LINE.show_fuel_amount', None, guiNeedsReInit)),
            ('Hotlap line fuel amount display'       , (EnumSelector, (["laps left", "add. fuel needed", "fuel left"],), 'config.LAYOUT_HOTLAP_LINE.fuel_display_mode', None)),
            VertSep,
            ('Show leaderboard'                      , (CheckBox, (), 'config.CONFIG_RACE.show_leaderboard', None, guiNeedsReInit)),
            ('Show driver status'                    , (CheckBox, (), 'config.CONFIG_RACE.show_driver_status', None, guiNeedsReInit)),
            ('Lap times in race mode'                , (EnumSelector, (["fastest only", "none", "best laps", "last laps"],), 'config.CONFIG_RACE.lap_time_mode', None, guiNeedsReInit)),
            ('Lap times as delta'                    , (CheckBox, (), 'config.GLOBAL.lap_times_as_delta')),
            ('Show lap count in race mode'           , (CheckBox, (), 'config.CONFIG_RACE.leaderboard_show_lap_count', None, guiNeedsReInit)),
            ('Always show race leader'               , (CheckBox, (), 'config.CONFIG_RACE.always_show_leader')),
            ('Show cars based on track pos'          , (EnumSelector, (["none", "next", "next, last", "next 2, last", "next 2, last 2"],), 'config.CONFIG_RACE.show_cars_around_ego', None)),
            ('Colorize drivers around you'           , (CheckBox, (), 'config.CONFIG_RACE.colorize_track_positions', None)),
            ('Show badge icon'                       , (CheckBox, (), 'config.LAYOUT.leaderboard_show_badge', None, guiNeedsReInit)),
            ('Race delta live sync'                  , (CheckBox, (), 'config.CONFIG_RACE.sync_live')),
            ('Race delta sync interval'              , (Spinner, (0, 0, 20, 0.5), 'config.CONFIG_RACE.sync_interval')),
            ('Race delta reference'                  , (EnumSelector, (["ego", "leader"],), 'config.CONFIG_RACE.delta_reference')),
            ('Delta coloring'                        , (EnumSelector, (["delta column", "all columns", "none"],), 'config.CONFIG_RACE.delta_coloring')),
            ('Show race delta'                       , (CheckBox, (), 'config.CONFIG_RACE.show_deltas', None, guiNeedsReInit)),
            ('Show tyres'                            , (CheckBox, (), 'config.LAYOUT.leaderboard_show_tyre', None, guiNeedsReInit)),
            ('Show MR rating (thanks Minolin!)'      , (CheckBox, (), 'config.LAYOUT.leaderboard_show_mr_rating', None, guiNeedsReInit)),
            ('Number of team characters (0->disable)', (Spinner, (0, 0, 30, 1), 'config.LAYOUT.team_num_char', None, guiNeedsReInit)),
            ('Leader board style'                    , (EnumSelector, (["orange/green", "gray", "green", "blue", "red", "yellow", "none"],), 'config.GLOBAL.leaderboard_style', None, guiNeedsReInit)),
            ('Number of leaderboard name characters' , (Spinner, (0, 0, 30, 1), 'config.LAYOUT.leaderboard_num_char', None, guiNeedsReInit)),
            ('Table transparency'                    , (Spinner, (0, 0, 100, 1), 'config.GLOBAL.table_opacity', Percentage, guiAndSelfneedsReInit)),
            ('Number of displayed items (qualify)'   , (Spinner, (3, 3, 30, 1), 'config.LAYOUT_QUAL.leaderboard_num_rows', None, guiNeedsReInit)),
            ('Number of displayed items (race)'      , (Spinner, (3, 3, 30, 1), 'config.LAYOUT_RACE.leaderboard_num_rows', None, guiNeedsReInit)),
            HorSep,
            ('Shortcut for opening edit'             , (Button, (), 'config.CHAT.shortcut_talk', KeyboardShortcut)),
            ('Shortcut for changing display mode'    , (Button, (), 'config.CHAT.shortcut_mode', KeyboardShortcut)),
            ('Shortcut for scrolling up'             , (Button, (), 'config.CHAT.shortcut_pgup', KeyboardShortcut)),
            ('Shortcut for scrolling down'           , (Button, (), 'config.CHAT.shortcut_pgdown', KeyboardShortcut)),
            ('Timeout for leaving scrolling'         , (Spinner, (20, 5, 60, 1), 'config.CHAT.scroll_timeout')),
            ('Edit position'                         , (EnumSelector, (["manual", "center", "top", "bottom"],), 'config.CHAT.text_input_auto_position', None, self.gui.chat.repositionEditor)),
            ('Directly send shortcut messages'       , (CheckBox, (), 'config.CHAT.msg_shortcut_send_direct')),
        ]
        for n in range(1,10):
            cfg = "config.CHAT.msg_%d_shortcut" % n
            cfg_msg = "config.CHAT.msg_%d_text" % n
            options.append(
                ((LineEdit, (), cfg_msg, None, selfNeedsReLoad), (Button, (), cfg, KeyboardShortcut))
            )
        soundSettings = config.getSoundFile.getSettingStrings()
        options.extend([
            VertSep,
            ('Enable message board'                  , (CheckBox, (), 'config.CONFIG_MESSAGE_BOARD.enabled', None, guiNeedsReInit)),
            ('Attach message board to ptracker GUI'  , (CheckBox, (), 'config.LAYOUT_MESSAGE_BOARD.attached', None, guiNeedsReInit)),
            ('Minimum width of message board'        , (Spinner, (150, 150, 500, 10), 'config.LAYOUT_MESSAGE_BOARD.width', None, guiNeedsReInit)),
            ('Message display time [s]'              , (Spinner, (1, 1, 60, 1), 'config.CONFIG_MESSAGE_BOARD.time_to_show')),
            ('Message board style'                   , (EnumSelector, (["orange/green", "gray", "green", "blue", "red", "yellow", "none"],), 'config.GLOBAL.messageboard_style')),
            ('Number of message lines'               , (Spinner, (1, 1, 30, 1), 'config.LAYOUT_MESSAGE_BOARD.num_rows', None, guiNeedsReInit)),
            ('Sound volume (0 -> disabled)'          , (Spinner, (0, 0, 100, 1), 'config.CONFIG_MESSAGE_BOARD.sound_volume', Percentage, playsound)),
            ('Chat filter'                           , (LineEdit, (), 'config.CHAT.chat_filter', None, selfNeedsReLoad)),
            HorSep,
            (''                                      , 'Enabled', 'Sound'),
            ('Enter/leave messages'          , (CheckBox, (), 'config.CONFIG_MESSAGE_BOARD.enable_msg_enter_leave'),
                            (EnumSelector, (soundSettings,) , 'config.CONFIG_MESSAGE_BOARD.sound_file_enter_leave', None, functools.partial(playsound, sound_file_setting="sound_file_enter_leave"))),
            ('Server best lap messages'      , (CheckBox, (), 'config.CONFIG_MESSAGE_BOARD.enable_msg_best_lap'),
                            (EnumSelector, (soundSettings,) , 'config.CONFIG_MESSAGE_BOARD.sound_file_best_lap', None, functools.partial(playsound, sound_file_setting="sound_file_best_lap"))),
            ('Local pb messages'             , (CheckBox, (), 'config.CONFIG_MESSAGE_BOARD.enable_msg_local_pb'),
                            (EnumSelector, (soundSettings,) , 'config.CONFIG_MESSAGE_BOARD.sound_file_local_pb', None, functools.partial(playsound, sound_file_setting="sound_file_local_pb"))),
            ('Local feedback messages'       , (CheckBox, (), 'config.CONFIG_MESSAGE_BOARD.enable_msg_local_feedback'),
                            (EnumSelector, (soundSettings,) , 'config.CONFIG_MESSAGE_BOARD.sound_file_local_feedback', None, functools.partial(playsound, sound_file_setting="sound_file_local_feedback"))),
            ('Save setup messages'           , (CheckBox, (), 'config.CONFIG_MESSAGE_BOARD.enable_msg_setup_saved'),
                            (EnumSelector, (soundSettings,) , 'config.CONFIG_MESSAGE_BOARD.sound_file_setup_saved', None, functools.partial(playsound, sound_file_setting="sound_file_setup_saved"))),
            ('Setup receive messages'        , (CheckBox, (), 'config.CONFIG_MESSAGE_BOARD.enable_msg_setup_rcv'),
                            (EnumSelector, (soundSettings,) , 'config.CONFIG_MESSAGE_BOARD.sound_file_setup_rcv', None, functools.partial(playsound, sound_file_setting="sound_file_setup_rcv"))),
            ('Race finished messages'        , (CheckBox, (), 'config.CONFIG_MESSAGE_BOARD.enable_msg_race_finished'),
                            (EnumSelector, (soundSettings,) , 'config.CONFIG_MESSAGE_BOARD.sound_file_race_finished', None, functools.partial(playsound, sound_file_setting="sound_file_race_finished"))),
            ('Checksum error messages'       , (CheckBox, (), 'config.CONFIG_MESSAGE_BOARD.enable_msg_checksum_errors'),
                            (EnumSelector, (soundSettings,) , 'config.CONFIG_MESSAGE_BOARD.sound_file_checksum_errors', None, functools.partial(playsound, sound_file_setting="sound_file_checksum_errors"))),
            ('Collision messages'            , (CheckBox, (), 'config.CONFIG_MESSAGE_BOARD.enable_msg_collision'),
                            (EnumSelector, (soundSettings,) , 'config.CONFIG_MESSAGE_BOARD.sound_file_collision', None, functools.partial(playsound, sound_file_setting="sound_file_collision"))),
            ('Chat messages (no to disable chat)', (CheckBox, (), 'config.CONFIG_MESSAGE_BOARD.enable_msg_chat', None, enableMsgChat),
                            (EnumSelector, (soundSettings,) , 'config.CONFIG_MESSAGE_BOARD.sound_file_chat', None, functools.partial(playsound, sound_file_setting="sound_file_chat"))),
            HorSep,
            ('Number of displayed items (lap statistics' , (Spinner, (3, 3, 30, 1), 'config.LAYOUT_LAP_STATS.stat_num_rows', None, guiAndSelfneedsReInit)),
            ('Prefer server connection if available' , (CheckBox, (), 'config.GLOBAL.use_server_stats_if_available')),
            ('Automatically save pb sets', (CheckBox, (), 'config.GLOBAL.auto_save_pb_setups')),
            ('Statistics boards style', (EnumSelector, (["orange/green", "gray", "green", "blue", "red", "yellow", "none"],), 'config.GLOBAL.statboard_style', None, guiAndSelfneedsReInit)),
        ])
        self.options = []
        for line in options:
            if line in [HorSep, VertSep]:
                self.options.append(line(self.appWindow))
            elif type(line) == type(()):
                myassert(len(line) in [2,3])
                res = []
                for opt in line:
                    if type(opt) == type(""):
                        res.append(Label(self.appWindow).setText(opt).setFontColor(config.COLORS_LAP_STATS.ui_label_color))
                    else:
                        cl = opt[0]
                        constr_args = opt[1]
                        config_str = opt[2]
                        if len(opt) >= 4:
                            adapter = opt[3]
                        else:
                            adapter = None
                        if adapter is None:
                            adapter = ConfigOptionAdapter
                        if len(opt) >= 5:
                            onChange = opt[4]
                        else:
                            onChange = []
                        gui_elem = cl(self.appWindow, *constr_args).setFontColor(config.COLORS_LAP_STATS.ui_control_color)
                        res.append( (gui_elem, adapter(config_str, gui_elem, self.gui, onChange)) )
                myassert( len(res) in [2,3] )
                self.options.append(tuple(res))

        # shortcut buttons
        self.btnLoadDefault = Button(self.appWindow, acButton=True).setText("Restore defaults").setClickEventHandler(self.loadDefaultConfig).setFontColor(config.COLORS_LAP_STATS.ui_control_color)
        self.btnFpsOptimized = Button(self.appWindow, acButton=True).setText("FPS Optimized").setClickEventHandler(self.fpsOptimizedSettings).setFontColor(config.COLORS_LAP_STATS.ui_control_color)
        self.configHorSep = HorSep(self.appWindow)

        # config finish

        # database buttons
        self.btnDbCompressSlow = Button(self.appWindow).setText("Delete delta infos of slow laps ...").setClickEventHandler(self.dbCompressSlowClicked).setFontColor(config.COLORS_LAP_STATS.ui_control_color)
        self.btnDbCompressAll = Button(self.appWindow).setText("Delete delta infos of all laps ...").setClickEventHandler(self.dbCompressAllClicked).setFontColor(config.COLORS_LAP_STATS.ui_control_color)
        self.btnDbCompressOther = Button(self.appWindow).setText("Delete delta infos of other players ...").setClickEventHandler(self.dbCompressOtherClicked).setFontColor(config.COLORS_LAP_STATS.ui_control_color)
        self.btnDbClear = Button(self.appWindow).setText("Clear whole database ...").setClickEventHandler(self.dbClearClicked).setFontColor(config.COLORS_LAP_STATS.ui_control_color)
        self.lblDbWarning = Label(self.appWindow).setText("").setFontColor(config.COLORS_LAP_STATS.ui_label_color)
        self.btnDbOk = Button(self.appWindow).setText("OK").setClickEventHandler(self.dbOKClicked).setFontColor(config.COLORS_LAP_STATS.ui_control_color)
        self.btnDbCancel = Button(self.appWindow).setText("Cancel").setClickEventHandler(self.dbCancelClicked).setFontColor(config.COLORS_LAP_STATS.ui_control_color)

        self.statRowFrames = []
        self.lbDisplay = StatisticsDisplay(self.appWindow)
        self.lbDisplay.addClickCallback(self.lbDisplayClicked)

        self.limit = [0, config.LAYOUT_LAP_STATS.stat_num_rows-1]
        self.bankick_map = {}
        self.bankick_confirm = {}
        self.setup_guids = {}
        self.displayedDepositID = None

        self.reload_config()
        self.reinit()

    def reload_config(self):
        # this function synchronizes all dialog elements to the current config
        # called after setting presets
        for line in self.options:
            if type(line) == type(()): # ignore seperators
                for opt in line:
                    if type(opt) == type(()):
                        adapter = opt[1]
                        adapter.syncGui()
        self.needsReLoad = False

    def reinit(self):
        if hasattr(self, 'config_ly'):
            self.setAllInactive()

        oldMode = self.mode

        self.appWindowFrame.read_ini_file(wstyle2frame[config.GLOBAL.window_style])
        self.appWindowFrame.setBackgroundOpacity(config.GLOBAL.background_opacity)

        WE = acFontCache.widthEstimator(config.LAYOUT_LAP_STATS.font_size)

        self.local_stat_ly = GridLayout(
            x=0,
            y=0,
            width=None,
            height=None,
            gap=config.LAYOUT_LAP_STATS.stat_table_gap,
            colWidths=[1500],
            rowHeights=[800],
            valign=GridLayout.VALIGN_TOP,
            halign=GridLayout.HALIGN_LEFT)

        self.remote_stat_ly = GridLayout(
            x=0,
            y=0,
            width=None,
            height=None,
            gap=config.LAYOUT_LAP_STATS.stat_table_gap,
            colWidths=[1500],
            rowHeights=[800],
            valign=GridLayout.VALIGN_TOP,
            halign=GridLayout.HALIGN_LEFT)

        self.setups_ly_control = GridLayout(
            x=0,
            y=0,
            width=None,
            height=None,
            gap=config.LAYOUT_LAP_STATS.stat_table_gap,
            colWidths=[config.LAYOUT_LAP_STATS.button_width]*2,
            rowHeights=[config.LAYOUT_LAP_STATS.button_height],
            valign=GridLayout.VALIGN_TOP,
            halign=GridLayout.HALIGN_LEFT)

        self.setups_ly_table = GridLayout(
            x=0,
            y=0,
            width=None,
            height=None,
            gap=config.LAYOUT_LAP_STATS.stat_table_gap,
            colWidths=[config.LAYOUT_SETUPS.width_name,
                       config.LAYOUT_SETUPS.width_send_set,
                       config.LAYOUT_SETUPS.width_save_set,
                       config.LAYOUT_SETUPS.width_bankick],
            rowHeights=[config.LAYOUT_LAP_STATS.stat_table_row_height]*(len(self.ptracker.lapCollectors)+1),
            valign=GridLayout.VALIGN_TOP,
            halign=GridLayout.HALIGN_LEFT)

        minMarginX,minMarginY,optMarginX,optMarginY = self.appWindowFrame.margins()
        self.setups_ly_hor = GridLayout(
            x=0,
            y=0,
            width=None,
            height=None,
            gap = config.LAYOUT_LAP_STATS.control_table_gap,
            colWidths = None,
            rowHeights = None,
            valign = GridLayout.VALIGN_TOP,
            halign = GridLayout.HALIGN_LEFT,
            marginX = optMarginX,
            marginY = optMarginY
            )

        self.lapdbpage_table_ly = GridLayout(
            x=0,
            y=0,
            width=None,
            height=None,
            gap=config.LAYOUT_LAP_STATS.control_table_gap,
            colWidths=[config.LAYOUT_DBPAGE.width_btns],
            rowHeights=[config.LAYOUT_LAP_STATS.button_height]*7,
            valign=GridLayout.VALIGN_TOP,
            halign=GridLayout.HALIGN_LEFT)

        self.lapdbpage_okcancel_ly = GridLayout(
            x=0,
            y=0,
            width=config.LAYOUT_DBPAGE.width_btns,
            height=None,
            gap=config.LAYOUT_LAP_STATS.control_table_gap,
            colWidths=[config.LAYOUT_DBPAGE.width_okcancel]*2,
            rowHeights=[config.LAYOUT_LAP_STATS.button_height],
            valign=GridLayout.VALIGN_TOP,
            halign=GridLayout.HALIGN_CENTER)

        self.lapdbpage_ly = GridLayout(
            x=0,
            y=0,
            width=None,
            height=None,
            gap=config.LAYOUT_LAP_STATS.space_to_control_area,
            colWidths=None,
            rowHeights=None,
            valign=GridLayout.VALIGN_TOP,
            halign=GridLayout.HALIGN_LEFT,
            marginX = optMarginX,
            marginY = optMarginY)

        self.setups_ly = GridLayout(
            x=0,
            y=0,
            width=None,
            height=None,
            gap=config.LAYOUT_LAP_STATS.space_to_control_area,
            colWidths=None,
            rowHeights=None,
            valign=GridLayout.VALIGN_TOP,
            halign=GridLayout.HALIGN_LEFT,
            marginX = optMarginX,
            marginY = optMarginY)

        self.setups_ly[(1,0)] = self.setups_ly_control
        self.setups_ly[(2,0)] = self.setups_ly_hor
        self.setups_ly_hor[(0,0)] = self.setups_ly_table
        self.setups_ly_hor[(0,1)] = self.setupVertSeps[0]
        self.setups_ly_hor[(0,2)] = self.tblSetupDeposit
        self.setups_ly_hor[(0,3)] = self.setupVertSeps[1]
        self.setups_ly_hor[(0,4)] = self.tblGroups
        self.lapdbpage_ly[(1,0)] = self.lapdbpage_table_ly
        self.lapdbpage_ly[(2,0)] = self.lapdbpage_okcancel_ly

        self.setups_ly_control[(0,0)] = self.btnCleanupAutosave
        self.setups_ly_control[(0,1)] = self.btnConnectToStracker

        self.config_ly = GridLayout(
            x=0,
            y=0,
            width=None,
            height=None,
            gap=10,
            colWidths=None,
            rowHeights=None,
            valign=GridLayout.VALIGN_TOP,
            halign=GridLayout.HALIGN_LEFT,
            marginX = optMarginX,
            marginY = optMarginY)

        config_base_ly = GridLayout(0,0,None,None,10,None,None,GridLayout.VALIGN_TOP,GridLayout.HALIGN_LEFT)
        config_btn_ly = GridLayout(0,0,None,None,10,[config.LAYOUT_CONFIG.width_controls]*2,[config.LAYOUT_LAP_STATS.button_height+4],GridLayout.VALIGN_TOP,GridLayout.HALIGN_LEFT)

        self.config_ly[(0,0)] = config_base_ly
        self.config_ly[(1,0)] = self.configHorSep
        self.config_ly[(2,0)] = config_btn_ly

        config_btn_ly[(0,0)] = self.btnLoadDefault
        config_btn_ly[(0,1)] = self.btnFpsOptimized

        currentHLayout = GridLayout(0,0,None,None,10,None,None,GridLayout.VALIGN_TOP,GridLayout.HALIGN_LEFT)
        config_base_ly[(0,0)] = currentHLayout
        currentHIdx = 0
        cnt = 0
        items = []
        nCols = 2
        widths = []
        for i,o in enumerate(self.options + [None]):
            if type(o) in [VertSep, HorSep, type(None)]:
                hPiece = GridLayout(0,0,None,None,2,
                                    [config.LAYOUT_CONFIG.width_labels] + [config.LAYOUT_CONFIG.width_controls]*(nCols-1),
                                    [config.LAYOUT_LAP_STATS.button_height]*len(items),
                                    GridLayout.VALIGN_TOP, GridLayout.HALIGN_LEFT)
                hPiece.setItems(items)
                currentHLayout[(cnt*2,0)] = hPiece
                if type(o) in [HorSep, type(None)]:
                    currentHLayout[(cnt*2+1,0)] = o
                    cnt += 2
                if type(o) == VertSep:
                    config_base_ly[(0,currentHIdx+1)] = o
                    currentHIdx += 2
                    currentHLayout = GridLayout(0,0,None,None,10,None,None,GridLayout.VALIGN_TOP,GridLayout.HALIGN_LEFT)
                    config_base_ly[(0,currentHIdx)] = currentHLayout
                    cnt = 0
                items = []
            else:
                line = []
                for k,item in enumerate(o):
                    item = item[0] if type(item) == type(()) else item
                    line.append(item)
                nCols = max(nCols, len(line))
                items.append(line)

        self.lapdbpage_table_ly[(0,0)] = self.btnDbCompressSlow
        self.lapdbpage_table_ly[(1,0)] = self.btnDbCompressOther
        self.lapdbpage_table_ly[(2,0)] = self.btnDbCompressAll
        self.lapdbpage_table_ly[(3,0)] = self.btnDbClear
        self.lapdbpage_table_ly[(4,0)] = self.lblDbWarning
        self.lapdbpage_okcancel_ly[(0,0)] = self.btnDbOk
        self.lapdbpage_okcancel_ly[(0,1)] = self.btnDbCancel

        def expandDisplay(n):
            if len(self.statRowFrames) < n:
                self.statRowFrames.extend([Frame(self.appWindow) for i in range(n-len(self.statRowFrames))])
            self.lbDisplay.expand(n)

        self.local_stat_ly[(0,0)] = self.browser
        self.remote_stat_ly[(0,0)] = self.browser

        npt = len(self.ptracker.lapCollectors)+1 # include heading
        expandDisplay(npt)
        for i in range(npt):
            self.setups_ly_table[(i,0)] = self.lbDisplay.lblConNames[i]
            self.setups_ly_table[(i,1)] = self.lbDisplay.btnConSendSetup[i]
            self.setups_ly_table[(i,2)] = self.lbDisplay.btnConSaveSetup[i]
            self.setups_ly_table[(i,3)] = self.lbDisplay.btnBan[i]

        tabWidth = config.LAYOUT_LAP_STATS.button_width
        self.tabView.update(self.appWindow,
           config.LAYOUT_LAP_STATS.button_height,
           config.LAYOUT_LAP_STATS.control_table_gap,
           config.LAYOUT_LAP_STATS.space_to_control_area,
           [dict(content=self.local_stat_ly, tabWidth=tabWidth, text="Local Stats", activateCallback=functools.partial(self.setMode, self.MODE_LOCAL_STATS)),
            dict(content=self.remote_stat_ly, tabWidth=tabWidth, text="Remote Stats", activateCallback=functools.partial(self.setMode, self.MODE_REMOTE_STATS)),
            dict(content=self.config_ly, tabWidth=tabWidth, text="Config", activateCallback=functools.partial(self.setMode, self.MODE_CONFIGURATION)),
            dict(content=self.setups_ly, tabWidth=tabWidth, text="Setups/Players", activateCallback=functools.partial(self.setMode, self.MODE_SETUPS)),
            dict(content=self.lapdbpage_ly, tabWidth=tabWidth, text="Database", activateCallback=functools.partial(self.setMode, self.MODE_DATABASE)),
           ],
           dict(fontColor=(config.COLORS_LAP_STATS.ui_label_color, config.COLORS_LAP_STATS.ui_control_color) )
           )
        self.tabView.setPos(5,30)
        mxMin,myMin,mxOpt,myOpt=self.appWindowFrame.margins()
        self.tabView.setMargins(mxOpt,myOpt)

        self.tabView.setBackgroundElements(self.appWindowFrame)
        self.tabView.setZoom(config.GLOBAL.zoom_dialog)
        self.tabView.setActive(True)

        self.mode = None
        self.setMode(oldMode) # make sure that the correct tab is selected

        self.tabView.updateLayout()

        self.needsReInit = False

    def setAllInactive(self):
        self.lbDisplay.setAllInactive()
        self.lastLayout = None

    def adjustSize(self):
        self.appWindow.setSize(self.tabView.getWidth(), self.tabView.getHeight())

    def setupConfigLayout(self):
        self.adjustSize()

    def doRenderConfig(self):
        pass

    def setupSetupsLayout(self):
        cfg = config.COLORS_LAP_STATS
        npt = len(self.ptracker.lapCollectors) + 1
        if npt != self.setups_ly_table.getRowCount():
            self.reinit()
        for i in range(npt):
            self.lbDisplay.lblConNames[i].setFontSize(config.LAYOUT_SETUPS.font_size).setFontAlignment('left').setFontColor(cfg.ui_label_color if i >= 1 else (1.0,1.0,1.0,1.0))
            self.lbDisplay.btnConSendSetup[i].setFontSize(config.LAYOUT_SETUPS.font_size).setFontAlignment('center').setFontColor(cfg.ui_control_color if i >= 1 else cfg.ui_label_color)
            self.lbDisplay.btnConSaveSetup[i].setFontSize(config.LAYOUT_SETUPS.font_size).setFontAlignment('center').setFontColor(cfg.ui_control_color if i >= 1 else cfg.ui_label_color)
            self.lbDisplay.btnBan[i].setFontSize(config.LAYOUT_SETUPS.font_size).setFontAlignment('center').setFontColor(cfg.ui_control_color if i >= 1 else cfg.ui_label_color)
        self.adjustSize()

    def doRenderSetups(self):
        cfg = config.COLORS_LAP_STATS
        cnt = 0
        self.lbDisplay.lblConNames[0].setText('Player')
        self.lbDisplay.btnConSendSetup[0].setText('')
        self.lbDisplay.btnConSaveSetup[0].setText('')
        self.lbDisplay.btnBan[0].setText('')

        for lc in self.ptracker.lapCollectors:
            if not acsim.ac.isConnected(lc.carId):
                continue
            if not lc.server_guid in self.ptracker.serverData:
                continue
            self.setup_guids[cnt+1] = lc.server_guid
            r = self.ptracker.serverData[lc.server_guid]
            name = lc.name
            self.lbDisplay.lblConNames[cnt+1].setText(name)
            self.lbDisplay.btnConSendSetup[cnt+1].setText('send set')
            if (r['ptracker_conn'] & ProtocolHandler.CAP_SEND_SETUP) and not self.ptracker.acLogParser.getCurrentSetup() is None:
                c = cfg.ui_control_color
            else:
                c = cfg.ui_label_color
            self.lbDisplay.btnConSendSetup[cnt+1].setFontColor(c)
            self.lbDisplay.btnConSaveSetup[cnt+1].setText('save set')
            if 'setup' in r:
                c = cfg.ui_control_color
            else:
                c = cfg.ui_label_color
            self.lbDisplay.btnConSaveSetup[cnt+1].setFontColor(c)
            self.lbDisplay.btnBan[cnt+1].setText('')
            c = cfg.ui_label_color
            self.lbDisplay.btnBan[cnt+1].setFontColor(c)
            cnt += 1

        for i in range(cnt,len(self.ptracker.lapCollectors)):
            self.lbDisplay.lblConNames[i+1].setText("")
            self.lbDisplay.btnConSendSetup[i+1].setText("")
            self.lbDisplay.btnConSaveSetup[i+1].setText("")
            self.lbDisplay.btnBan[i+1].setText("")

        if self.displayedDepositID != self.ptracker.setupDepositID:
            self.displayedDepositID = self.ptracker.setupDepositID
            self.tblSetupDeposit.clear()
            self.tblGroups.clear()
            deposit = self.ptracker.setupDeposit
            if not deposit is None:
                for s in deposit['setups']:
                    text = "%s (%s:%s)" % (s['name'], s['group'], s['sender'])
                    delText = "Del" if s['owner'] else ""
                    self.tblSetupDeposit.addItem(
                        [{'text':text,'color':config.COLORS_LAP_STATS.ui_label_color},
                         "Get",
                         delText],
                        s['setupid'])
                for g in deposit['memberOfGroup']:
                    self.tblGroups.addItem(
                        [{'text':g['group_name'], 'color':config.COLORS_LAP_STATS.ui_label_color},
                         "Publish"],
                        g['group_id'])

    def setupDBLayout(self):
        self.adjustSize()

    def doRenderDB(self):
        r = self.dbPageStateRes()
        if not r is None:
            self.dbPageState = None
            self.dbPageStateRes = lambda: None
        for b in [self.btnDbClear, self.btnDbCompressAll, self.btnDbCompressOther, self.btnDbCompressSlow]:
            b.setFontColor(config.COLORS_LAP_STATS.ui_control_color)
        if self.dbPageState is None or self.dbPageState == self.DBPAGE_STATE_WAIT:
            c = config.COLORS_LAP_STATS.ui_label_color
        else:
            c = config.COLORS_LAP_STATS.ui_control_color
        for b in [self.btnDbCancel, self.btnDbOk]:
            b.setFontColor(c)
        if self.dbPageState == self.DBPAGE_STATE_CLEAR:
            self.lblDbWarning.setText("This will DELETE ALL ENTRIES from the local database. Press OK to proceed.").setFontColor((1.0,0.5,0.5,1.0))
            hlBtn = self.btnDbClear
        elif self.dbPageState == self.DBPAGE_STATE_COMPRESS_ALL:
            self.lblDbWarning.setText("This will delete the lap comparison info from ALL laps. Press OK to proceed.").setFontColor((1.0,0.5,0.5,1.0))
            hlBtn = self.btnDbCompressAll
        elif self.dbPageState == self.DBPAGE_STATE_COMPRESS_OTHER:
            self.lblDbWarning.setText("This will delete the lap comparison info from all opponent's laps. Press OK to proceed.").setFontColor((1.0,0.5,0.5,1.0))
            hlBtn = self.btnDbCompressOther
        elif self.dbPageState == self.DBPAGE_STATE_COMPRESS_SLOW:
            self.lblDbWarning.setText("This will delete the lap comparison info from slow laps. Press OK to proceed.").setFontColor((1.0,0.5,0.5,1.0))
            hlBtn = self.btnDbCompressSlow
        elif self.dbPageState == self.DBPAGE_STATE_WAIT:
            self.lblDbWarning.setText("Operation in progress. Please wait.").setFontColor((1.0,1.0,1.0,1.0))
            hlBtn = None
        else:
            self.lblDbWarning.setText("")
            hlBtn = None
        if not hlBtn is None:
            hlBtn.setFontColor(config.COLORS_LAP_STATS.ui_control_color_highlight)

    def setupBrowserLayout(self):
        self.adjustSize()

    def doRenderStats(self):
        pass

    def renderStats(self):
        if self.lastLayout != self.LY_BROWSER:
            self.setupBrowserLayout()
            self.lastLayout = self.LY_BROWSER
        self.doRenderStats()

    def renderConfig(self):
        if self.lastLayout != self.LY_CONFIG:
            self.setupConfigLayout()
            self.lastLayout = self.LY_CONFIG
        self.doRenderConfig()

    def renderSetups(self):
        if self.lastLayout != self.LY_SETUPS:
            self.setupSetupsLayout()
            self.lastLayout = self.LY_SETUPS
        self.doRenderSetups()

    def renderDB(self):
        if self.lastLayout != self.LY_DATABASE:
            self.setupDBLayout()
            self.lastLayout= self.LY_DATABASE
        self.doRenderDB()

    def render(self, sessionType):
        if self.needsReInit:
            self.reinit()
        if self.needsReLoad:
            self.reload_config()
        if self.mode is None:
            self.setMode(self.MODE_LOCAL_STATS)
        if self.mode == self.MODE_LOCAL_STATS:
            self.renderStats()
        elif self.mode == self.MODE_REMOTE_STATS:
            self.renderStats()
        elif self.mode == self.MODE_CONFIGURATION:
            self.renderConfig()
        elif self.mode == self.MODE_SETUPS:
            self.renderSetups()
        elif self.mode == self.MODE_DATABASE:
            self.renderDB()
        # While we are rendering the statistics window, we allow our python threads
        # to consume some time here.
        time.sleep(0)

    def setMode(self, mode, force=False):
        if not force and (self.mode == mode or mode is None):
            return
        self.setAllInactive()
        self.mode = mode
        self.bankick_confirm = {}
        if mode == self.MODE_LOCAL_STATS:
            self.browser.loadUrl("local/lapstat")
            self.tabView.activate(index=0)
        elif mode == self.MODE_REMOTE_STATS:
            self.browser.loadUrl("server/lapstat")
            self.tabView.activate(index=1)
        elif mode == self.MODE_CONFIGURATION:
            self.tabView.activate(index=2)
        elif mode == self.MODE_SETUPS:
            self.ptracker.querySetups()
            self.tabView.activate(index=3)
        elif mode == self.MODE_DATABASE:
            self.tabView.activate(index=4)

    def cleanSetupsClicked(self, *args):
        self.ptracker.cleanupAutosaveSetups()

    def reinitLayout(self):
        self.needsReInit = True

    def lbDisplayClicked(self, row, column):
        if self.mode == self.MODE_SETUPS:
            if column == 1:
                acdebug("send setup clicked (row=%d, column=%d)", row, column)
                setup = self.ptracker.acLogParser.getCurrentSetup()
                if row in self.setup_guids and not setup is None:
                    stype, trackname, carname = self.ptracker.lastSessionType
                    self.ptracker.ptClient.send_setup(self.setup_guids[row], setup, carname)
                    acdebug("send setup called %s", self.setup_guids[row])
                    try:
                        receiver = self.ptracker.serverData[self.setup_guids[row]]['name']
                    except:
                        receiver = "?"
                    self.ptracker.addMessage(text="Setup sent to %s" % receiver,
                                             color=(1.0,1.0,1.0,1.0),
                                             mtype=MTYPE_LOCAL_FEEDBACK)
                else:
                    acdebug("cant send setup: setup_guids=%s", self.setup_guids)
            elif column == 2:
                if row in self.setup_guids and self.setup_guids[row] in self.ptracker.serverData:
                    sd = self.ptracker.serverData[self.setup_guids[row]]
                    if 'setup' in sd:
                        setup = sd['setup']
                        carname = sd['setup_car']
                        del sd['setup']
                        del sd['setup_car']
                        self.ptracker.saveSetup(sd['name'], setup, setup_car = carname)

        elif self.mode == self.MODE_STATISTICS_LAPS:
            if not self.ptracker.lapStats is None and 1 <= row <= len(self.ptracker.lapStats['laps']):
                self.lapIdToDisplay = self.ptracker.lapStats['laps'][row-1]['id']
                self.setMode(self.MODE_LAP)

    def dbClearClicked(self, *args):
        self.dbPageState = self.DBPAGE_STATE_CLEAR

    def dbCompressAllClicked(self, *args):
        self.dbPageState = self.DBPAGE_STATE_COMPRESS_ALL

    def dbCompressOtherClicked(self, *args):
        self.dbPageState = self.DBPAGE_STATE_COMPRESS_OTHER

    def dbCompressSlowClicked(self, *args):
        self.dbPageState = self.DBPAGE_STATE_COMPRESS_SLOW

    def dbOKClicked(self, *args):
        if self.dbPageState == self.DBPAGE_STATE_CLEAR:
            self.dbPageState = self.DBPAGE_STATE_WAIT
            self.dbPageStateRes = self.ptracker.sqliteDB.compressDB(COMPRESS_DELETE_ALL)
        elif self.dbPageState == self.DBPAGE_STATE_COMPRESS_ALL:
            self.dbPageState = self.DBPAGE_STATE_WAIT
            self.dbPageStateRes = self.ptracker.sqliteDB.compressDB(COMPRESS_NULL_ALL_BINARY_BLOBS)
        elif self.dbPageState == self.DBPAGE_STATE_COMPRESS_OTHER:
            self.dbPageState = self.DBPAGE_STATE_WAIT
            self.dbPageStateRes = self.ptracker.sqliteDB.compressDB(COMPRESS_NULL_ALL_BINARY_BLOBS_EXCEPT_GUID, steamGuid=self.ptracker.guid())
        elif self.dbPageState == self.DBPAGE_STATE_COMPRESS_SLOW:
            self.dbPageState = self.DBPAGE_STATE_WAIT
            self.dbPageStateRes = self.ptracker.sqliteDB.compressDB(COMPRESS_NULL_SLOW_BINARY_BLOBS)
        else:
            self.dbPageState = None

    def dbCancelClicked(self, *args):
        self.dbPageState = None

    def setupDepositClicked(self, selId, column):
        if column == 1: # user clicked get
            self.ptracker.querySetups(get_setupid=selId)
        elif column == 2: # user clicked del
            self.ptracker.querySetups(del_setupid=selId)

    def publishToGroupClicked(self, groupId, column):
        if column == 1: # user clicked publish
            self.ptracker.querySetups(save_group_id=groupId)

    def loadDefaultConfig(self, *args):
        config.revertToDefault()
        self.reload_config()
        self.gui.needsReInit = True
        self.needsReInit = True

    def fpsOptimizedSettings(self, *args):
        config.revertToFpsOptimized()
        self.reload_config()
        self.gui.needsReInit = True
        self.needsReInit = True

