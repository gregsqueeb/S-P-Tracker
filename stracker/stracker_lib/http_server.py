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

import pickle
import datetime
import functools
import time
import os.path
import re
import sys
import logging
import traceback
import random
import shutil
import simplejson as json
import math
import zipfile
import cgi
import re
from collections import OrderedDict,deque

import cherrypy
from cherrypy.lib import auth_digest

from ptracker_lib.helpers import isProMode, format_time_ms, format_datetime, unixtime2datetime, datetime2unixtime, format_time, localtime2utc, utc2localtime, unixtime_now, format_time_s
from ptracker_lib.dbgeneric import decompress
from ptracker_lib import read_ui_data
from stracker_lib.logger import *
from stracker_lib import config
from stracker_lib import entry_list
from stracker_lib import streaming_support
from stracker_lib import stracker_shm
from stracker_lib import livemap
from stracker_lib import acauth
from stracker_lib import tail
from stracker_lib import http_server_base
from stracker_lib import version

from acplugins4python import ac_server_protocol

from http_templates.tmpl_base import baseTemplate
from http_templates.tmpl_players import playersTemplate
from http_templates.tmpl_championship import pointSchemaTemplate
from http_templates.tmpl_groups import groupsTemplate
from http_templates.tmpl_generaladmin import generalAdminTemplate
from http_templates.tmpl_log import logTemplate
from http_templates.tmpl_livemap import livemapTemplate, livemapClassification
from http_templates.tmpl_chat import chatlogTemplate

db = None
banlist = None
started = False

def exceptionLogger(f):
    def new_f(*args, **kw):
        try:
            return f(*args, **kw)
        except:
            acerror(traceback.format_exc())
            raise
    new_f.__name__ = f.__name__
    return new_f

def my_auth_digest(realm, get_ha1, key, debug=False):
    try:
        return auth_digest.digest_auth(realm, get_ha1, key, debug=False)
    except cherrypy.HTTPError as e:
        hdr = cherrypy.serving.response.headers['WWW-Authenticate']
        if 'stale="true"' in hdr:
            # silently ignore failures due to stale nonce values
            raise e
        auth_header = cherrypy.request.headers.get('authorization')
        if not auth_header is None:
            try:
                auth = auth_digest.HttpDigestAuthorization(auth_header, cherrypy.request.method, debug=debug)
                username = auth.username
                timestamp = datetime.datetime.now().strftime("%b %d %H:%M:%S")
                processid = os.getpid()
                rname = cherrypy.request.remote.name
                rip = cherrypy.request.remote.ip
                acwarning("http authentication failure; username=%s rhost=%s rip=%s",
                    username, rname, rip)
                lf = config.config.HTTP_CONFIG.auth_log_file
                if lf != "":
                    try:
                        open(lf, "a").write(
                            "%s stracker.http_auth[%d]: http authentication failure; username=%s rhost=%s rip=%s\n" % (
                                timestamp, processid, username, rname, rip))
                    except:
                        acwarning("Cannot write authentication failure to specified log file %s", lf)
                        acwarning(traceback.format_exc())
            except ValueError:
                pass
        raise e

cherrypy.tools.my_auth_digest = cherrypy.Tool('before_handler', my_auth_digest, priority=1)

def add_url(f):
    def new_f(*args, **kw):
        kw['curr_url'] = cherrypy.request.request_line.split(" ")[1]
        return f(*args, **kw)
    return new_f

