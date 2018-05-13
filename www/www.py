import os, os.path
import sys
import re
import glob
import functools
import random
import time
import traceback
from threading import Thread

import psycopg2

import cherrypy
from cherrypy import Tool
from cherrypy.lib import auth_digest
from bottle import SimpleTemplate

abspath = lambda x: os.path.abspath(x).replace('\\', '/')

static_base_dir = os.path.split(abspath(__file__))[0]

try:
    db = psycopg2.connect(user="wwwuser", password="schneemann", host="localhost", database="wwwdb")
    primkey = "SERIAL PRIMARY KEY"
    print("Using postgres DB.")
except:
    print("no database connection.")
    db = None

def click_count():
    name = cherrypy.request.script_name + cherrypy.request.path_info
    status = cherrypy.response.status.split(" ")[0]
    if status != "200":
        print("click_count: ignoring request %s (status != 200, %s)" % (name, status))
        return
    print("click_count: request: %s"%name)
    if db is None: return
    try:
        c = db.cursor()
        c.execute("BEGIN")
        c.execute("""
CREATE TABLE IF NOT EXISTS
Clicks(
    Id %(primkey)s,
    Name TEXT,
    NumClicks INTEGER,
    UNIQUE(Name)
)""" % globals())
        c.execute("""
INSERT INTO Clicks(Name,NumClicks)
    SELECT %s,0
    WHERE NOT EXISTS (SELECT 1 FROM Clicks WHERE Name=%s)
""", (name,name))
        c.execute("UPDATE Clicks SET NumClicks=NumClicks+1 WHERE Name=%s", (name,))
        c.execute("COMMIT")
    except:
        c.execute("ROLLBACK")

cherrypy.tools.click_count = Tool('on_end_request', click_count)

