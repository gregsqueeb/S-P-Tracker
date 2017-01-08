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
from stracker_lib import logger

class SectionRes:
    def __init__(self, **kw):
        for k in kw:
            setattr(self, k, kw[k])

class Enum:
    def __init__(self, config, *v):
        self.config = config
        self.values = collections.OrderedDict()
        for (k, s) in v:
            self.values[k] = s

    def __call__(self, section, option):
        v = self.config.get(section, option)
        for k in self.values:
            if v == k:
                return self.values[k]
        acwarning("config enum %s/%s is set to an unknown value. Possible values are %s. Using default (%s)." % (
            section,option,str(self.values.keys()), list(self.values.keys())[0]))
        return self.values[list(self.values.keys())[0]]

    def inverse(self, x):
        for k in self.values:
            if self.values[k] == x:
                return k
        acwarning("config enum %s is not in known values. Returning default %s" % (str(x), list(self.values.keys())[0]))
        return list(self.values.keys())[0]

class PortValidator:
    def __init__(self, config):
        self.config = config
        self.validPorts = [50042, 50043, 54242, 54243, 60023, 60024, 62323, 62324, 42423, 42424, 23232, 23233]

    def __call__(self, section, option):
        v = self.config.getint(section, option)
        if not v in self.validPorts:
            acwarning("""\
Config option %s/%s is set to an invalid value.
    Possible values are %s. Continue, but ptracker connections might not be possible.
    Only exception: set the the port to the TCP port of the AC server + 42 (this method is not validated here).
""", section, option, str(self.validPorts))
        return v