class StrackerPublic(http_server_base.StrackerPublicBase):
    cp_config = {
        '/img' : {
            'tools.expires.on'    : True,
            'tools.expires.secs'  : 3600*24*7,
            'tools.staticdir.on' : True,
            'tools.staticdir.dir' : os.path.abspath(os.path.join(http_server_base.static_base_dir, "http_static", "img")),
        },
        '/jquery' : {
            'tools.expires.on'    : True,
            'tools.expires.secs'  : 3600*24*7,
            'tools.staticdir.on' : True,
            'tools.staticdir.dir' : os.path.abspath(os.path.join(http_server_base.static_base_dir, "http_static", "jquery")),
        },
        '/bootstrap' : {
            'tools.expires.on'    : True,
            'tools.expires.secs'  : 3600*24*7,
            'tools.staticdir.on' : True,
            'tools.staticdir.dir' : os.path.abspath(os.path.join(http_server_base.static_base_dir, "http_static", "bootstrap")),
        },
        '/pygal' : {
            'tools.expires.on'    : True,
            'tools.expires.secs'  : 3600*24*7,
            'tools.staticdir.on' : True,
            'tools.staticdir.dir' : os.path.abspath(os.path.join(http_server_base.static_base_dir, "http_static", "pygal")),
        }
    }
    def __init__(self, rootpage="/"):
        super().__init__()
        self.rootpage=rootpage

    lapstat = cherrypy.expose(add_url(cherrypy.tools.caching(delay=60)(http_server_base.StrackerPublicBase.lapstat)))

    @cherrypy.expose
    @add_url
    @cherrypy.tools.sessions()
    def lapdetails(self, lapid, cmpbits=None, curr_url=None):
        return super().lapdetails(lapid=lapid, cmpbits=cmpbits, cmp_lapid=cherrypy.session.get('cmp_lapid', None), curr_url=curr_url)
    #lapdetails = cherrypy.expose(add_url((http_server_base.StrackerPublicBase.lapdetails)))

    sessionstat = cherrypy.expose(add_url(cherrypy.tools.caching(delay=60)(http_server_base.StrackerPublicBase.sessionstat)))
    sessiondetails = cherrypy.expose(add_url(cherrypy.tools.caching(delay=60)(http_server_base.StrackerPublicBase.sessiondetails)))
    players = cherrypy.expose(add_url(cherrypy.tools.caching(delay=60)(http_server_base.StrackerPublicBase.players)))
    playerdetails = cherrypy.expose(add_url(cherrypy.tools.caching(delay=60)(http_server_base.StrackerPublicBase.playerdetails)))
    mainpage = cherrypy.expose(add_url(cherrypy.tools.caching(delay=3600)(http_server_base.StrackerPublicBase.mainpage)))
    statistics = cherrypy.expose(add_url(cherrypy.tools.caching(delay=3600)(http_server_base.StrackerPublicBase.statistics)))
    lapspertrack_svg = cherrypy.expose(add_url(cherrypy.tools.caching(delay=3600)(http_server_base.StrackerPublicBase.lapspertrack_svg)))
    lapspercar_svg = cherrypy.expose(add_url(cherrypy.tools.caching(delay=3600)(http_server_base.StrackerPublicBase.lapspercar_svg)))
    serverstats_svg = cherrypy.expose(add_url(cherrypy.tools.caching(delay=3600)(http_server_base.StrackerPublicBase.serverstats_svg)))
    lapspercombo_svg = cherrypy.expose(add_url(cherrypy.tools.caching(delay=3600)(http_server_base.StrackerPublicBase.lapspercombo_svg)))
    ltcomparison_svg = cherrypy.expose(add_url(cherrypy.tools.caching(delay=300)(http_server_base.StrackerPublicBase.ltcomparison_svg)))
    championship = cherrypy.expose(add_url(cherrypy.tools.caching(delay=300)(http_server_base.StrackerPublicBase.championship)))
    ltcomparisonmap_svg = cherrypy.expose(add_url(cherrypy.tools.caching(delay=300)(http_server_base.StrackerPublicBase.ltcomparisonmap_svg)))
    carbadge = cherrypy.expose(add_url(cherrypy.tools.caching(delay=10)(http_server_base.StrackerPublicBase.carbadge)))
    trackmap = cherrypy.expose(add_url(cherrypy.tools.caching(delay=10)(http_server_base.StrackerPublicBase.trackmap)))

    def isAdmin(self):
        if (config.config.HTTP_CONFIG.admin_username != "" and
            config.config.HTTP_CONFIG.admin_password != ""):
            return cherrypy.request.login == config.config.HTTP_CONFIG.admin_username
        else:
            return None

    def redirect(self, name, **kw):
        s = "?"
        new_url = name
        for p in kw:
            v = kw[p]
            if not v is None:
                new_url += s + p + "=" + str(kw[p])
                s = "&"
        raise cherrypy.HTTPRedirect(new_url)

    def features(self):
        return {'admin': self.isAdmin(),
                'banlist': banlist.available(),
                'version': version,
                'checksum_tests':config.config.STRACKER_CONFIG.perform_checksum_comparisons,
                'flattr':False,
                'paypal':config.config.HTTP_CONFIG.enable_paypal_link,
                'pts': False,
                }

    @cherrypy.expose
    @add_url
    def acauth(self, **kw):
        return acauth.acauth(self.features()['admin'], db, **kw)

    @cherrypy.expose
    @add_url
    @cherrypy.tools.sessions()
    def lapdetails_store_lapid(self, lapid, cmpbits=None, curr_url=None):
        lapid = int(lapid)
        cherrypy.session['cmp_lapid'] = lapid
        self.redirect("lapdetails", lapid=lapid, cmpbits=cmpbits)

    @cherrypy.expose
    @add_url
    def default(self, *args, **kw):
        self.redirect("mainpage")

    @cherrypy.expose
    @add_url
    def livemap(self, server=None, curr_url=None):
        servers = sorted(db.allservers(__sync=True)())
        if server is None:
            server = config.config.STRACKER_CONFIG.server_name
        si = livemap.SessionInfo()
        try:
            b = stracker_shm.get(server, 'session_info')
            si.from_buffer(b, 1)
        except stracker_shm.ServerError:
            si.track = "<server down>"
        track = si.track
        try:
            td = self.trackAndCarDetails()['tracks']
        except:
            acerror("td=%s", str(td))
            td = self.trackAndCarDetails()['tracks']
        td = dict(map(lambda x: (x['acname'], x), td))
        self.trackmap(track=track, curr_url=curr_url)
        if track in td and td[track]['mapdata']:
            mapdata = pickle.loads(td[track]['mapdata'])
            scale = 1./float(mapdata['ini']['scale'])
            offsetx = float(mapdata['ini']['xoffset'])
            offsetz = float(mapdata['ini']['zoffset'])
            width = float(mapdata['ini']['width'])
            height = float(mapdata['ini']['height'])
            track_image = "trackmap?track=%s" % track
        else:
            scale = 0.001
            offsetx = 50000
            offsetz = 50000
            width = 640
            height = 480
            track_image = "/img/nomap.png"
        r = livemapTemplate.render(server=server, servers=servers, key=streaming_support.new_key(),
                                   track_image = track_image, width=width, height=height,
                                   scale=scale, offsetx=offsetx, offsety=offsetz, features=self.features())
        return baseTemplate.render(base=r, pagination=None, src="livemap", rootpage=self.rootpage, features=self.features(), pygal=True, curr_url=curr_url)


    @cherrypy.expose
    @add_url
    @streaming_support.json_yield
    #@cherrypy.tools.caching(delay=0.2)
    def livemap_stream(self, server=None, global_scale=1., curr_url=None):
        self.streamingClientsCount += 1
        last_res_c = None
        last_res_s = None
        last_res_p = None
        last_res_a = None
        last_res_chat = None
        last_alive_t = time.time()
        last_alive_active = False
        try:
            acdebug("streaming started")
            td = self.trackAndCarDetails()['tracks']
            td = dict(map(lambda x: (x['acname'], x), td))

            global_scale = float(global_scale)
            radius = 2*global_scale
            if radius < 5:
                radius = 5
            font_size_f = 14/global_scale
            font_size = "%dpx" % round(font_size_f)

            while not stopNow:
                # fetch server's session info
                sessionInfo = livemap.SessionInfo()
                try:
                    b = stracker_shm.get(server, 'session_info')
                    sessionInfo.from_buffer(b, 1)
                except stracker_shm.ServerError:
                    sessionInfo.track = "<server down>"

                # fetch server's classification info
                connected = {}
                rank_map = {}
                maxLaps = 0
                colors = ["maroon", "green", "olive", "navy", "purple", "teal", "gray"]
                color_map = {}
                try:
                    classInfo = stracker_shm.get(server, 'classification')
                    carClassEntries = []
                    for b in classInfo:
                        ci = livemap.CarClassification()
                        ci.from_buffer(b, 1)
                        carClassEntries.append(ci)
                        connected[ci.guid] = ci.connected
                        rank_map[ci.guid] = ci.pos
                        maxLaps = max(ci.lapCount, maxLaps)
                    guids = [x.guid for x in carClassEntries]
                    for guid in sorted(guids):
                        color_map[guid] = colors[len(color_map) % len(colors)]
                    res_c = livemapClassification.render(server=server, sessionInfo=sessionInfo, classInfo=classInfo, carClassEntries=carClassEntries, color_map=color_map, features=self.features())
                except stracker_shm.ServerError:
                    res_c = ""

                # generate session info
                res_s = ''
                types = {
                    ac_server_protocol.SESST_PRACTICE: 'Practice',
                    ac_server_protocol.SESST_QUALIFY: 'Qualify',
                    ac_server_protocol.SESST_RACE: 'Race',
                    ac_server_protocol.SESST_DRAG: 'Drag',
                    ac_server_protocol.SESST_DRIFT: 'Drift',
                }
                track = td[sessionInfo.track].get('uiname', sessionInfo.track)
                if track is None: track = sessionInfo.track
                track = cgi.escape(track)
                session_type = cgi.escape(types[sessionInfo.session_type])
                if sessionInfo.session_laps > 0:
                    duration = cgi.escape('%d / %d laps'%(maxLaps, sessionInfo.session_laps))
                else:
                    timeLeft = sessionInfo.session_duration*60*1000 - sessionInfo.elapsedMS
                    timeLeft = format_time_s(int(timeLeft))
                    duration = cgi.escape(timeLeft)
                res_s = '<td>%(track)s</td><td>%(session_type)s</td><td>%(duration)s</td>\n' % locals()


                # fetch server's car positions
                try:
                    cpr = stracker_shm.get(server, 'car_positions')
                    res_p = ''
                    alive = True
                    for r in cpr:
                        cp = livemap.CarPosition()
                        cp.from_buffer(r, 1)
                        guid = cp.guid
                        if connected.get(guid, False):
                            pos = rank_map[guid]
                            color = color_map[guid]
                            x = cp.x
                            y = cp.y
                            res_p += '<circle r="%(radius).2f" cx="%(x).2f" cy="%(y).2f" fill="%(color)s" stroke="none"></circle>\n' % locals()
                            fx = x+radius*1.5
                            fy = y+radius*1.5
                            res_p += '<text x="%(fx).2f" y="%(fy).2f" style="font-family:verdana; font-size:%(font_size)s" stroke="%(color)s" fill="%(color)s">%(pos)d</text>' % locals()
                except stracker_shm.ServerError:
                    res_p = ''
                    alive = False

                # update alive data
                res_a = ''
                radius = 2*global_scale
                if radius < 6:
                    radius = 6
                center = radius + 3
                if alive:
                    t = time.time()
                    if t - last_alive_t > 1.5:
                        last_alive_t = t
                        last_alive_active = not last_alive_active
                    if last_alive_active:
                        res_a += '<circle r="%(radius)d" cx="%(center)d" cy="%(center)d" fill="green" stroke="darkgreen"></circle>\n' % locals()
                    else:
                        res_a += '<circle r="%(radius)d" cx="%(center)d" cy="%(center)d" fill="none" stroke="none"></circle>\n' % locals()
                else:
                    res_a += '<circle r="%(radius)d" cx="%(center)d" cy="%(center)d" fill="red" stroke="darkred"></circle>\n' % locals()

                # update chat data
                try:
                    chat_messages = stracker_shm.get(server, 'chat_messages')
                    y = center + radius + font_size_f
                    res_chat = ''
                    for t,name,msg in chat_messages:
                        res_chat += '<text x="0.0" y="%(y).2f" style="font-family:verdana; font-size:%(font_size)s" stroke="green" fill="green">%(name)s: %(msg)s</text>' % locals()
                        y += font_size_f*1.5
                except stracker_shm.ServerError:
                    res_chat = ''

                res = {}
                if last_res_c != res_c:
                    res['class_data'] = res_c
                    last_res_c = res_c
                if last_res_p != res_p:
                    res['svg_data'] = res_p
                    last_res_p = res_p
                if last_res_chat != res_chat:
                    res['chat_data'] = res_chat
                    last_res_chat = res_chat
                if last_res_s != res_s:
                    res['session_data'] = res_s
                    last_res_s = res_s
                if last_res_a != res_a:
                    res['alive_data'] = res_a
                    last_res_a = res_a
                if len(res) > 0:
                    yield res
                time.sleep(0.25)
        except:
            acdebug("exception in livemap_stream")
            acdebug(traceback.format_exc())
        finally:
            self.streamingClientsCount -= 1


