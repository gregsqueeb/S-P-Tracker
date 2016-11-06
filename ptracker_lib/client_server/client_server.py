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
import traceback
import functools

from threading import RLock

from ptracker_lib.client_server.client_server_impl import SharedMemoryIF, PendingResult, ServerFunction, CSTimeoutError

PRINT = print

__all__ = ['Server', 'Client', 'IF_SHM', 'IF_TCP']

IF_SHM = 0
IF_TCP = 1

REQ_ADD_FUNCTION = 0
REQ_REMOTE_CALL = 1
REQ_REMOTE_ANS = 2

ANS_CALL_OK = 0
ANS_CALL_EXC = 1



class ClientServer:
    ARG_PICKLE = SharedMemoryIF.ARG_PICKLE
    ARG_STRING = SharedMemoryIF.ARG_STRING
    ARG_BYTES = SharedMemoryIF.ARG_BYTES
    ARG_CALLBACK = SharedMemoryIF.ARG_CALLBACK

    MODE_SERVER = SharedMemoryIF.MODE_SERVER
    MODE_CLIENT = SharedMemoryIF.MODE_CLIENT

    TimeoutError = CSTimeoutError

    def __init__(self, mode, interface, *ifargs):
        # interface must be either IF_SHM or IF_TCP
        #   - if IF_SHM, the remaining ifargs are:
        #        - the name of the shared memory structure
        #        - maximum request size in bytes
        #        - maximum answer size in bytes
        self.lock = RLock()
        if interface == IF_SHM:
            self._interface = SharedMemoryIF(mode, self, mode == self.MODE_SERVER, *ifargs)
        elif interface == IF_TCP:
            from .tcp_impl import TcpIF
            self._interface = TcpIF(mode, self, mode == self.MODE_SERVER, *ifargs)
        else:
            raise NotImplementedError

        self._local_functions_by_name = {}
        self._local_functions_by_id = {}
        self._local_call_results = {}
        self._local_lastFuncId = 0

        class ServedFunctions:
            def __init__(self):
                pass

        self.remote = ServedFunctions()
        self._remote_functions = {}
        self._remote_functions_by_id = {}
        self._remote_call_results = {}
        self._remote_call_requests = []
        self._next_call_id = 0

    def addFunction(self, name, args, ret, f):
        with self.lock:
            id = self._local_lastFuncId
            self._local_lastFuncId += 1
            desc = ServerFunction(args, ret, id, f)
            self._local_functions_by_name[name] = desc
            self._local_functions_by_id[id] = desc
        self._notifyAboutAddedFunction(self._interface, name)
        return desc

    def get_pending_results(self, call_id):
        with self.lock:
            return self._local_call_results[call_id]

    def _handle_callback_calls_client(self, arg_descs, args):
        with self.lock:
            res = []
            if not type(arg_descs) == type(()):
                return args
            for i,d in enumerate(arg_descs):
                if type(d) == self.ARG_CALLBACK:
                    f = args[i]
                    # we must add a local function here
                    name = "cs_callback_%d" % self._local_lastFuncId
                    fd = self.addFunction(name, d.to_tuple(), None, f)
                    res.append(ServerFunction(fd.args, fd.ret, fd.id, None))
                    #PRINT("added remote function for callback %s!" % name)
                    #PRINT("".join(traceback.format_stack()))
                else:
                    res.append(args[i])
            return tuple(res)

    def _callFunction(self, funcName, *args, cs_callback = None):
        with self.lock:
            #PRINT("cf",funcName,args,cs_callback)
            func_desc = self._remote_functions[funcName]
            IF = self._interface
            args = self._handle_callback_calls_client(func_desc.args, args)
            IF.write_int(REQ_REMOTE_CALL)
            call_id = self._next_call_id
            self._next_call_id = (self._next_call_id+1)%(65536)
            IF.write_int(call_id)
            IF.write_int(func_desc.id)
            IF.pack(func_desc.args, args)
            IF.inc()
            r = PendingResult(cs_callback, call_id, func_desc.ret, self._interface, func_desc.id)
            self._remote_call_results[call_id] = r
            return r

    def _handle_callback_calls_server(self, args):
        with self.lock:
            res = []
            for a in args:
                if type(a) == ServerFunction:
                    id = a.id
                    name = self._remote_functions_by_id[id]
                    f = getattr(self.remote, name)
                    res.append(f)
                else:
                    res.append(a)
            return tuple(res)

    def _logRemoteCallRequest(self, IF):
        with self.lock:
            call_id = IF.read_int()
            func_id = IF.read_int()
            func_desc = self._local_functions_by_id[func_id]
            func_args = IF.unpack(func_desc.args)
            func_args = self._handle_callback_calls_server(func_args)
            self._remote_call_requests.append( (call_id, func_desc, func_args) )

    def performRemoteCallRequests(self):
        IF = self._interface
        for call_id, func_desc, func_args in self._remote_call_requests:
            try:
                func_args = map(lambda x,self=self: self.get_pending_results(x.callid) if isinstance(x, IF.ARG_REFERENCE) else x, func_args)
                r = func_desc.func(*func_args)
                with self.lock:
                    self._local_call_results[call_id] = r
                    IF.write_int(REQ_REMOTE_ANS)
                    IF.write_int(call_id)
                    IF.write_int(ANS_CALL_OK)
                    IF.pack(func_desc.ret, r)
                    IF.inc()
            except:
                with self.lock:
                    IF.write_int(REQ_REMOTE_ANS)
                    IF.write_int(call_id)
                    IF.write_int(ANS_CALL_EXC)
                    estr = traceback.format_exc()
                    PRINT("exception!", estr)
                    IF.write_str(estr)
                    IF.inc()
        with self.lock:
            self._remote_call_requests = []

    def _performRemoteAnsRequest(self, IF):
        with self.lock:
            call_id = IF.read_int()
            resOK = IF.read_int()
            if resOK == ANS_CALL_OK:
                pr = self._remote_call_results[call_id]
                #PRINT("Unpacking remote answer of function %s" % self._remote_functions_by_id[pr.func_id])
                ret = IF.unpack(pr.func_ret)
                if not pr.callback is None:
                    pr.callback(ret)
                pr.retVal = ret
                del self._remote_call_results[call_id]
            elif resOK == ANS_CALL_EXC:
                self.exc.append(IF.read_str())
            else:
                raise NotImplementedError

    def _performAddFunctionRequest(self, IF):
        with self.lock:
            t = pickle.loads(IF.read_bytes())
            (id,name,args,ret) = t
            sf = ServerFunction(args,ret,id,None)
            self._remote_functions[name] = sf
            self._remote_functions_by_id[id] = name
            setattr(self.remote, name, makeAcCompatible(functools.partial(self._callFunction, name)))

    def _notifyAboutAddedFunction(self, IF, name):
        with self.lock:
            f_desc = self._local_functions_by_name[name]
            a = (f_desc.id,name,f_desc.args,f_desc.ret)
            IF.write_int(REQ_ADD_FUNCTION)
            IF.write_bytes(pickle.dumps(a))
            IF.inc()

    def _processRequest(self):
        #with self.lock:
            IF = self._interface
            r = IF.read_int()
            if r == REQ_ADD_FUNCTION:
                self._performAddFunctionRequest(IF)
            elif r == REQ_REMOTE_CALL:
                self._logRemoteCallRequest(IF)
            elif r == REQ_REMOTE_ANS:
                self._performRemoteAnsRequest(IF)
            else:
                raise NotImplementedError

    def wait(self, timeout = None, autoCallFuncs = True):
        IF = self._interface
        self.exc = []
        cntRequests = IF.wait(self.lock, timeout)
        for reqNum in range(cntRequests):
            self._processRequest()
        if autoCallFuncs:
            self.performRemoteCallRequests()
        if len(self.exc) > 0:
            PRINT("Exceptions occured. reraise.")
            raise RuntimeError("Excption caught:\n" + ("\n\nException caught:\n".join(self.exc)))

    def commit(self):
        with self.lock:
            IF = self._interface
            IF.commit()

    def serve_forever(self):
        self.stopped = False
        while not self.stopped:
            self.wait()
            self.commit()

    def stop_serving(self):
        self.stopped = True

    def statistics(self):
        return self._interface.statistics()

