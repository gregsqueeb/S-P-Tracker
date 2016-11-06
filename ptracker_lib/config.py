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

################################################################################
# Never Eat Yellow Snow APPS - ptracker
#
# This file is part of the ptracker project. See ptracker.py for details.
################################################################################
import configparser
import collections
import os.path
import shutil
from glob import glob
from ptracker_lib.expand_ac import expand_ac
from ptracker_lib.helpers import *

class SectionRes:
    def __init__(self, **kw):
        for k in kw:
            setattr(self, k, kw[k])

class Enum:
    def __init__(self, config, *v):
        self.config = config
        self.values = collections.OrderedDict()
        for (text, numeric) in v:
            self.values[text] = numeric
        self.reverse = {}
        for (text, numeric) in v:
            self.reverse[numeric] = text

    def __call__(self, section, option):
        v = self.config.get(section, option)
        for k in self.values:
            if v == k:
                return self.values[k]
        default_val = self.config[section][option][0]
        default_str = self.reverse[default_val]
        acwarning("config enum %s/%s is set to an unknown value. Possible values are %s. Using default (%s)." % (
            section,option,str(self.values.keys()), default_str))
        return default_val

    def inverse(self, x):
        r = self.reverse.get(x, None)
        if r is None:
            acwarning("config enum %s is not in known values. Returning default %s" % (str(x), list(self.values.keys())[0]))
            r = list(self.values.keys())[0]
        return r

    def getSettingStrings(self):
        return list(self.values.keys())

class ShortcutKeyConfig:
    def __init__(self, config):
        self.config = config

    def validKey(self, v):
        non_mods = set(v) - set(["Alt", "Ctrl", "Shift"])
        return len(v) > 0 and len(non_mods) == 1

    def __call__(self, section, option):
        vo = self.config.get(section, option)
        v = vo.split(" ")
        if not self.validKey(v):
            acwarning("invalid key %s", v)
            myassert(False)
        return v

    def inverse(self, x):
        res = " ".join(x)
        return res