class StrackerAdmin(StrackerPublic):
    def __init__(self, username, password):
        self.cp_config = {
            '/' :  {
                'tools.my_auth_digest.on': True,
                'tools.my_auth_digest.realm': 'stracker admin area',
                'tools.my_auth_digest.get_ha1': auth_digest.get_ha1_dict_plain(
                    {username : password}
                ),
                'tools.my_auth_digest.key': random.getrandbits(64),
            }
        }
        StrackerPublic.__init__(self, "/admin/")

    @cherrypy.expose
    @add_url
    def banlist(self, search_pattern = "", page = 0, curr_url=None):
        page = int(page)
        nip = self.itemsPerPage
        res = db.getPlayers(__sync=True, limit=[page*nip+1, nip], searchPattern = search_pattern, inBanList=True)()
        r = playersTemplate.render(res=res, search_pattern=search_pattern, features=self.features(), caller = "banlist")
        return baseTemplate.render(base=r, pagination=(page, (res['count']+nip-1)//nip), src="banlist", rootpage=self.rootpage, features=self.features(), pygal=False, curr_url=curr_url)

    @cherrypy.expose
    @add_url
    def ban(self, pid, period=None, unban=None, extendPeriod=None, curr_url=None):
        if hasattr(cherrypy, "_cache"): cherrypy._cache.clear()
        if not period is None:
            res = db.modifyBlacklistEntry(__sync=True, playerid=pid, addBan=int(period))()
        elif unban:
            res = db.modifyBlacklistEntry(__sync=True, playerid=pid, unban=True)()
        elif not extendPeriod is None:
            res = db.modifyBlacklistEntry(__sync=True, playerid=pid, extendPeriod=int(extendPeriod))()
        acauth.AuthCache.singleton.reset()
        banlist.regenerateBlacklist()
        self.redirect("playerdetails", pid=pid)

    @cherrypy.expose
    @add_url
    def groups(self, group_id = None, page = 0, curr_url=None):
        page = int(page)
        group_id = int(group_id if not group_id is None else 0)
        nip = self.itemsPerPage
        res = db.getPlayers(__sync=True, limit=[page*nip+1, nip], group_id=group_id, include_groups=True)()
        r = groupsTemplate.render(res=res, group_id=group_id, features=self.features())
        return baseTemplate.render(base=r, pagination=(page,(res['count']+nip-1)//nip), src="groups", rootpage=self.rootpage, features=self.features(), pygal=False, curr_url=curr_url)

    @cherrypy.expose
    @add_url
    def modify_groups(self, add_group=None, del_group=None, add_player_id=None, group_id=None, del_player_id=None, curr_url=None):
        if hasattr(cherrypy, "_cache"): cherrypy._cache.clear()
        if not add_group is None:
            group_id = db.modifyGroup(__sync=True, add_group=add_group)()
        elif not del_group is None:
            db.modifyGroup(__sync=True, del_group=int(del_group))()
            group_id = None
        elif not add_player_id is None:
            group_id = int(group_id)
            db.modifyGroup(__sync=True, add_player_id=int(add_player_id), group_id=group_id)
        elif not del_player_id is None:
            group_id = int(group_id)
            db.modifyGroup(__sync=True, del_player_id=int(del_player_id), group_id=group_id)
        self.redirect("groups", group_id=group_id)

    @cherrypy.expose
    @add_url
    def modify_whitelist(self, whitelist_player_id=None, unwhitelist_player_id=None, curr_url=None):
        if hasattr(cherrypy, "_cache"): cherrypy._cache.clear()
        if not whitelist_player_id is None:
            playerid = whitelist_player_id
            db.modifyGroup(__sync=True, whitelist_player_id=int(whitelist_player_id))
        elif not unwhitelist_player_id is None:
            playerid = unwhitelist_player_id
            db.modifyGroup(__sync=True, unwhitelist_player_id=int(unwhitelist_player_id))
        self.redirect("playerdetails", pid=playerid)

    @cherrypy.expose
    @add_url
    def modify_cs(self,
                  add_season=None, del_season=None,
                  add_event=None, del_event=None, cs_id=None,
                  event_id=None, ps_id=None, session_name=None, session_id=None,
                  remove_event_session_id=None, curr_url=None):
        if hasattr(cherrypy, "_cache"): cherrypy._cache.clear()
        if not cs_id is None: cs_id = int(cs_id)
        if not event_id is None: event_id = int(event_id)
        if not ps_id is None: ps_id = int(ps_id)
        if not session_id is None: session_id = int(session_id)
        if not remove_event_session_id is None: remove_event_session_id = int(remove_event_session_id)
        new_url = None
        if not add_season is None:
            cs_id = db.csModify(__sync=True, add_season_name=add_season)()
        elif not del_season is None:
            db.csModify(__sync=True, del_season=del_season)()
        elif not add_event is None:
            event_id = db.csModify(__sync=True, add_event_name=add_event, cs_id=cs_id)()
        elif not del_event is None:
            db.csModify(__sync=True, del_event=int(del_event))()
        elif not event_id is None and not ps_id is None and not session_name is None:
            db.csModify(__sync=True, add_session_name=session_name, event_id=event_id, ps_id=ps_id, session_id=session_id)
        elif not remove_event_session_id is None and not session_id is None:
            db.csModify(__sync=True, remove_event_session_id=remove_event_session_id)
            self.redirect("sessiondetails", sessionid=session_id)
        self.redirect("championship", cs_id=cs_id, event_id=event_id)

    @cherrypy.expose
    @add_url
    def point_schemata(self, ps_id=None, curr_url=None):
        if not ps_id is None: ps_id = int(ps_id)
        csRes = db.csGetSeasons(__sync=True, cs_id=None)()
        r = pointSchemaTemplate.render(point_schemata=csRes['point_schemata'], ps_id=ps_id, features=self.features())
        return baseTemplate.render(base=r, pagination=None, src="cs", rootpage=self.rootpage, features=self.features(), pygal=False, curr_url=curr_url)

    @cherrypy.expose
    @add_url
    def modify_point_schema(self, ps_id=None, add_schema=None, del_schema=None, pos=None, points=None, delpos=None, curr_url=None):
        if hasattr(cherrypy, "_cache"): cherrypy._cache.clear()
        if not ps_id is None: ps_id = int(ps_id)
        if not del_schema is None: del_schema = int(del_schema)
        if not add_schema is None:
            ps_id = db.csModify(__sync=True, add_schema_name=add_schema)()
        elif not del_schema is None:
            db.csModify(__sync=True, del_schema=del_schema)()
            ps_id = None
        elif not pos is None and not points is None and not ps_id is None:
            points = float(points)
            pos = int(pos)
            db.csModify(__sync=True, ps_id=ps_id, pos=pos, points=points)
        elif not delpos is None and not ps_id is None:
            db.csModify(__sync=True, ps_id=ps_id, delpos=delpos)
        self.redirect("point_schemata", ps_id=ps_id)

    @cherrypy.expose
    @add_url
    def modify_session_penalties(self, pisId, session_id, dt=None, dp=None, dl=None, pc=None, curr_url=None):
        if hasattr(cherrypy, "_cache"): cherrypy._cache.clear()
        if dt.strip() == "": dt = None
        if dp.strip() == "": dp = None
        if dl.strip() == "": dl = None
        if pc.strip() == "": pc = None

        if not dt is None:
            M = re.match(r'([+-]?)\s*((\d+):)?(\d+)\.(\d+)', dt)
            if not M is None:
                sign = M.group(1)
                minutes = M.group(3) if not M.group(3) is None else '0'
                seconds = M.group(4)
                msecs = int(float("."+M.group(5))*1000)
                dt = int(sign+minutes)*60*1000 + int(seconds)*1000 + int(msecs)
        if not dp is None:
            dp = float(dp.replace(" ", ""))
        if not dl is None:
            dl = int(dl.replace(" ", ""))

        pisId = int(pisId)
        session_id = int(session_id)
        db.playerInSessionPaCModify(__sync=True, pis_id=pisId, delta_time=dt, delta_points=dp, delta_laps=dl, comment=pc)
        self.redirect("sessiondetails", sessionid = session_id)

    @cherrypy.expose
    @add_url
    def modify_lap(self, lapid, valid, curr_url=None):
        if hasattr(cherrypy, "_cache"): cherrypy._cache.clear()
        lapid = int(lapid)
        valid = int(valid)
        db.modifyLap(__sync=True, lapid=lapid, valid=valid)
        self.redirect("lapdetails", lapid=lapid)

    @cherrypy.expose
    @add_url
    def modify_reqchecksum(self, lapid, track=None, track_checksum=None, car=None, car_checksum=None, curr_url=None):
        if hasattr(cherrypy, "_cache"): cherrypy._cache.clear()
        db.modifyRequiredChecksums(__sync=True, track=track, reqTrackChecksum=track_checksum, car=car, reqCarChecksum=car_checksum)
        self.redirect("lapdetails", lapid=lapid)

    @cherrypy.expose
    @add_url
    def entry_list(self, sessionid, curr_url=None):
        res = db.sessionDetails(__sync=True, sessionid=sessionid)()
        try:
            return entry_list.generate_entry_list(res)
        except:
            acerror("Error while generating entry list: ")
            acerror(traceback.format_exc())
            raise RuntimeError("Entry list generation did not succeed. You need to have a matching entry_list.ini file beneath your server configuration file.")

    @cherrypy.expose
    @add_url
    def championship_setteam(self, cs_id, pid, team_name, curr_url=None):
        if hasattr(cherrypy, "_cache"): cherrypy._cache.clear()
        if team_name == "":
            team_name = None
        db.csSetTeamName(__sync=True, cs_id=cs_id, pid=pid, team_name=team_name)()
        self.redirect("championship", cs_id=cs_id)

    @cherrypy.expose
    @add_url
    def general_admin(self, curr_url=None):
        self.resetTrackAndCarDetails()
        res = self.trackAndCarDetails()
        r = generalAdminTemplate.render(res=res, features=self.features())
        return baseTemplate.render(base=r, pagination=None, src="admin", rootpage=self.rootpage, features=self.features(), pygal=False, curr_url=curr_url)

    @cherrypy.expose
    @add_url
    def general_admin_remove(self,
                             allTrackData = None, trackUiName = None, trackLength = None, trackMap = None,
                             allCarData = None, carUiName = None, carBrand = None, carBadge = None, curr_url=None):
        if hasattr(cherrypy, "_cache"): cherrypy._cache.clear()
        tracks = []
        cars = []
        if not trackUiName is None: tracks.append(dict(track=trackUiName, uiname=None))
        if not trackLength is None: tracks.append(dict(track=trackLength, length=None))
        if not trackMap is None:    tracks.append(dict(track=trackMap, mapdata=None))
        if not allTrackData is None: tracks.append(dict(track=allTrackData, uiname=None, length=None, mapdata=None))
        if not carUiName is None:   cars.append(dict(car=carUiName, uiname=None))
        if not carBrand is None:    cars.append(dict(car=carBrand, brand=None))
        if not carBadge is None:    cars.append(dict(car=carBadge, badge=None))
        if not allCarData is None:  cars.append(dict(car=allCarData, uiname=None, brand=None, badge=None))
        db.trackAndCarDetails(__sync=True, tracks=tracks, cars=cars, overwrite=True)()
        self.resetTrackAndCarDetails()
        self.redirect("general_admin")

    @cherrypy.expose
    @add_url
    def invalidate_laps(self, servers=None, date_from=None, date_to=None, tracks=None, cars=None, curr_url=None):
        if hasattr(cherrypy, "_cache"): cherrypy._cache.clear()
        oservers = servers
        odate_from = date_from
        odate_to = date_to
        otracks = tracks
        ocars = cars

        date_from = self.toTimestamp(date_from)
        date_to = self.toTimestamp(date_to,24*60*60)

        if not servers is None:
            servers = servers.split(",")

        if not tracks is None:
            tracks = tracks.split(",")

        if not cars is None:
            cars = cars.split(",")

        stats = db.statistics(__sync=True, servers=servers, startDate=date_from[0], endDate=date_to[0], tracks=tracks, cars=cars, invalidate_laps=True)()
        self.redirect("statistics", servers=oservers, date_from=odate_from, date_to=odate_to, tracks=otracks, cars=ocars)

    @cherrypy.expose
    @add_url
    def log(self, limit=10, server=None, level="unclassified", curr_url=None):
        servers = sorted(db.allservers(__sync=True)())
        if server is None:
            server = config.config.STRACKER_CONFIG.server_name
        limit = int(limit)
        r = logTemplate.render(key=streaming_support.new_key(), limit=limit, server=server, servers=servers, level=level)
        return baseTemplate.render(base=r, pagination=None, src="log", rootpage=self.rootpage, features=self.features(), pygal=False, curr_url=curr_url)

    @cherrypy.expose
    @add_url
    @streaming_support.json_yield
    def log_stream(self, limit=10, server=None, level="unclassified", curr_url=None):

        def colorize(line):
            res = ('', cgi.escape(line), 4)
            cd = {"[ERROR"  : ("danger",0),
                  "[WARN"   : ("warning",1),
                  "[INFO"   : ("info",2),
                  "[DEBUG"  : ("default",3),
                  "[STDOUT" : ("primary",3),
                  }
            for l in cd:
                p1 = line.find(l)
                if p1 >= 0:
                    p2 = line.find(":", p1+1)
                    if p2 > p1:
                        lbl = cd[l][0]
                        level = cd[l][1]
                        res = ('<span class="label label-' + lbl + '">' + cgi.escape(line[:p2].strip()) + '</span>',
                               cgi.escape(line[p2+1:].strip()),
                               level)
            return res

        def process(new_lines, lastItem):
            lines = []
            for l in new_lines:
                cl = list(colorize(l))
                if not lastItem is None:
                    if cl[0] == '':
                        cl[0] = lines[-1][0]
                    if cl[2] == 4:
                        cl[2] = lines[-1][2]
                lastItem = cl
                lines.append(tuple(cl))
            return lines

        self.streamingClientsCount += 1
        acdebug("LOGSTREAM start %d", self.streamingClientsCount)
        try:
            limit = int(limit)
            level = {"error":0,"warning":1,"info":2,"debug":3,"unclassified":4}[level]
            acdebug("level=%d", level)
            if server is None:
                logfile = config.config.STRACKER_CONFIG.log_file
            else:
                logfile = stracker_shm.get(server, 'logfile')

            f = open(logfile, "r")
            f.seek(0, os.SEEK_END)
            oldPos = f.tell()
            lines = []
            cnt = 0
            # search last <limit> lines classified correctly
            for l in tail.reversed_lines(f):
                r = process([l], None)[0]
                lines = [l] + lines
                if r[2] <= level:
                    cnt += 1
                    if cnt == limit:
                        break
            f.seek(oldPos, os.SEEK_SET)
            lastItem = None
            lines = process(lines, lastItem)
            if len(lines): lastItem = lines[-1]
            lines = filter(lambda l: l[2] <= level, lines)
            ctail = "\n".join(["<tr><td>"+l[0]+"</td><td>"+l[1]+"</td></tr>" for l in lines])
            yield ctail
            pending = ""
            lastSendTime = time.time()
            while not stopNow:
                chunk = f.read()
                if len(chunk) == 0:
                    time.sleep(5)
                else:
                    pending += chunk
                    lines = pending.split("\n")
                    pending = lines[-1]
                    lines = process(lines[:-1], lastItem)
                    if len(lines): lastItem = lines[-1]
                    lines = filter(lambda l: l[2] <= level, lines)
                    fmt = "\n".join(["<tr><td>"+l[0]+"</td><td>"+l[1]+"</td></tr>" for l in lines])
                    if fmt != '':
                        yield fmt
                        lastSendTime = time.time()
                if time.time() - lastSendTime > 20:
                    yield ""
        except GeneratorExit:
            acdebug("generator exit")
        except KeyError:
            yield cgi.escape("<Server down?>")
        except stracker_shm.ServerError:
            yield cgi.escape("<Server down?>")
        except:
            yield cgi.escape("<Interrupted>")
            acerror("Exception in log_stream:")
            acerror(traceback.format_exc())
            self.streamingClientsCount -= 1
            return
        self.streamingClientsCount -= 1
        acdebug("LOG_STREAM stopped %d", self.streamingClientsCount)

    @cherrypy.expose
    @add_url
    def chatlog(self, server=None, date_from=None, date_to=None, page=0, curr_url=None):
        servers = sorted(db.allservers(__sync=True)())
        if server is None:
            server = config.config.STRACKER_CONFIG.server_name
        def convert_date(d):
            try:
                year,month,day = [int(x) for x in d.split("-")]
                return datetime2unixtime(datetime.datetime(year,month,day))
            except:
                return None
        date_from_ts = convert_date(date_from)
        date_to_ts = convert_date(date_to)
        try:
            page = int(page)
        except:
            page = 0
        nip = self.itemsPerPage
        res = db.filterChat(__sync=True, server=server, startTime=date_from_ts, endTime=date_to_ts, limit=[nip*page+1, nip])()
        r = chatlogTemplate.render(server=server, servers=servers, date_from=date_from, date_to=date_to, messages=res['messages'])
        totalPages=(res['totalCount']+nip-1)//nip
        return baseTemplate.render(base=r, pagination=[page, totalPages], src="log", rootpage=self.rootpage, features=self.features(), pygal=False, curr_url=curr_url)

    @cherrypy.expose
    @add_url
    def upload_sync_file(self, file_data, curr_url=None, *args, **kw):
        if hasattr(cherrypy, "_cache"):
            cherrypy._cache.clear()
        try:
            r = zipfile.ZipFile(file_data.file, "r")
            data = {}
            for m in r.infolist():
                try:
                    data = read_ui_data.read_ui_file(m.filename, r.open(m, "r"), data)
                except read_ui_data.JSONDecodeError:
                    acinfo("Problem with parsing %s (probably broken mod, ignored)", fn)
                except:
                    acwarning("Unexpected error while parsing json info:")
                    acerror(traceback.format_exc())

            tracks = data.get('tracks', {})
            cars = data.get('cars', {})

            if len(tracks) == 0 and len(cars) == 0:
                raise AssertionError
            trackres = []
            for t in tracks:
                td = tracks[t]
                if 'mini' in td and 'mpng' in td:
                    td['mapdata'] = pickle.dumps(dict(ini=td['mini'], png=td['mpng']))
                td.update({'track':t})
                trackres.append(td)
            carres = []
            for c in cars:
                cd = cars[c]
                cd.update({'car':c})
                carres.append(cd)
            db.trackAndCarDetails(__sync=True,tracks=trackres,cars=carres)()
            self.resetTrackAndCarDetails()
        except:
            acerror(traceback.format_exc())
            return json.dumps({'error': 'error during processing'})
        return json.dumps({})

    @cherrypy.expose
    @add_url
    def server_stats(self, curr_url=None):
        from ptracker_lib.ps_protocol import globalConnMon,ProtocolHandler
        def rid2str(rid):
            for k in ProtocolHandler.__dict__:
                if not k[:3] in ["REQ","ANS"]:
                    continue
                if getattr(ProtocolHandler, k) == rid:
                    return k
            return "?"
        chart = StackedLine(
             http_server_base.pygalConfig,
             fill=True,
             dots_size=0,
             #interpolate='', #'cubic',
             include_x_axis=True,
             x_title='Time [ms]',
             y_title='Sent bytes/seconds',
             title="server send traffic",
             legend_at_bottom = True,
             legend_font_size = 12,
             truncate_legend = 30)
        t0 = time.time()
        t,bw = globalConnMon.traffic_send(5., 120., t0, [254,255], [255])
        chart.add("html sent total", bw)
        t,bw = globalConnMon.traffic_rcv(5., 120., t0, [254,255], [255])
        chart.add("html rcv total", bw)
        t,bw = globalConnMon.traffic_send(5., 120., t0, range(255), range(9))
        chart.add("old prot sent total", bw)
        t,bw = globalConnMon.traffic_rcv(5., 120., t0, range(255), range(9))
        chart.add("old prot rcv total", bw)
        t,bw = globalConnMon.traffic_send(5., 120., t0, range(255), range(9,254))
        chart.add("new prot sent total", bw)
        t,bw = globalConnMon.traffic_rcv(5., 120., t0, range(255), range(9,254))
        chart.add("new prot rcv total", bw)

        return chart.render()

    @cherrypy.expose
    @add_url
    def whisper(self, guid, text, server, curr_url=None):
        stracker_shm.set('command_from_http', 'whisper guid %s %s' % (guid, text), server=server)
        self.redirect('livemap', server=server)

    @cherrypy.expose
    @add_url
    def broadcastchat(self, message, server, curr_url=None):
        server = None if server == "" else server
        stracker_shm.set('command_from_http', 'broadcast %s' % message, server=server)
        self.redirect('livemap', server=server)

    @cherrypy.expose
    @add_url
    def kick(self, guid, server, curr_url=None):
        stracker_shm.set('command_from_http', 'kickban guid %s 0' % guid, server=server)
        self.redirect('livemap', server=server)

    @cherrypy.expose
    @add_url
    def bannow(self, guid, days, server, curr_url=None):
        stracker_shm.set('command_from_http', 'kickban guid %s %d' % (guid, int(days)), server=server)
        self.redirect('livemap', server=server)

    @cherrypy.expose
    @add_url
    def manage_session(self, server, ptime="", qtime="", rlaps="", restart=False, skip=False, curr_url=None):
        server = None if server == "" else server
        if ptime != "":
            ptime = int(ptime)
            stracker_shm.set('command_from_http', 'session ptime %d' % ptime, server=server)
        if qtime != "":
            qtime = int(qtime)
            stracker_shm.set('command_from_http', 'session qtime %d' % qtime, server=server)
        if rlaps != "":
            rlaps = int(rlaps)
            stracker_shm.set('command_from_http', 'session rlaps %d' % rlaps, server=server)
        if restart:
            stracker_shm.set('command_from_http', 'servercmd /restart_session', server=server)
        if skip:
            stracker_shm.set('command_from_http', 'servercmd /next_session', server=server)
        self.redirect('livemap', server=server)

class LoggerHandler(logging.Handler):
    def __init__(self):
        logging.Handler.__init__(self)

    def emit(self, record):
        if config.config.HTTP_CONFIG.log_requests:
            if record.levelno < logging.DEBUG:
                log_f = acdump
            elif record.levelno < logging.INFO:
                log_f = acdebug
            elif record.levelno < logging.WARNING:
                log_f = acinfo
            elif record.levelno < logging.ERROR:
                log_f = acwarning
            else:
                log_f = acerror
        else:
            if record.levelno < logging.WARNING:
                log_f = acdump
            elif record.levelno < logging.ERROR:
                log_f = acwarning
            else:
                log_f = acerror
        msg = record.getMessage()
        try:
            url = cherrypy.request.request_line.split(" ")[1]
        except:
            url = "<unknown>"
        log_f("While processing url: %s\n%s", url, msg)

def start(database, listen_addr, listen_port, refBanlist, udp_plugin_):
    global db, banlist, udp_plugin, started
    db = database
    http_server_base.db = database

    banlist = refBanlist
    udp_plugin = udp_plugin_
    authcache = acauth.AuthCache(db)

    app = StrackerPublic()
    cherrypy.tree.mount(app, config=app.cp_config)
    if config.config.HTTP_CONFIG.admin_username != "" and config.config.HTTP_CONFIG.admin_password != "":
        admin = StrackerAdmin(config.config.HTTP_CONFIG.admin_username, config.config.HTTP_CONFIG.admin_password)
        cherrypy.tree.mount(admin, script_name="/admin", config=admin.cp_config)

    cherrypy.server.unsubscribe()
    server = cherrypy._cpserver.Server()
    server.socket_host = listen_addr
    server.socket_port = listen_port
    server.thread_pool = max(10, config.config.HTTP_CONFIG.max_streaming_clients + 5)

    server.subscribe()
    cherrypy.config.update({
        'engine.autoreload.on': False,
        'tools.gzip.on' : True,
        'tools.gzip.compress_level' : 5,
        'tools.gzip.mime_types' : ['text/html', 'text/plain', 'text/javascript', 'text/css', 'application/javascript'],
        'tools.sessions.on' : True,
        'tools.sessions.timeout' : 5, # 5 minutes timeout (keep as small as possible to prevent attacks)
        #'tools.gzip.debug' : True,
        #'tools.caching.debug' : True,
    })
    cherrypy.log.screen = False
    cherrypy.log.access_log.addHandler(LoggerHandler())
    cherrypy.log.error_log.addHandler(LoggerHandler())

    if config.config.HTTP_CONFIG.ssl:
        if (config.config.HTTP_CONFIG.ssl_certificate != "" and config.config.HTTP_CONFIG.ssl_private_key != "" and
                os.access(config.config.HTTP_CONFIG.ssl_certificate, os.R_OK) and os.access(config.config.HTTP_CONFIG.ssl_private_key, os.R_OK)):
            server.ssl_module = "builtin"
            server.ssl_certificate = config.config.HTTP_CONFIG.ssl_certificate
            server.ssl_private_key = config.config.HTTP_CONFIG.ssl_private_key
        else:
            acwarning("HTTPS set to be enabled, but certificate or private key either not provided or not readable. Falling back to non-SSL.")

    cherrypy.engine.start()
    started = True
    acdebug("http server started")

stopNow = False
def stop():
    global stopNow, started
    stopNow = True
    if started:
        print("Stopping http server; please wait - this might take some time")
        cherrypy.engine.exit()
        started = False