class Config:

    def __init__(self, ini_file_name, logger_module):
        if not logger_module is None:
            global acerror, acwarning, acinfo, acdebug, acdump
            if ini_file_name is None: # ptracker, no all messages are mapped to debug
                acerror = logger_module.acdebug
                acwarning = logger_module.acdebug
                acinfo = logger_module.acdebug
            else:
                acerror = logger_module.acerror
                acwarning = logger_module.acwarning
                acinfo = logger_module.acinfo
            acdebug = logger_module.acdebug
            acdump = logger_module.acdump
        else:
            acerror = lambda *args: None
            acwarning = lambda *args: None
            acinfo = lambda *args: None
            acdebug = lambda *args: None
            acdump = lambda *args: None

        self.config = configparser.ConfigParser(interpolation=None)
        self.dirtyConfig = False
        self.ini_file_name = ini_file_name
        if not ini_file_name is None:
            inidir = os.path.split(ini_file_name)[0]
            if not inidir == "":
                os.makedirs(inidir, exist_ok=True)
            try:
                self.config.read(self.ini_file_name)
            except configparser.Error:
                acwarning("Error reading ini file %s. Creating a new one." % self.ini_file_name)
            except OSError:
                acwarning("OSError while reading / backup-ing ini file. Creating a new one.")
        conf = self.config

        self.portValidator = PortValidator(self.config)

        self.DBTYPE_SQLITE3 = 0
        self.DBTYPE_POSTGRES = 1
        self.getDatabaseType = Enum(self.config, ('sqlite3', self.DBTYPE_SQLITE3), ('postgres', self.DBTYPE_POSTGRES))

        self.getLogLevel = Enum(self.config, ('info', logger.LOG_LEVEL_INFO), ('debug', logger.LOG_LEVEL_DEBUG), ('dump', logger.LOG_LEVEL_DUMP) )

        self.DBCOMPRESSION_HI_SAVE_ALL = 0
        self.DBCOMPRESSION_HI_SAVE_FAST = 1
        self.DBCOMPRESSION_HI_SAVE_NONE = 2
        self.getCompressionLevel = Enum(self.config, ('none', self.DBCOMPRESSION_HI_SAVE_ALL),
                                                     ('remove_slow_laps', self.DBCOMPRESSION_HI_SAVE_FAST),
                                                     ('remove_all', self.DBCOMPRESSION_HI_SAVE_NONE))

        self.PTC_ANY = 0
        self.PTC_NEWER = 1
        self.PTC_NONE = 2
        self.getPtrackerConnectionMode = Enum(self.config, ('any', self.PTC_ANY), ('newer', self.PTC_NEWER), ('none', self.PTC_NONE))

        self.ROS_NONE = 0
        self.ROS_REPLACE_WITH_PRACTICE = 1
        self.ROS_SKIP = 2
        self.getRaceOverStrategy = Enum(self.config, ('none', self.ROS_NONE), ('replace_with_practice', self.ROS_REPLACE_WITH_PRACTICE), ('skip', self.ROS_SKIP))

        self.SF_NONE = 0
        self.SF_KICK = 1
        self.SF_BAN = 2
        self.getSwearAction = Enum(self.config, ('none', self.SF_NONE), ('kick', self.SF_KICK), ('ban', self.SF_BAN))

        self.VU_KMH = 0
        self.VU_MPH = 1
        self.getVelUnit = Enum(self.config, ('kmh', self.VU_KMH), ('mph', self.VU_MPH))

        self.TU_DEGC = 0
        self.TU_DEGF = 1
        self.getTempUnit = Enum(self.config, ('degc', self.TU_DEGC), ('degf', self.TU_DEGF))

        self.sections = collections.OrderedDict()
        self.sections['STRACKER_CONFIG'] = {
            'ac_server_cfg_ini' : ('', conf.get, 'Path to configuration file of ac server. Note: whenever the server is restarted, it is required to restart stracker as well'),
            'ac_server_address' : ('127.0.0.1', conf.get, 'Server ip address or name used to poll results from. You should not touch the default value: 127.0.0.1'),
            'listening_port' : (50042, self.portValidator, "Listening port for incoming connections of ptracker. Must be one of 50042, 50043, 54242, 54243, 60023, 60024, 62323, 62324, 42423, 42424, 23232, 23233, <AC udp port>+42; ptracker will try all these ports on the ac server's ip address (until a better solution is found...)"),
            'server_name': ('acserver', conf.get, 'name for the server; sessions in the database will be tagged with that name; useful when more than one server is running in parallel on the same database'),
            'log_file': ('./stracker.log', conf.get, 'name of the stracker log file (utf-8 encoded), all messages go into there'),
            'tee_to_stdout': (False, conf.getboolean, 'set to 1, if you want the messages appear on stdout'),
            'log_level': (logger.LOG_LEVEL_INFO, self.getLogLevel, 'Valid values are "info", "debug" and "dump". Use "dump" only for problem analysis, log files can get very big.'),
            'append_log_file' : (False, conf.getboolean, 'Set to 1, if you want to append to log files rather than overwriting them. Only meaningful with external log file rotation system.'),
            'perform_checksum_comparisons': (False, conf.getboolean, 'set to 1, if you want stracker to compare the players checksums.'),
            'ptracker_connection_mode': (self.PTC_ANY, self.getPtrackerConnectionMode, 'Configure which ptracker instances shall be allowed to connect: Valid values are "any", "newer" or "none".'),
            'log_timestamps': (False, conf.getboolean, 'set to true, if you want the log messages to be prefixed with a timestamp'),
            'lower_priority': (True, conf.getboolean, 'set to true, if you want stracker to reduce its priority. Will use BELOW_NORMAL on windows and nice(5) on linux.'),
            'keep_alive_ptracker_conns': (True, conf.getboolean, 'set to false, if you want to disable the TCP keep_alive option (that was the behaviour pre 3.1.7).'),
            'guids_based_on_driver_names': (False, conf.getboolean, 'you normally want to leave that at the default (False). Use case for this is an environment where the same steam account is used by different drivers.'),
        }
        self.sections['SWEAR_FILTER'] = {
            'warning': ('Please be polite and do not swear in the chat. You will be %(swear_action)s from the server after receiving %(num_warnings_left)d more warnings.', conf.get, 'message sent to player after a swear detection'),
            'num_warnings': (3, conf.getint, 'Specify the number of warnings issued before the player is going to be kicked.'),
            'action': (self.SF_NONE, self.getSwearAction, 'Valid values are "none", "kick" and "ban".'),
            'ban_duration': (30, conf.getint, 'Number of days the player shall be banned (if action is "ban").'),
            'swear_file' : ('bad_words.txt', conf.get, 'Specify a file with bad words (one in each line). See https://github.com/shutterstock/List-of-Dirty-Naughty-Obscene-and-Otherwise-Bad-Words for examples.'),
        }
        self.sections['SESSION_MANAGEMENT'] = {
            'race_over_strategy': (self.ROS_NONE, self.getRaceOverStrategy, 'What to do when the race is over and no player is actively racing. Valid values are: "none" or "skip".'),
            'wait_secs_before_skip': (15, conf.getint, 'Number of seconds to wait before the session skip is executed (if race_over_strategy is set to "skip")'),
        }
        self.sections['MESSAGES'] = {
            'car_to_car_collision_msg' : (True, conf.getboolean, 'set to 1 to enable car to car private messages.'),
            'message_types_to_send_over_chat' : ("best_lap+welcome+race_finished", conf.get, 'available message types are "enter_leave","best_lap","checksum_errors","welcome","race_finished" and "collision". Connect them using a + sign without spaces.'),
            'best_lap_time_broadcast_threshold' : (105, conf.getfloat, 'Lap times below this threshold (in percent of the best time) will be broadcasted as best laps. Lap times above this will be whispered to the player achieving it.'),
        }
        self.sections['DATABASE'] = {
            'database_type' : (self.DBTYPE_SQLITE3, self.getDatabaseType, 'Valid values are "sqlite3" and "postgres". Selects the database to be used.'),
            'database_file' : ('./stracker.db3', conf.get, 'Only relevant if database_type=sqlite3. Path to the stracker database. If a relative path is given, it is relative to the <stracker> executable'),
            'postgres_host' : ('localhost', conf.get, 'name of the host running the postgresql server.'),
            'postgres_user' : ('myuser', conf.get, 'name of the postgres user.'),
            'postgres_db'   : ('stracker', conf.get, 'name of the postgres database.'),
            'postgres_pwd'  : ('password', conf.get, 'name of the postgres user password.'),
            'perform_backups' : (True, conf.getboolean, 'Set to "False", if you do not want stracker to backup the database before migrating to a new db version. Note: The backups will be created as sqlite3 db in the current working directory.'),
        }
        self.sections['DB_COMPRESSION'] = {
            'mode' : (self.DBCOMPRESSION_HI_SAVE_ALL, self.getCompressionLevel,
                     'Various options to minimize database size. Valid values are "none" (no compression, save all available infos), "remove_slow_laps" (save detailed infos for fast laps only) and "remove_all" (save no detailed lap info).'),
            'interval' : (60, conf.getint, 'Interval of database compression in minutes.'),
            'needs_empty_server' : (1, conf.getboolean, 'If set to 1, database compression will only take place if the server is empty.'),
        }
        self.sections['HTTP_CONFIG'] = {
            'enabled' : (False, conf.getboolean, 'set to 1, if you want to start a http server for statistics access'),
            'listen_port' : (50041, conf.getint, 'tcp listening port of the http server'),
            'listen_addr' : ('0.0.0.0', conf.get, 'listening address of the http server (normally there is no need to change the default value 0.0.0.0 which means that the whole internet can connect to the server)'),
            'admin_username' : ('', conf.get, 'username for the stracker admin pages (leaving it empty results in disabled admin pages'),
            'admin_password' : ('', conf.get, 'password for the stracker admin pages (leaving it empty results in disabled admin pages'),
            'items_per_page' : (15, conf.getint, 'number of items displayed per page'),
            'banner' : ('', conf.get, 'icon to be used in webpages (leave empty for default Assetto Corsa icon)'),
            'enable_svg_generation' : (True, conf.getboolean, 'set to false if you do not want svg graphs in the http output (for saving bandwidth)'),
            'log_requests' : (False, conf.getboolean, 'If set to true, http requests will be logged in stracker.log. Otherwise they are not logged.'),
            'auth_log_file' : ('', conf.get, 'Set to a file to be used for logging http authentication requests. Useful to prevent attacks with external program (e.g., fail2ban).'),
            'enable_paypal_link' : (True, conf.getboolean, 'Enable paypal link for letting users donate to the author. If you do not like that, switch it off.'),
            'max_streaming_clients' : (10, conf.getint, 'Maximum number of streaming clients (LiveMap/Log users) allowed to connect to this server in parallel. The number of threads allocated for http serving will be max(10, max_streaming_clients + 5)'),
            'lap_times_add_columns' : ('valid+aids+laps+date', conf.get, 'Additional columns to be displayed in LapTimes table (seperated by a + sign). Columns can be "valid", "aids", "laps", "date", "grip", "cuts", "collisions", "tyres", "temps", "ballast" and "vmax". Note that too many displayed columns might cause problems on some browsers.'),
            'inverse_navbar' : (False, conf.getboolean, 'set to true to get the navbar inverted (i.e., dark instead of bright)'),
            'velocity_unit' : (self.VU_KMH, self.getVelUnit, 'Valid values are "kmh" or "mph".'),
            'temperature_unit' : (self.TU_DEGC, self.getTempUnit, 'Valid values are "degc" or "degf".'),
        }
        self.sections['BLACKLIST'] = {
            'blacklist_file' : ('', conf.get, 'Path to blacklist.txt of ac server. If empty, blacklist support will not be available. Changes to blacklist file require an AC server restart to be active.'),
        }
        self.sections['WELCOME_MSG'] = {
            'line1' : ('Welcome to stracker %(version)s', conf.get, 'First line of welcome message text (if not empty, this text is sent a player when he enters the server'),
            'line2' : ('', conf.get, 'Second line of welcome message text (if not empty, this text is sent a player when he enters the server'),
            'line3' : ('', conf.get, 'Third line of welcome message text (if not empty, this text is sent a player when he enters the server'),
        }
        self.sections['ACPLUGIN'] = {
            'rcvPort' : (-1, conf.getint, 'udp port the plugins receives from. -1 means to use the AC servers setting UDP_PLUGIN_ADDRESS'),
            'sendPort' : (-1, conf.getint, 'udp port the plugins sends to. -1 means to use the AC servers setting UDP_PLUGIN_LOCAL_PORT'),
            'proxyPluginPort' : (-1, conf.getint, 'proxy the AC server protocol on these ports, so multiple plugins may be chained (this is equivalent to UDP_PLUGIN_ADDRESS in server_cfg.ini)'),
            'proxyPluginLocalPort' : (-1, conf.getint, 'proxy the AC server protocol on these ports, so multiple plugins may be chained (this is equivalent to UDP_PLUGIN_LOCAL_PORT in server_cfg.ini)'),
        }
        self.sections['LAP_VALID_CHECKS'] = {
            'invalidateOnEnvCollisions' : (True, conf.getboolean, 'if true, collisions with environment objects will invalidate laps'),
            'invalidateOnCarCollisions' : (True, conf.getboolean, 'if true, collisions with other cars will invalidate laps'),
            'ptrackerAllowedTyresOut'   : (-1, conf.getint, 'if -1: use server penalty setting, if available, otherwise use 2. All other values are passed to ptracker.'),
        }
        self.save()

    def save(self):
        conf = self.config
        for s in self.sections:
            if not conf.has_section(s):
                conf.add_section(s)
            v = getattr(self, s)
        if not self.dirtyConfig:
            return
        try:
            if os.path.isfile(self.ini_file_name):
                backup = self.ini_file_name + ".bak"
                shutil.move(self.ini_file_name, backup)
                acinfo("Created backup for old ini file name in %s", backup)
            else:
                acwarning("Old config file does not exist, no backup needed.")
        except:
            acwarning("Cannot create backup of old config file.")
        acinfo("Overwriting config file because of new options added.")
        try:
            f = open(self.ini_file_name, 'w')
            for s in self.sections:
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
                    self.dirtyConfig = True
                    d[o] = defaultVal
            self.__dict__[attr] = SectionRes(**d)
        return self.__dict__[attr]