class Config:

    def __init__(self):
        inidir = expand_ac('Assetto Corsa/plugins/ptracker')
        os.makedirs(inidir, exist_ok=True)
        self.ini_file_name = os.path.join(inidir, 'ptracker.ini')
        self.config = configparser.ConfigParser(allow_no_value = True)
        try:
            self.config.read(self.ini_file_name)
            if not self.config.has_section('LAYOUT_HOTLAP_LINE'):
                acwarning("Config file looks like an old version, overwriting after backup")
                self.config = configparser.ConfigParser(allow_no_value = True)
                if os.path.exists(self.ini_file_name):
                    shutil.copyfile(self.ini_file_name, self.ini_file_name + ".bak")
        except configparser.Error:
            acwarning("Error reading ini file %s. Creating a new one." % self.ini_file_name)
        except OSError:
            acwarning("OSError while reading / backup-ing ini file. Creating a new one.")
        self.CM_2ND_DERIV = 0
        self.CM_RACE_ORDER = 1
        self.getColoringMode = Enum(self.config, ('2nd_deriv',self.CM_2ND_DERIV), ('race_order',self.CM_RACE_ORDER))
        self.VAL_TOP = 0
        self.VAL_CENTER = 1
        self.VAL_BOTTOM = 2
        self.getVertAlign = Enum(self.config, ('bottom', self.VAL_BOTTOM), ('center',self.VAL_CENTER), ('top',self.VAL_TOP))
        self.HAL_LEFT = 0
        self.HAL_CENTER = 1
        self.HAL_RIGHT = 2
        self.getHorAlign = Enum(self.config, ('left', self.HAL_LEFT), ('center',self.HAL_CENTER), ('right',self.HAL_RIGHT))
        self.LT_FASTEST = 0
        self.LT_NONE = 1
        self.LT_ALL = 2
        self.LT_LAST = 3
        self.getLapTimeMode = Enum(self.config, ('fastest', self.LT_FASTEST), ('none', self.LT_NONE), ('all', self.LT_ALL), ('last_laps', self.LT_LAST))
        self.ACCURACY_HUNDREDTH = 0
        self.ACCURACY_MILLI = 1
        self.getAccuracy = Enum(self.config, ('hundredths', self.ACCURACY_HUNDREDTH), ('milliseconds', self.ACCURACY_MILLI))
        self.UNIT_TEMP_CELSIUS = 0
        self.UNIT_TEMP_FAHRENHEIT = 1
        self.getUnitTemp = Enum(self.config, ('Celsius', self.UNIT_TEMP_CELSIUS), ('Fahrenheit', self.UNIT_TEMP_FAHRENHEIT))
        self.UNIT_VEL_KMH = 0
        self.UNIT_VEL_MPH = 1
        self.getUnitVel = Enum(self.config, ('kmh', self.UNIT_VEL_KMH), ('mph', self.UNIT_VEL_MPH))
        self.WSTYLE_ROUND_FRAME = 0
        self.WSTYLE_ROUND_NOFRAME = 1
        self.WSTYLE_RECT_FRAME = 2
        self.WSTYLE_RECT_NOFRAME = 3
        self.getWindowStyle = Enum(self.config, ("rounded_frame",self.WSTYLE_ROUND_FRAME), ("rounded_frameless",self.WSTYLE_ROUND_NOFRAME),
                                  ("rect_frame",self.WSTYLE_RECT_FRAME), ("rect_frameless",self.WSTYLE_RECT_NOFRAME))
        self.TSTYLE_ORANGE_GREEN = 0
        self.TSTYLE_GRAY = 1
        self.TSTYLE_GREEN = 2
        self.TSTYLE_BLUE = 3
        self.TSTYLE_RED = 4
        self.TSTYLE_YELLOW = 5
        self.TSTYLE_NONE = 6
        self.getTableStyle = Enum(self.config, *zip(("orange_green","gray","green","blue","red","yellow","none"), range(self.TSTYLE_NONE+1)))

        self.MSG_DISABLED = 0
        self.MSG_ENABLED_NO_SOUND = 1
        self.MSG_ENABLED_WITH_SOUND = 2
        self.getMsgEnabled = Enum(self.config, ("disabled", self.MSG_DISABLED), ("visual", self.MSG_ENABLED_NO_SOUND), ("enabled", self.MSG_ENABLED_WITH_SOUND))

        self.CHATPOS_MANUAL = 0
        self.CHATPOS_CENTER = 1
        self.CHATPOS_TOP = 2
        self.CHATPOS_BOTTOM = 3
        self.getChatPos = Enum(self.config, ("manual",self.CHATPOS_MANUAL), ("center",self.CHATPOS_CENTER), ("top",self.CHATPOS_TOP), ("bottom", self.CHATPOS_BOTTOM))

        self.PREFER_ACCURACY = 0
        self.PREFER_HIGH_FPS = 1
        self.getFpsMode = Enum(self.config, ("prefer accuracy", self.PREFER_ACCURACY), ("prefer high fps",self.PREFER_HIGH_FPS))

        self.LV_ERROR = 0
        self.LV_WARNING = 1
        self.LV_INFO = 2
        self.LV_DEBUG = 3
        self.LV_DUMP = 4
        self.getLogVerbosity = Enum(self.config, *zip(("error", "warning", "info", "debug", "dump"), range(self.LV_DUMP+1)))

        self.FAD_LAPS_LEFT = 0
        self.FAD_ADD_FUEL_NEEDED = 1
        self.FAD_FUEL_LEFT = 2
        self.getFuelDisplayMode = Enum(self.config, *zip(("laps_left", "add_fuel_needed", "fuel_left"), range(self.FAD_FUEL_LEFT+1)))

        self.DR_EGO = 0
        self.DR_LEADER = 1
        self.getDeltaReference = Enum(self.config, *zip(("ego", "leader"), range(self.DR_LEADER+1)))

        self.DC_DELTA_COLUMN = 0
        self.DC_ALL_COLUMNS = 1
        self.DC_NO_COLUMNS = 2
        self.getDeltaColoring = Enum(self.config, *zip(("delta", "all", "none"), range(self.DC_NO_COLUMNS+1)))

        self.getShortcutKey = ShortcutKeyConfig(self.config)

        self.SOUND_FILE_NONE = 0
        self.SOUND_FILE_SWITCH1 = 0
        self.SOUND_FILE_CRASH = 0
        self.SOUND_FILE_APPLAUSE = 0
        sound_enums = [("(none)", self.SOUND_FILE_NONE)]
        self.sound_file_mapping = {}
        for i,f in enumerate(sorted(glob("apps/python/ptracker/sounds/*.wav"))):
            desc = os.path.splitext(os.path.basename(f))[0]
            if desc.lower() == "switch1":
                self.SOUND_FILE_SWITCH1 = i+1
            elif desc.lower() == "crash":
                self.SOUND_FILE_CRASH = i+1
            elif desc.lower() == "applause":
                self.SOUND_FILE_APPLAUSE = i+1
            sound_enums.append((desc, i+1))
            self.sound_file_mapping[i+1] = f
        self.getSoundFile = Enum(self.config, *sound_enums)

        self.SCAE_NONE = 0
        self.SCAE_NEXT = 1
        self.SCAE_NEXT_AND_LAST = 2
        self.SCAE_TWONEXT_AND_LAST = 3
        self.SCAE_TWONEXT_AND_TWO_LAST = 4
        self.getShowCarsAroundEgo = Enum(self.config, *zip(("none", "next", "nextAndLast", "TwoNextAndLast", "TwoNextAndTwoLast"), range(self.SCAE_TWONEXT_AND_TWO_LAST+1)))

        conf = self.config
        self.sections = collections.OrderedDict()
        self.sections['GLOBAL'] =  {
                'background_opacity' : (0.5, conf.getfloat, 'Set the opacity of the labels. 0 -> transparent, 1 -> opaque'),
                'save_samples_per_second_self' : (3., conf.getfloat, 'number of samples per second saved in database (used for lap comparisons), leave these as they are'),
                'save_samples_per_second_other' : (1., conf.getfloat, 'number of samples per second saved in database (used for lap comparisons), leave these as they are'),
                'override_stracker_server' : ("", conf.get, 'do not touch this; this is for development only'),
                'use_server_stats_if_available' : (True, conf.getboolean, 'if true, the default in the statistics window will be ServerDB, otherwise it will be LocalDB'),
                'time_display_accuracy' : (self.ACCURACY_HUNDREDTH, self.getAccuracy, 'accuracy for time displays, valid values are "hundredths","milliseconds".'),
                'auto_save_pb_setups' : (False, conf.getboolean, 'if true, the setups of personal best laps are saved automatically and named pt_autosave_MM_SS_MMM. Note that you always have to use saved setups for this feature.'),
                'temperature_unit' : (self.UNIT_TEMP_CELSIUS, self.getUnitTemp, 'unit for temperature, valid values are "Celsius" and "Fahrenheit".'),
                'velocity_unit' : (self.UNIT_VEL_KMH, self.getUnitVel, 'unit for velocity values, valid values are "kmh" and "mph".'),
                'window_style' : (self.WSTYLE_ROUND_FRAME, self.getWindowStyle, 'window style, valid values are "rounded_frame","rounded_frameless","rect_frame" and "rect_frameless".'),
                'leaderboard_style' : (self.TSTYLE_RED, self.getTableStyle, 'Leaderboard table style, valid values are "orange_green","gray","green","blue","red","yellow" and "none".'),
                'messageboard_style' : (self.TSTYLE_GRAY, self.getTableStyle, 'Messageboard table style, valid values are "orange_green","gray","green","blue","red","yellow" and "none".'),
                'statboard_style' : (self.TSTYLE_GRAY, self.getTableStyle, 'Statistics table style, valid values are "orange_green","gray","green","blue","red","yellow" and "none".'),
                'table_opacity' : (0.3, conf.getfloat, 'Opacity of the table style'),
                'zoom_gui' : (1.0, conf.getfloat, 'Zoom of the ptracker online window'),
                'zoom_dialog' : (1.0, conf.getfloat, 'Zoom of the ptracker dialog'),
                'fps_mode' : (self.PREFER_HIGH_FPS, self.getFpsMode, 'fps mode, valid values are "prefer accuracy" and "prefer high fps".'),
                'log_verbosity' : (self.LV_INFO, self.getLogVerbosity, 'log verbosity, valid values are "error", "warning", "info", "debug", "dump"'),
                'lap_times_as_delta' : (False, conf.getboolean, 'show best lap times as delta in leaderboards'),
                'initial_ban_days' : (30, conf.getint, 'default ban time when clicking on ban (you can change that in stracker web interface afterwards)'),
            }
        self.fpsOptimized = {}
        self.fpsOptimized['GLOBAL.fps_mode'] = self.PREFER_HIGH_FPS
        self.fpsOptimized['GLOBAL.auto_save_pb_setups'] = False
        self.fpsOptimized['GLOBAL.window_style'] = self.WSTYLE_RECT_NOFRAME
        self.fpsOptimized['GLOBAL.leaderboard_style'] = self.TSTYLE_NONE
        self.fpsOptimized['GLOBAL.messageboard_style'] = self.TSTYLE_NONE
        self.fpsOptimized['GLOBAL.log_verbosity'] = self.LV_INFO
        self.sections['LAYOUT'] = {
                'space_top' : (0, conf.getint, 'margin around the app window (including title bar)'),
                'space_bottom' : (0, conf.getint, 'margin around the app window'),
                'space_left' : (0, conf.getint, 'margin around the app window'),
                'space_right' : (0, conf.getint, 'margin around the app window'),
                'valign' : (self.VAL_TOP, self.getVertAlign, 'vertical alignment, valid values are "bottom", "center", "top"'),
                'halign' : (self.HAL_LEFT, self.getHorAlign, 'horizontal alignment, valid values are "left", "center", "right"'),
                'hexpand' : (True, conf.getboolean, 'If set to true, the hotlap line, leaderboard and messageboard are expanded to have the same width'),
                'leaderboard_num_char' : (0, conf.getint, 'Set this to the number of characters to be used in the leaderboard display. 0 means to limit by available space.'),
                'leaderboard_show_badge' : (1, conf.getboolean, 'set to 1 to show the badge.'),
                'leaderboard_show_tyre' : (1, conf.getboolean, 'set to 1 to show the tyre icon'),
                'team_num_char' : (0, conf.getint, 'Set to the number of characters of the team column (0 to not show the team)'),
            }
        self.fpsOptimized['LAYOUT.leaderboard_show_badge'] = False
        self.sections['LAYOUT_HOTLAP'] = {
                'space_gap' : (2, conf.getint, 'gap between to labels (x/y) in pixel'),
                'width_descriptions' : (70, conf.getint, 'width of the description area (left column) in pixel'),
                'width_times' : (70, conf.getint, 'width of the time area (middle column) in pixel'),
                'width_deltas' : (70, conf.getint, 'width of the delta area (right column) in pixel'),
                'row_height' : (20, conf.getint, 'height of one row in pixel'),
                'font_size_desc' : (17, conf.getint, 'description font size'),
                'font_size_times' : (17, conf.getint, 'time and delta font size'),
                'font_size_reason' : (10, conf.getint, 'invalid reason font size'),
            }
        self.sections['COLORS_HOTLAP'] = {
                'fast_time_color' : ((0.0, 1.0, 0.0, 1.0), self.getcolor, 'color for fast delta times'),
                'slow_time_color' : ((0.9, 0.9, 0.9, 1.0), self.getcolor, 'color for slow delta times'),
                'equal_time_color' : ((0.9, 0.9, 0.9, 1.0), self.getcolor, 'color for equal delta times'),
                'ui_label_color' : ((0.6, 0.6, 0.6, 1.0), self.getcolor, 'color for description labels'),
                'invalid_lap_color' : ((0.9, 0.3, 0.3, 1.0), self.getcolor, 'color for displaying invalid laps'),
                'valid_lap_color' : ((0.3, 0.9, 0.3, 1.0), self.getcolor, 'color for displaying valid laps'),
                'session_display_color' : ((0.9, 0.9, 0.9, 1.0), self.getcolor, 'color for lap / session time left display'),
                'stracker_display_color_connected' : ((0.3, 0.9, 0.3, 1.0), self.getcolor, 'color for stracker display when connected'),
                'stracker_display_color_setup_av' : ((0.9, 0.9, 0.0, 1.0), self.getcolor, 'color for stracker display when setup is available'),
                'stracker_display_color_not_conn' : ((0.7, 0.7, 0.7, 1.0), self.getcolor, 'color for stracker display when not connected'),
                'cmp_time_color' : ((1.0, 0.5, 1.0, 1.0), self.getcolor, 'color for displaying the comparison split/sector/lap times'),
                'pit_time_color' : ((0.6, 0.6, 0.9, 1.0), self.getcolor, 'color for displaying pit times'),
            }
        self.sections['CONFIG_HOTLAP_LINE'] = {
                'show_laptime_duration' : (10, conf.getfloat, 'number of seconds to show the split / lap time in the hotlap line instead of the comparison'),
                'show_pitlanetime_duration' : (10, conf.getfloat, 'number of seconds to show the pitlane time in the hotlap line instead of the comparison or laptime'),
            }
        self.sections['LAYOUT_HOTLAP_LINE'] = {
                'hotlap_line_gap': (2,conf.getint, 'gap between the labels in pixel'),
                'show_live_delta': (1,conf.getboolean, 'show the live delta label'),
                'show_cmp_values': (0,conf.getboolean, 'show comparison base (=personal best) split/sector display'),
                'show_split_delta': (1,conf.getboolean, 'show the split delta and lap time display label'),
                'show_sector_delta': (1,conf.getboolean, 'show the sector delta display label'),
                'show_validity': (1,conf.getboolean, 'use 0 to not display lap validity'),
                'width_validity_reason': (0,conf.getint, 'width of the lap validity reason display (use 0 to not display the reason'),
                'show_session_display': (1,conf.getboolean, 'show session status display (laps or session time remaining)'),
                'show_stracker_display': (1, conf.getboolean, 'use 0 to not display stracker connection status'),
                'hotlap_row_height': (25,conf.getint, 'height of the hotlap line, use 0 to not display the hotlap line at all'),
                'font_size' : (17,conf.getint, 'font size of the hotlap line'),
                'font_size_reason' : (10,conf.getint, 'font size for displaying invalid reasons in the hotlap line'),
                'show_fuel_icon' : (True, conf.getboolean, 'show the fuel icon'),
                'show_fuel_amount' : (True, conf.getboolean, 'show fuel numbder'),
                'fuel_display_mode' : (self.FAD_LAPS_LEFT, self.getFuelDisplayMode, 'show the fuel amount in hotlap line. Valid values are "laps_left", "add_fuel_needed" and "fuel_left".'),
            }
        self.sections['CONFIG_RACE'] = {
                'sync_live' : (0, conf.getboolean, 'if set to 1, the opponent delta times are updated live, otherwise they are updated when crossing sectors'),
                'sync_interval' : (0, conf.getfloat, 'interval between delta syncs when sync_live is set to 1. 0 means "as fast as possible".'),
                'show_splits_seconds' : (20, conf.getfloat, 'number of seconds, the opponent deltas will be shown, when sync_live is False'),
                'coloring_mode' : (0, self.getColoringMode, 'mode for coloring the leaderboard. Valid values are "2nd_deriv" (quicker/slower) and "race_order" (in front/behind)'),
                'delta_2nd_deriv_filter_strength' : (50, conf.getfloat, 'if sync_live is True, this is the filter strength for comparison. Higher values mean tighter filtering (and less flickering)'),
                'always_show_leader' : (1, conf.getboolean, 'if set, the leader will always be shown on the leaderboard'),
                'show_cars_around_ego' : (self.SCAE_NEXT_AND_LAST, self.getShowCarsAroundEgo, 'set to the cars which should be displayed always based on track position. Valid values are "none", "next", "nextAndLast", "TwoNextAndLast", "TwoNextAndTwoLast".'),
                'colorize_track_positions' : (True, conf.getboolean, 'if set, the next and last car according to the track position will be colored blue or red'),
                'lap_time_mode' : (self.LT_ALL, self.getLapTimeMode, 'configures race lap time display.Valid values are "fastest", "none", "all" and "last_laps".'),
                'show_leaderboard' : (True, conf.getboolean, 'show the leaderboard in race / quali mode'),
                'show_deltas' : (True, conf.getboolean, 'show the delta times to opponents'),
                'leaderboard_show_lap_count' : (False, conf.getboolean, 'show the lap count of the drivers'),
                'delta_reference' : (self.DR_EGO, self.getDeltaReference, 'Chooses the reference for the delta disply. Valid values are "ego" (means spectated) and "leader".'),
                'delta_coloring' : (self.DC_DELTA_COLUMN, self.getDeltaColoring, 'Which columns are colored according to the delta. Valid values are "delta", "all" and "none".'),
                'show_driver_status' : (True, conf.getboolean, 'show the status of the driver (pits, finished, track position)'),
            }
        self.fpsOptimized['CONFIG_RACE.sync_live'] = False
        self.sections['COLORS_RACE'] = {
                'race_order_before_color' : ((0.9, 0.9, 0.9, 1.0), self.getcolor, 'when CONFIG_RACE.coloring mode is race_order: color of opponents before yourself'),
                'race_order_self_color' : ((0.9, 0.9, 0.0, 1.0), self.getcolor, 'in either mode: color of yourself'),
                'race_order_after_color' : ((0.9, 0.9, 0.9, 1.0), self.getcolor, 'when CONFIG_RACE.coloring mode is race_order: color of opponents after yourself'),
                'race_quicker_color' : ((0.0, 1.0, 0.0, 1.0), self.getcolor, 'when CONFIG_RACE.coloring mode is 2nd_deriv: oppponent color when you are quicker than the other'),
                'race_slower_color' : ((1.0, 0.0, 0.0, 1.0), self.getcolor, 'when CONFIG_RACE.coloring mode is 2nd_deriv: oppponent color when you are slower than the other'),
                'race_equal_color' : ((0.9, 0.9, 0.9, 1.0), self.getcolor, 'when CONFIG_RACE.coloring mode is 2nd_deriv: color of opponents which are same speed than you'),
                'best_time_color' : ((1.0, 0.5, 1.0, 1.0), self.getcolor, 'coloring of the fastest lap time in the race (if displayed)'),
                'pers_best_time_color' : ((1.0, 1.0, 0.5, 1.0), self.getcolor, 'coloring of the personal best lap in the race (if displayed)'),
                'norm_time_color' : ((0.9, 0.9, 0.9, 1.0), self.getcolor, 'coloring of normal lap times in the race (if displayed)'),
                'notconnected' : ((0.5, 0.5, 0.5, 1.0), self.getcolor, 'coloring for opponents which are not connected'),
                'next_track_color' : ((0.5,0.5,1.0,1.0), self.getcolor, 'coloring for opponents you are following on track'),
                'last_track_color' : ((1.0,0.5,0.5,1.0), self.getcolor, 'coloring for opponents following you on track'),
            }
        self.sections['COLORS_QUAL'] = {
                'race_order_before_color' : ((0.9, 0.9, 0.9, 1.0), self.getcolor, 'color of opponents before yourself'),
                'race_order_self_color' : ((0.9, 0.9, 0.0, 1.0), self.getcolor, 'color of yourself'),
                'race_order_after_color' : ((0.9, 0.9, 0.9, 1.0), self.getcolor, 'color of opponents after yourself'),
                'best_time_color' : ((1.0, 0.5, 1.0, 1.0), self.getcolor, 'coloring of the fastest lap time'),
                'norm_time_color' : ((0.9, 0.9, 0.9, 1.0), self.getcolor, 'coloring of normal lap times'),
            }
        self.sections['LAYOUT_RACE'] = {
                'leaderboard_gap' : (2, conf.getint, 'space in pixel between labels in the leaderboard'),
                'width_position' : (20, conf.getint, 'width of column with the position numbers(0 to not display position numbers)'),
                'width_name' : (150, conf.getint, 'width of column with the names (0 to not display names)'),
                'width_delta' : (60, conf.getint, 'width of column with the deltas (0 to not display deltas)'),
                'width_bestTime' : (60, conf.getint, 'width of column with best times (0 to not display best times)'),
                'leaderboard_row_height' : (17, conf.getint, 'row height in pixels'),
                'leaderboard_num_rows' : (10, conf.getint, 'number of rows to be displayed in leaderboard display'),
                'space_to_hotlap_line' : (4, conf.getint, 'space between hotlap line and leaderboard table'),
                'font_size_positions' : (14, conf.getint, 'font size of the position display'),
                'font_size_names' : (14, conf.getint, 'font size of the name display'),
                'font_size_deltas' : (14, conf.getint, 'font size of the delta display'),
                'font_size_laps' : (14, conf.getint, 'font size of the best lap time display'),
            }
        self.sections['LAYOUT_QUAL'] = {
                'leaderboard_gap' : (2, conf.getint, 'space in pixel between labels in the leaderboard'),
                'width_position' : (20, conf.getint, 'width of column with the position numbers(0 to not display position numbers)'),
                'width_name' : (150, conf.getint, 'width of column with the names (0 to not display names)'),
                'width_delta' : (0, conf.getint, 'leave this at 0!'),
                'width_bestTime' : (60, conf.getint, 'width of column with best times (0 to not display best times)'),
                'leaderboard_row_height' : (17, conf.getint, 'row height in pixels'),
                'leaderboard_num_rows' : (10, conf.getint, 'number of rows to be displayed in leaderboard display'),
                'space_to_hotlap_line' : (4, conf.getint, 'space between hotlap line and leaderboard table'),
                'font_size_positions' : (14, conf.getint, 'font size of the position display'),
                'font_size_names' : (14, conf.getint, 'font size of the name display'),
                'font_size_deltas' : (14, conf.getint, 'font size of the delta display'),
                'font_size_laps' : (14, conf.getint, 'font size of the best lap time display'),
            }
        self.sections['LAYOUT_LAP_STATS'] = {
                'font_size' : (14, conf.getint, 'font size for the statistics display'),
                'stat_table_gap' : (2, conf.getint, 'gap between the labels in the statistics display'),
                'width_position' : (27, conf.getint, 'width of the column with the position numbers'),
                'width_name' : (150, conf.getint, 'width of the column with the driver name'),
                'width_bestTime' : (60, conf.getint, 'width of the column with the lap times'),
                'width_timeStamp' : (135, conf.getint, 'width of the column with the time stamps'),
                'width_lapValid' : (60, conf.getint, 'width of the column with the validity'),
                'width_tyre' : (150, conf.getint, 'width of the column with the tyre type'),
                'width_sectors' : (60, conf.getint, 'width of the columns with the sector times'),
                'width_car' : (125, conf.getint, 'width of the car column'),
                'width_inputMethod' : (125, conf.getint, 'width of the input method column'),
                'width_proMode' : (60, conf.getint, 'width of the pro mode column'),
                'width_maxSpeed' : (65, conf.getint, 'width of the max speed column'),
                'stat_table_row_height' : (17, conf.getint, 'height of a table row'),
                'stat_num_rows' : (21, conf.getint, 'number of rows shown on one page'),
                'control_table_gap' : (5, conf.getint, 'gap between elements in the stat control area'),
                'button_width' : (120, conf.getint, 'width of a control button'),
                'button_height': (17, conf.getint, 'height of a control button'),
                'space_to_control_area' : (4, conf.getint, 'space between control area and stat table'),
                'nav_btn_height' : (24, conf.getint, 'height of the db navigation buttons'),
            }
        self.sections['LAYOUT_SESSION_STATS'] = {
                'width_type' : (100, conf.getint, 'width of the column with the session type'),
                'width_numRacers' : (60, conf.getint, 'width of the column with the number of drivers'),
                'width_egoPosition' : (60, conf.getint, 'width of the column with own finish position'),
                'width_podium' : (150, conf.getint, 'width of the columns containing the podium'),
                'width_timeStamp' : (135, conf.getint, 'width of the column with the time and date'),
                'width_mpDisplay' : (60, conf.getint, 'width of the column with the multiplayer boolean'),
            }
        self.sections['LAYOUT_LAP_DETAILS'] = {
                'combo_info_width' : (150, conf.getint, 'width of the first column of lap details display'),
                'lap_info_width' : (150, conf.getint, 'width of the second column of lap details display'),
                'session_info_width' : (150, conf.getint, 'width of the third column of lap details display'),
                'aid_info_width' : (150, conf.getint, 'width of the fourth column of lap details display'),
                'font_size' : (14, conf.getint, 'font size for the lap details display'),
        }
        self.sections['COLORS_LAP_STATS'] = {
                'ui_label_color' : ((0.8, 0.8, 0.8, 1.0), self.getcolor, 'color of headings'),
                'fastest_lap_color': ((1.0, 0.5, 1.0, 1.0), self.getcolor, 'color of fastest lap (p1 in statistics)'),
                'fastest_sector_color': ((0.3, 1.0, 0.3, 1.0), self.getcolor, 'color of fastest sectors'),
                'normal_color': ((0.9,0.9,0.9,1.0), self.getcolor, 'color of normal laps'),
                'ego_color': ((0.9, 0.9, 0.0, 1.0), self.getcolor, 'color of ego laps'),
                'ui_control_color': ((0.9, 0.9, 0.0, 1.0), self.getcolor, 'color of ui control elements'),
                'ui_control_color_highlight': ((1.0, 1.0, 0.75, 1.0), self.getcolor, 'color of ui control elements'),
        }
        self.sections['COLORS_LAP_DETAILS'] = {
                'ui_label_color' : ((0.6, 0.6, 0.6, 1.0), self.getcolor, 'color of headings'),
                'normal_color' : ((0.9,0.9,0.9,1.0), self.getcolor, 'color of data'),
        }
        self.sections['LAYOUT_CONFIG'] = {
                'width_labels' : (300, conf.getint, 'width of the lable column'),
                'width_controls' : (100, conf.getint, 'width of the control column'),
        }
        self.sections['LAYOUT_SETUPS'] = {
                'width_name' : (150, conf.getint, 'width of the column with the driver name'),
                'width_send_set' : (65, conf.getint, 'width of the column with the send buttons'),
                'width_save_set' : (65, conf.getint, 'width of the column with the save buttons'),
                'width_bankick' : (65, conf.getint, 'width of the column with the ban/kick buttons'),
                'font_size' : (14, conf.getint, 'font size for the setup sheet in pixel'),
        }
        self.sections['LAYOUT_MESSAGE_BOARD'] = {
            'num_rows' : (10, conf.getint, 'max. number of messages displayed'),
            'width' : (250, conf.getint, 'width of messages in pixels'),
            'row_height' : (17, conf.getint, 'height of message row in pixels'),
            'font_size' : (14, conf.getint, 'font size of messages'),
            'attached' : (True, conf.getboolean, 'true, if message board shall be attached to ptracker gui'),
        }
        self.sections['CONFIG_MESSAGE_BOARD'] = {
            'enabled' : (1, conf.getboolean, 'set to 1 to enable the message board, set to 0 to disable it.'),
            'time_to_show' : (20, conf.getint, 'time [seconds] to show messages.'),
            'enable_msg_enter_leave' : (True, conf.getboolean, 'set to 1 to enable these messages, set to 0 to disable it.'),
            'sound_file_enter_leave' : (self.SOUND_FILE_SWITCH1, self.getSoundFile, 'choose sound file to play. Sound is taken from ptracker/sounds directory, .wav is appended. "(none)" means no sound.'),
            'enable_msg_best_lap' : (True, conf.getboolean, 'set to 1 to enable these messages, set to 0 to disable it.'),
            'sound_file_best_lap' : (self.SOUND_FILE_CRASH, self.getSoundFile, 'choose sound file to play. Sound is taken from ptracker/sounds directory, .wav is appended. "(none)" means no sound.'),
            'enable_msg_checksum_errors' : (False, conf.getboolean, 'set to 1 to enable these messages, set to 0 to disable it.'),
            'sound_file_checksum_errors' : (self.SOUND_FILE_NONE, self.getSoundFile, 'choose sound file to play. Sound is taken from ptracker/sounds directory, .wav is appended. "(none)" means no sound.'),
            'enable_msg_welcome' : (True, conf.getboolean, 'set to 1 to enable these messages, set to 0 to disable it.'),
            'sound_file_welcome' : (self.SOUND_FILE_NONE, self.getSoundFile, 'choose sound file to play. Sound is taken from ptracker/sounds directory, .wav is appended. "(none)" means no sound.'),
            'enable_msg_local_feedback' : (True, conf.getboolean, 'set to 1 to enable these messages, set to 0 to disable it.'),
            'sound_file_local_feedback' : (self.SOUND_FILE_NONE, self.getSoundFile, 'choose sound file to play. Sound is taken from ptracker/sounds directory, .wav is appended. "(none)" means no sound.'),
            'enable_msg_local_pb' : (True, conf.getboolean, 'set to 1 to enable these messages, set to 0 to disable it.'),
            'sound_file_local_pb' : (self.SOUND_FILE_CRASH, self.getSoundFile, 'choose sound file to play. Sound is taken from ptracker/sounds directory, .wav is appended. "(none)" means no sound.'),
            'enable_msg_setup_rcv' : (True, conf.getboolean, 'set to 1 to enable these messages, set to 0 to disable it.'),
            'sound_file_setup_rcv' : (self.SOUND_FILE_CRASH, self.getSoundFile, 'choose sound file to play. Sound is taken from ptracker/sounds directory, .wav is appended. "(none)" means no sound.'),
            'enable_msg_setup_saved' : (True, conf.getboolean, 'set to 1 to enable these messages, set to 0 to disable it.'),
            'sound_file_setup_saved' : (self.SOUND_FILE_NONE, self.getSoundFile, 'choose sound file to play. Sound is taken from ptracker/sounds directory, .wav is appended. "(none)" means no sound.'),
            'enable_msg_race_finished' : (True, conf.getboolean, 'set to 1 to enable these messages, set to 0 to disable it.'),
            'sound_file_race_finished' : (self.SOUND_FILE_APPLAUSE, self.getSoundFile, 'choose sound file to play. Sound is taken from ptracker/sounds directory, .wav is appended. "(none)" means no sound.'),
            'enable_msg_chat' : (True, conf.getboolean, 'set to 1 to enable the integrated chat feature, set to 0 to disable it (also the text input will be disabled).'),
            'sound_file_chat' : (self.SOUND_FILE_CRASH, self.getSoundFile, 'choose sound file to play. Sound is taken from ptracker/sounds directory, .wav is appended. "(none)" means no sound.'),
            'enable_msg_collision' : (True, conf.getboolean, 'set to 1 to enable collision messages from the server'),
            'sound_file_collision' : (self.SOUND_FILE_CRASH, self.getSoundFile, 'choose sound file to play. Sound is taken from ptracker/sounds directory, .wav is appended. "(none)" means no sound.'),
            'sound_volume' : (0.4, conf.getfloat, 'set to the volume of the sound to be played (use 0.0 to disable sound output.'),
        }
        self.sections['LAYOUT_DBPAGE'] = {
            'width_btns' : (600, conf.getint, 'width of the database page controls'),
            'width_okcancel' : (60, conf.getint, 'width of the database page ok/cancel buttons'),
        }
        self.sections['CHAT'] = {
            'text_input_auto_position' : (self.CHATPOS_CENTER, self.getChatPos, 'Valid values are "manual", "center", "top" and "bottom".'),
            'chat_filter' : ('', conf.get, 'Regular expression for filtering the chat messages. Examples: "PLP:" will filter out all messages containing the string "PLP:", "(^Pit Lane App)|(PLP:)" will filter out messages starting with Pit Lane App and messages containing the string PLP:")'),
            'shortcut_talk' : ('Alt T'.split(" "), self.getShortcutKey, 'shortcut for talking'),
            'shortcut_mode' : ('Alt H'.split(" "), self.getShortcutKey, 'shortcut changing the chat display mode'),
            'shortcut_pgup' : ('Alt KeyUp'.split(" "), self.getShortcutKey, 'shortcut for scrolling upwards in message histories'),
            'shortcut_pgdown': ('Alt KeyDown'.split(" "), self.getShortcutKey, 'shortcut for scrolling downwards in message histories'),
            'scroll_timeout': (20, conf.getint, 'after this timespan in seconds the scrolling mode will be left'),
            'msg_shortcut_send_direct' : (True, conf.getboolean, 'if set to true, message shortcuts are sent directly to the chat, if false, they are sent to the edit box for further refinement'),
            'msg_1_shortcut' : ('KeyNumPad1'.split(" "), self.getShortcutKey, 'shortcut for msg 1'),
            'msg_1_text' : (':)', conf.get, 'text for msg 1'),
            'msg_2_shortcut' : ('KeyNumPad2'.split(" "), self.getShortcutKey, 'shortcut for msg 2'),
            'msg_2_text' : (':D', conf.get, 'text for msg 2'),
            'msg_3_shortcut' : ('KeyNumPad3'.split(" "), self.getShortcutKey, 'shortcut for msg 3'),
            'msg_3_text' : (':(', conf.get, 'text for msg 3'),
            'msg_4_shortcut' : ('KeyNumPad4'.split(" "), self.getShortcutKey, 'shortcut for msg 4'),
            'msg_4_text' : ('good race', conf.get, 'text for msg 4'),
            'msg_5_shortcut' : ('KeyNumPad5'.split(" "), self.getShortcutKey, 'shortcut for msg 5'),
            'msg_5_text' : ('good pass', conf.get, 'text for msg 5'),
            'msg_6_shortcut' : ('KeyNumPad6'.split(" "), self.getShortcutKey, 'shortcut for msg 6'),
            'msg_6_text' : ('sorry', conf.get, 'text for msg 6'),
            'msg_7_shortcut' : ('KeyNumPad7'.split(" "), self.getShortcutKey, 'shortcut for msg 7'),
            'msg_7_text' : ('hi', conf.get, 'text for msg 7'),
            'msg_8_shortcut' : ('KeyNumPad8'.split(" "), self.getShortcutKey, 'shortcut for msg 8'),
            'msg_8_text' : ('thank you!', conf.get, 'text for msg 8'),
            'msg_9_shortcut' : ('KeyNumPad9'.split(" "), self.getShortcutKey, 'shortcut for msg 9'),
            'msg_9_text' : ('bye', conf.get, 'text for msg 9'),
        }
        self.save()

    def revertToDefault(self):
        for s in self.sections:
            section = getattr(self, s)
            for a in self.sections[s]:
                setattr(section, a, self.sections[s][a][0])

    def revertToFpsOptimized(self):
        for s in self.fpsOptimized:
            v = self.fpsOptimized[s]
            section,attr = s.split(".")
            setattr(getattr(self,section),attr,v)

    def save(self):
        conf = self.config
        try:
            f = open(self.ini_file_name, 'w')
            for s in self.sections:
                if not conf.has_section(s):
                    conf.add_section(s)
                f.write('[%s]\n'%s)
                v = getattr(self, s)
                for o in sorted(self.sections[s]):
                    validator = self.sections[s][o][1]
                    try:
                        inverseF = validator.inverse
                    except:
                        inverseF = str
                    f.write('; %s\n' % self.sections[s][o][2])
                    f.write('%s = %s\n' % (o, inverseF(getattr(v, o))))
                f.write('\n\n')
            f.close()
        except:
            acwarning("Error writing file %s. Ignoring." % (self.ini_file_name))

    def __getattr__(self, attr):
        if attr in self.sections:
            d = {}
            s = self.sections[attr]
            for o in s:
                defaultVal, getter, comment = s[o]
                try:
                    d[o] = getter(attr, o)
                except:
                    acwarning("Error reading %s/%s. Using default." % (attr, o))
                    d[o] = defaultVal
            self.__dict__[attr] = SectionRes(**d)
        return self.__dict__[attr]

    def getcolor(self, section, option):
        v = self.config.get(section, option)
        v = eval(v)
        myassert(type(v) == type(()))
        myassert(len(v) == 4)
        for c in v:
            myassert( 0.0 <= c <= 1.0 )
        return v

config = Config()