class WwwServer(Thread):
    cp_config = {
        '/images' : {
            'tools.expires.on'    : True,
            'tools.expires.secs'  : 3600*24*7,
            'tools.staticdir.on' : True,
            'tools.staticdir.dir' : abspath(os.path.join(static_base_dir, "images")),
        },
        '/bootstrap' : {
            'tools.expires.on'    : True,
            'tools.expires.secs'  : 3600*24*7,
            'tools.staticdir.on' : True,
            'tools.staticdir.dir' : abspath(os.path.join(static_base_dir, "bootstrap")),
        },
        '/downloads' : {
            'tools.expires.on'    : True,
            'tools.expires.secs'  : 3600*24*7,
            'tools.staticdir.on' : True,
            'tools.staticdir.dir' : abspath(os.path.join(static_base_dir, "downloads")),
#            'tools.click_count.on' : True,
        },
        '/git' : {
            'tools.expires.on'    : True,
            'tools.expires.secs'  : 3600*24*7,
            'tools.staticdir.on' : True,
            'tools.staticdir.dir' : abspath(os.path.join(static_base_dir, "git")),
#            'tools.click_count.on' : True,
        },
    }
    def __init__(self, managed_dir = static_base_dir):
        Thread.__init__(self)
        self.daemon = True
        self.managed_dir = managed_dir
        self.pages = []
        self.lastFileContents = None
        self._update_contents()
        self._templ = SimpleTemplate(open(static_base_dir + "/templ.html").read())
        self.start()

    def _cmp_pages(self, np):
        if len(np) != len(self.pages):
            return False
        for i in range(len(np)):
            if len(np[i])!=len(self.pages[i]):
                return False
            for k in np[i].keys():
                if not k in self.pages[i]:
                    return False
                if self.pages[i][k] != np[i][k]:
                    return False
        return True

    def run(self):
        lastCompleteUpdate = time.time()
        while 1:
            time.sleep(interval)
            t = time.time()
            if t - lastCompleteUpdate > 60*60*24: # regenerate the pages at least once a day
                lastCompleteUpdate = t
                self.lastFileContents = None
            self._update_contents()

    def _update_contents(self):
        pages = []
        files = sorted(glob.glob(self.managed_dir + "/*.htm"))
        fileContents = [open(f).read() for f in (files + [static_base_dir + "/templ.html"])]
        if fileContents == self.lastFileContents:
            pass
        for f in files:
            p = self._parse(f)
            if not p is None:
                pages.append(p)
        pages.sort(key=lambda x: (x['index'], x['nav']))
        if not self._cmp_pages(pages):
            self.pages = pages
            for p in self.pages:
                f = functools.partial(self._genpage, page=p)
                setattr(self, p['link'], f)
                getattr(self, p['link']).exposed = True

    def _parse(self, f):
        link = os.path.splitext(os.path.basename(f))[0]
        l = open(f).readline()
        M = re.match(r'<!--\s*title="([^"]*)"\s*nav="([^"]*)"\s*index=([0-9]+)\s*sections=(.*)\s*-->', l.strip())
        try:
            if not M is None:
                title = M.group(1)
                nav = M.group(2)
                index = int(M.group(3))
                raw_sections = M.group(4)
                if raw_sections.strip() == "auto":
                    html = open(f).read()
                    pattern = r'<h([0-9])>(.*)</h\1>'
                    chapters = []
                    while 1:
                        M = re.search(pattern, html)
                        if M is None:
                            break
                        level = int(M.group(1))
                        name = M.group(2)
                        counter = len(chapters)
                        ref = "auto_chapter_%(counter)d" % locals()
                        chapters.append( (ref, name, level) )
                        html = (html[:M.start(0)]
+ ('<h%(level)d id="%(ref)s">%(name)s</h%(level)d>' % locals())
+ html[M.end(0):])
                else:
                    html = open(f).read()
                    sections = raw_sections.split(",")
                    chapters = []
                    try:
                        for sp in sections:
                            ref,desc = sp.split("+")
                            desc = desc.strip()
                            desc = desc[1:-1]
                            chapters.append( (ref, desc, 1) )
                    except:
                        pass
                res = dict(title=title,nav=nav,index=index,link=link,chapters=chapters,template=SimpleTemplate(html))
                return res
        except:
            print(traceback.format_exc())
            pass

    def _genpage(self, page, **kw):
        return self._templ.render(server=self, src=page['link'], kw=kw)

    def _redirect(self, name, **kw):
        s = "?"
        new_url = name
        for p in kw:
            v = kw[p]
            if not v is None:
                new_url += s + p + "=" + str(kw[p])
                s = "&"
        raise cherrypy.HTTPRedirect(new_url)

    @cherrypy.expose
    def default(self):
        self._redirect(self.pages[0]['link'])

    def link_from_file(self, file):
        ap = abspath(file)
        if ap.startswith(self.managed_dir):
            ap = ap[len(self.managed_dir):]
        return ap

    def get_num_downloads(self, name):
        if db is None:
            return 0
        try:
                c = db.cursor()
                c.execute("SELECT NumClicks,Name FROM Clicks WHERE Name=%s", (name,))
                a = c.fetchone()
                if not a is None:
                    return a[0]
                return 0
        except:
            print(traceback.format_exc())
            return 0

class StrackerAdmin(WwwServer):
    def __init__(self, username, password):
        self.cp_config = {
            '/' :  {
                'tools.auth_digest.on': True,
                'tools.auth_digest.realm': 'stracker admin area',
                'tools.auth_digest.get_ha1': auth_digest.get_ha1_dict_plain(
                    {username : password}
                ),
                'tools.auth_digest.key': random.getrandbits(64),
            }
        }
        WwwServer.__init__(self, static_base_dir + "/admin")

def main():
    app = WwwServer()
    cherrypy.tree.mount(app, config=app.cp_config)
    admin_credits = [l.strip() for l in open("credits.txt").readlines()]
    admin = StrackerAdmin(admin_credits[0], admin_credits[1])
    cherrypy.tree.mount(admin, script_name="/admin", config=admin.cp_config)
    cherrypy.server.unsubscribe()
    server = cherrypy._cpserver.Server()
    server.socket_host = "0.0.0.0"
    server.socket_port = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
    server.subscribe()
    cherrypy.config.update({
        'engine.autoreload.on': False,
        'tools.gzip.on' : True,
        'tools.gzip.compress_level' : 5,
        'tools.gzip.mime_types' : ['text/html', 'text/plain', 'text/javascript', 'text/css', 'application/javascript'],
        'tools.click_count.on' : True,
    })
    cherrypy.engine.start()
    while 1:
        try:
            time.sleep(1)
        except KeyboardInterrupt:
            print("Keyboard Interrupt")
            cherrypy.engine.exit()
            break

if __name__ == "__main__":
    interval = int(sys.argv[2]) if len(sys.argv) > 2 else 60
    main()