Server = functools.partial(ClientServer, ClientServer.MODE_SERVER)
Client = functools.partial(ClientServer, ClientServer.MODE_CLIENT)

callback_counter = 0
def makeAcCompatible(real_callback):

    def new_f(*args, **kw):
        return real_callback(*args, **kw)

    global callback_counter
    name = "_callback_%d_" % callback_counter
    globals()[name] = new_f
    globals()[name].__name__ = name
    callback_counter += 1
    return new_f

if __name__ == "__main__":

    def server_main(s_create):

        def test_perform_callback(f):
            Thread(target=lambda: [time.sleep(0.4), print("Calling callback"), f(42, "server thread's callback")]).start()

        s = s_create[0](*s_create[1])
        s.addFunction('inc', s.ARG_PICKLE, s.ARG_PICKLE, lambda x: x+1)
        s.addFunction('add', s.ARG_PICKLE, s.ARG_PICKLE, lambda x,y: x+y)
        s.addFunction('add2', 'ii', 'i', lambda x,y: x+y)
        s.addFunction('add3', ('i','i'), 'i', lambda x,y: x+y)
        s.addFunction('printer', (s.ARG_STRING,), None, lambda x: print(x))
        s.addFunction('encode_utf8', (s.ARG_STRING,), s.ARG_BYTES, lambda x: x.encode('utf8'))
        s.addFunction('f_callback', (s.ARG_CALLBACK('i', s.ARG_STRING),), None, test_perform_callback)
        s.addFunction('quit', (), None, lambda: s.stop_serving())
        s.serve_forever()

    from threading import Thread
    import time

    def perform_test(s_create,c_create):
        class X:
            pass
        t = Thread(target=server_main, args=(s_create,), daemon=True)
        t.start()

        c = c_create[0](*c_create[1])
        c.commit()
        c.wait()
        r1 = c.remote.inc(0, cs_callback=lambda x: print("inc(0)=",x))
        r2 = c.remote.add(2, 4, cs_callback=lambda x: print("add(2,4)=",x))
        try:
            r1()
            raise AssertionError
        except RuntimeError:
            pass # we expect this exception
        a = c.remote.add2(2,4, cs_callback=lambda x: print("add2(2,4)=",x))
        c.remote.add3(a,4, cs_callback=lambda x: print("add3(add2(2,4),4=",x))
        c.remote.encode_utf8('Hello World', cs_callback=lambda x: print("encode_utf8(hello world)=",x))
        c.commit()
        c.wait()

        c.remote.inc("7", cs_callback=lambda x: print("inc('7')=",x))
        c.commit()
        try:
            c.wait()
            raise AssertionError
        except RuntimeError:
            print("Exception was expected, OK")
            pass # we expect this exception

        c.remote.inc(0,)
        c.remote.printer("Hello World")
        c.commit()
        c.wait()

        c.remote.f_callback(lambda x,y: print(x,y))
        c.commit()
        c.wait()

        time.sleep(1)
        c.commit()
        c.wait()
        print("r1=", r1(), "r2=", r2())

        c.remote.quit()
        c.commit()
        c.wait()

    perform_test((Server, (IF_SHM, "test-client-server", 1234, 15.)), (Client, (IF_SHM, "test-client-server", 1234, 15.)))

    import socket
    import errno
    def create_sock_pair(port=0):
        """Create socket pair.

        If socket.socketpair isn't available, we emulate it.
        """
        # See if socketpair() is available.
        have_socketpair = hasattr(socket, 'socketpair')
        if have_socketpair:
            client_sock, srv_sock = socket.socketpair()
            return client_sock, srv_sock

        # Create a non-blocking temporary server socket
        temp_srv_sock = socket.socket()
        temp_srv_sock.setblocking(False)
        temp_srv_sock.bind(('', port))
        port = temp_srv_sock.getsockname()[1]
        temp_srv_sock.listen(1)

        # Create non-blocking client socket
        client_sock = socket.socket()
        client_sock.setblocking(False)
        try:
            client_sock.connect(('localhost', port))
        except socket.error as err:
            # EWOULDBLOCK is not an error, as the socket is non-blocking
            if err.errno != errno.EWOULDBLOCK:
                raise

        # Use select to wait for connect() to succeed.
        import select
        timeout = 1
        readable = select.select([temp_srv_sock], [], [], timeout)[0]
        if temp_srv_sock not in readable:
            raise Exception('Client socket not connected in {} second(s)'.format(timeout))
        srv_sock, _ = temp_srv_sock.accept()

        return client_sock, srv_sock

    s1,s2 = create_sock_pair()
    perform_test((Server, (IF_TCP, s1)), (Client, (IF_TCP, s2)))