def reread_acconfig(assert_options_unchanged):
    global acconfig
    acconfig_old = acconfig
    mr_old = minorating_enabled()
    acconfig = configparser.ConfigParser(strict=False, interpolation=None, allow_no_value=True)
    acconfig.read(config.STRACKER_CONFIG.ac_server_cfg_ini)
    for section,option in assert_options_unchanged:
        if acconfig[section][option] != acconfig_old[section][option]:
            raise AssertionError
    if mr_old != minorating_enabled():
        mino_message()

mino_message_logged = False
def mino_message():
    global mino_message_logged
    mino_message_logged = True
    if minorating_enabled():
        acinfo("server is configured for minorating usage. MR cache is enabled.")
    else:
        acinfo("server is not configured for minorating usage. MR cache is disabled.")

def minorating_enabled():
    res = 'minorating.com' in acconfig["SERVER"].get('AUTH_PLUGIN_ADDRESS', '')
    if not mino_message_logged:
        mino_message()
    return res

def create_config(ini_file_name, logger):
    global config, acconfig
    config = Config(ini_file_name, logger)
    if not os.path.exists(config.STRACKER_CONFIG.ac_server_cfg_ini):
        acerror("AC server config path not found (configured: '%s')",
                config.STRACKER_CONFIG.ac_server_cfg_ini)
        acerror("Please set the config option [STRACKER_CONFIG]/acserver_cfg_ini to the server_cfg.ini file of the ac server!")
        raise RuntimeError
    acconfig = configparser.ConfigParser(strict=False, interpolation=None, allow_no_value=True)
    acconfig.read(config.STRACKER_CONFIG.ac_server_cfg_ini)
    if not 'SERVER' in acconfig:
        acerror("AC server config does not contain section [SERVER], but this is needed for continueing!")
        raise RuntimeError
    for o in ['UDP_PORT']:
        if not o in acconfig['SERVER']:
            acerror("AC server config does not contain option [SERVER]/%s, but this is needed for continueing!", o)
            raise RuntimeError

def create_default_config(logger):
    global config
    config = Config(None, logger)
    config.HTTP_CONFIG.lap_times_add_columns = 'valid+aids+laps+date+tyres+vmax'
