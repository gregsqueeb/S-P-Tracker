import traceback
import urllib
from queue import Queue
from ptracker_lib.async_worker import Worker, threadCallDecorator
from ptracker_lib.helpers import *

urls = [
    "http://authminoratingcom.azurewebsites.net/auth/%s?GUID=%s",
    "http://plugin.minorating.com:805/minodata/auth/%s/?GUID=%s",
]

url = urls[0]
errors_in_sequence = 0

class MRQuery:
    def __init__(self, database, callback):
        self.worker = Worker(True)
        self.database = database
        self.guid_queue = Queue()
        self.callback = callback

    def query(self, guid):
        res = self.database.queryMR(__sync=True, guid=guidhasher(guid))()
        if not res is '' and not res is None:
            self.done(guid, None, res)
            return

        def query_from_mr(guid):
            global url, errors_in_sequence
            # try to query the minorating from minolin's server
            tree = [
                "ABC", ["C", "C", ["A", "A", "B"]],
                       ["N", "N", ["D", "D", "W"]]]
            t = tree
            while type(t) == list:
                while errors_in_sequence < 3:
                    try:
                        curl = url % (t[0], guid)
                        acdebug("Querying %s ...", curl)
                        ans = urllib.request.urlopen(curl, timeout=3.0)
                        ans = ans.read().decode(ans.headers.get_content_charset('utf-8')).strip()
                        acdebug("Result: %s", ans[:2])
                        if ans.startswith("OK"):
                            t = t[1]
                        elif ans.startswith("DE"):
                            t = t[2]
                        else:
                            raise RuntimeError("Unexpected answer")
                        errors_in_sequence = 0
                        break
                    except:
                        acdebug("Traceback in query_from_mr:%s", traceback.format_exc())
                        errors_in_sequence += 1
                        if errors_in_sequence == 3 and url == urls[0]:
                            acwarning("Using fallback minorating AUTH address.")
                            url = urls[1]
                            errors_in_sequence = 0
                        if errors_in_sequence >= 3:
                            break
                if errors_in_sequence >= 3:
                    errors_in_sequence = 2
                    t = ''
                    break
            res = t
            return res
        self.worker.apply_async(threadCallDecorator(query_from_mr), (guid,), {}, callback = lambda res, guid=guid: self.done(guid, res[0], res[1]))

    def done(self, guid, tb, res):
        if tb is None and not res is None and not res == '':
            self.database.queryMR(__sync=True, guid=guidhasher(guid), set_rating=res)
            self.callback(guid, res.lower())
        elif not tb is None:
            et,ev,etb = tb
            acwarning("Error found in MR query thread: %s", str(ev))
            acwarning("".join(traceback.format_exception(et, ev, etb)))
