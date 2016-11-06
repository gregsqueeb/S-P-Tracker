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

# original code from github: https://github.com/IronManMark20/hooked/blob/master/hooked.py

# extended to control whether to listen to mouse or not

import ctypes
from ctypes import wintypes
from collections import namedtuple
import functools
import os
import atexit
import win32gui
import struct
import traceback
from threading import Thread
from ctypes import windll, CFUNCTYPE, POINTER, c_int, c_void_p, byref, Structure, WinError

if __name__ != "__main__":
    from .helpers import *
    PRINT=acinfo
else:
    def myassert(x, *args): assert(x)
    PRINT=print

KeyEvents=namedtuple("KeyEvents",(['event_type', 'key_code',
                                             'scan_code', 'alt_pressed',
                                             'time']))
Callback=namedtuple("Callback", ('hotkey_list', 'callback', 'hotkey_id', 'callID'))

class _hook:
    """Main class to create and track hotkeys. Use hook.Hotkey to make a new hotkey"""
    def __init__(self, windowHandles=None):
        self.handler = None
        self.currentID = 0
        self.callbacks=[]
        self.raw_callbacks=[]
        self.mouseHandlers=[]
        self.current_keys={}
        self.modifiers = set(["Shift","Ctrl","Alt","LShift","RShift","LCtrl","RCtrl","LAlt","RAlt",])
        # virtual key codes defined by microsoft (https://msdn.microsoft.com/en-us/library/windows/desktop/dd375731%28v=vs.85%29.aspx)
        self.vkeycodes={
            0x01:"MouseLeft",
            0x02:"MouseRight",
            0x03:"Cancel",
            0x04:"MouseMiddle",
            0x05:"MouseX1",
            0x06:"MouseX2",
            0x08:"Backspace",
            0x09:"Tab",
            0x0c:"Clear",
            0x0d:"Enter",
            0x10:"Shift",
            0x11:"Ctrl",
            0x12:"Alt",
            0x13:"Pause",
            0x14:"Capslock",
            0x15:"IME Kana mode",
            0x17:"IME Junja mode",
            0x18:"IME final mode",
            0x19:"IME Hanja mode",
            0x1b:"Esc",
            0x1c:"IME convert",
            0x1d:"IME nonconvert",
            0x1e:"IME accept",
            0x1f:"IME mode change request",
            0x20:"Space",
            0x21:"KeyPgUp",
            0x22:"KeyPgDn",
            0x23:"KeyEnd",
            0x24:"KeyHome",
            0x25:"KeyLeft",
            0x26:"KeyUp",
            0x27:"KeyRight",
            0x28:"KeyDown",
            0x29:"KeySelect",
            0x2a:"KeyPrint",
            0x2b:"KeyExecute",
            0x2c:"KeyPrintScreen",
            0x2d:"KeyIns",
            0x2e:"KeyDel",
            0x2f:"KeyHelp",
            0x5b:"KeyLWin",
            0x5c:"KeyRWin",
            0x5d:"KeyApps",
            0x5f:"KeySleep",
            0x6a:"KeyNumPadMul",
            0x6b:"KeyNumPadAdd",
            0x6c:"Seperator",
            0x6d:"KeyNumPadSub",
            0x6e:"KeyNumPadDec",
            0x6f:"KeyNumPadDiv",
            0x90:"Numlock",
            0x91:"Scrolllock",
            0xa0:"LShift",
            0xa1:"RShift",
            0xa2:"LCtrl",
            0xa3:"RCtrl",
            0xa4:"LAlt",
            0xa5:"RAlt",
            0xa6:"BrowserBack",
            0xa7:"BrowserForwrd",
            0xa8:"BrowserRefresh",
            0xa9:"BrowserStop",
            0xaa:"BrowserSearch",
            0xab:"BrowserFavorites",
            0xac:"BrowserStart",
            0xad:"VolumeMute",
            0xae:"VolumeDown",
            0xaf:"VolumeUp",
            0xb0:"MediaNextTrack",
            0xb1:"MediaPrevTrack",
            0xb2:"MediaStop",
            0xb3:"MediaPause",
            0xb4:"MailStart",
            0xb5:"MediaSelect",
            0xb6:"StartApp1",
            0xb7:"StartApp2",
            0xba:";",
            0xbb:"+",
            0xbc:",",
            0xbd:"-",
            0xbe:".",
            0xbf:"/",
            0xc0:"~",
            0xdb:"[",
            0xdc:"\\",
            0xdd:"]",
            0xde:"'",
            0xdf:"Misc",
            0xe2:"<",
            0xe5:"IME process",
            0xf6:"KeyAttn",
            0xf7:"KeyCrSel",
            0xf8:"KeyExSel",
            0xf9:"KeyEraseEOF",
            0xfa:"KeyPlay",
            0xfb:"KeyZoom",
            0xfd:"KeyPA1",
            0xfe:"KeyClear",
        }
        # numbers
        for i in range(0x30,0x3a):
            self.vkeycodes[i] = chr(ord("0")+(i-0x30))
        # characters
        for i in range(0x41,0x5b):
            self.vkeycodes[i] = chr(ord("A")+(i-0x41))
        # numpad numbers
        for i in range(0x60,0x6a):
            self.vkeycodes[i] = "KeyNumPad"+str(i-0x60)
        # function keys
        for i in range(0x70,0x88):
            self.vkeycodes[i] = "F" + str(i-0x6f)
        self.vkeycodes_rev = {}
        for i in self.vkeycodes.keys():
            k = self.vkeycodes[i]
            myassert(not k in self.vkeycodes_rev, k)
            self.vkeycodes_rev[k] = i
        # mapping for modifiers
        self.modifier_map = {
            "LAlt"   : "Alt",
            "RAlt"   : "Alt",
            "LCtrl"  : "Ctrl",
            "RCtrl"  : "Ctrl",
            "LShift" : "Shift",
            "RShift" : "Shift",
        }
        if not windowHandles is None:
            windowHandles = set(windowHandles)
        self.windowHandles = windowHandles

    def cleanup_ck(self, maxT):
        for k in list(self.current_keys):
            t = self.current_keys[k]
            if maxT - t > 60000: # timeout after 1 minute, we assume we missed the key up event somehow
                del self.current_keys[k]

    def print_event(self,e):
        """This parses through the keyboard events. You shouldn't ever need this. Actually, don't mess with this; you may break your computer."""
        if type(e) == KeyEvents:
            scancode=e.scan_code
            keycode=e.key_code
            key = self.vkeycodes.get(keycode, None)
            if key is None:
                PRINT("Unknown key keycode=%s scancode=%s",keycode,scancode)
                return
        if not key in self.modifiers:
            for cb in self.raw_callbacks:
                cb.callback(e.event_type, key)
        #append to current_keys when down
        if (e.event_type)==self.KEY_DOWN:
            self.current_keys[key] = e.time
            self.cleanup_ck(e.time)
            ck = set(map(lambda x: self.modifier_map.get(x, x), self.current_keys.keys()))
            #PRINT(self.current_keys)
            for cb in self.callbacks:
                hotkey_list = cb.hotkey_list
                func = cb.callback
                if (hotkey_list == ck):
                    func()
                if len(hotkey_list) == 0 and not key in self.modifiers:
                    func()
        #remove key when releaseD
        elif (e.event_type)==self.KEY_UP:
            try:
                del self.current_keys[key]
            except KeyError:
                pass
            #PRINT(self.current_keys)
        else:
            PRINT("unknown event: %s", str(e), self.KEY_DOWN, self.KEY_UP)

    def get_current_keys(self):
        modifiers = []
        normals = []
        for c in self.current_keys.keys():
            c = self.modifier_map.get(c, c)
            if c in self.modifiers:
                modifiers.append(c)
            else:
                normals.append(c)
        return sorted(modifiers) + sorted(normals)

    def get_current_mods(self):
        modifiers = []
        for c in self.current_keys.keys():
            c = self.modifier_map.get(c, c)
            if c in self.modifiers:
                modifiers.append(c)
        return sorted(modifiers)

    def Hotkey(self,hotkey_list,callback,args=(), callID=None):
        """Adds a new hotkey. Definition: Hotkey(list=[],fhot=None) where list is the list of
        keys and fhot is the callback function"""
        hotkey_id = self.currentID
        self.currentID+=1
        self.callbacks.append( Callback(set(hotkey_list), functools.partial(callback, *args), hotkey_id, callID ) )
        PRINT("Hotkey %s registered", str(set(hotkey_list)))
        self.handler = self.print_event
        return hotkey_id

    def RemHotKey(self,hkey):
        """Remove a hotkey. Specify the id, the key list, or the function to remove the hotkey."""
        if type(hkey)==type(0):
            attr = lambda x: x.hotkey_id
        elif type(hkey) in [type([]), type(set())]:
            attr = lambda x: x.hotkey_list
            hkey = set(hkey)
        else:
            attr = lambda x: x.callback.func
        for i in range(len(self.callbacks)-1,-1,-1):
            if attr(self.callbacks[i]) == hkey:
                self.callbacks = self.callbacks[:i] + self.callbacks[(i+1):]
        if len(self.callbacks) + len(self.raw_callbacks) == 0:
            self.handler = None

    def RawKeyboardHandler(self, callback, callID = None):
        self.raw_callbacks.append( Callback(None, callback, None, callID))
        self.handler = self.print_event

    def RemoveRawKeyboardHandler(callID = None):
        self.raw_callbacks = list(filter(lambda x: x.callID != callID, self.raw_callbacks))
        if len(self.callbacks) + len(self.raw_callbacks) == 0:
            self.handler = None

    def MouseHandler(self, callback, callID = None):
        """Add a callback function to be called for mouse events. Callbacks have the
           signature (e,x,y,mouseData), where e is the mouse event as string,
           x/y is the mouse position and mouseData is the delta of a wheel event
        """
        self.mouseHandlers.append( Callback(None, callback, None, callID) )

    def ResetMouseHandlers(self, callID = None):
        """Remove all callback functions for mouse events."""
        self.mouseHandlers = list(filter(lambda x: x.callID != callID, self.mouseHandlers))

    def clear(self, callID=None):
        self.callbacks = list(filter(lambda x: x.callID != callID, self.callbacks))
        if len(self.callbacks) + len(self.raw_callbacks) == 0:
            self.handler = None

    def listener(self):
        self.KEY_DOWN = 0
        self.KEY_UP = 1
        """The listener listens to events and adds them to handlers"""
        event_types = {0x100: self.KEY_DOWN, #WM_KeyDown for normal keys
                   0x101: self.KEY_UP, #WM_KeyUp for normal keys
                   0x104: self.KEY_DOWN, # WM_SYSKEYDOWN, used for Alt key.
                   0x105: self.KEY_UP, # WM_SYSKEYUP, used for Alt key.
                  }
        def low_level_handler(nCode, wParam, lParam):
            """
            Processes a low level Windows keyboard event.
            """
            if( nCode >= 0 and
                (self.windowHandles is None or win32gui.GetForegroundWindow() in self.windowHandles or wParam in [0x101,0x105]) and
                not self.handler is None ):

                event = KeyEvents(event_types[wParam], lParam[0], lParam[1],
                              lParam[2] == 32, lParam[3])
                self.handler(event)

            return windll.user32.CallNextHookEx(0, nCode, wParam, lParam)

        CMPFUNC = CFUNCTYPE(c_int, c_int, c_int, POINTER(c_void_p))

        #Make a C pointer
        self.pointer = CMPFUNC(low_level_handler)
        windll.kernel32.GetModuleHandleW.restype = wintypes.HMODULE
        windll.kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]

        hook_id = windll.user32.SetWindowsHookExA(0x0D, self.pointer, 0,0)
        if hook_id == 0: raise WinError()
        atexit.register(windll.user32.UnhookWindowsHookEx, hook_id)

        self.MOUSE_WHEEL = 0
        self.LEFT_BTN_DOWN = 1
        self.LEFT_BTN_UP = 2
        self.RIGHT_BTN_DOWN = 3
        self.RIGHT_BTN_UP = 4

        mouse_types = {0x20a: self.MOUSE_WHEEL,
                       #0x202: self.LEFT_BTN_DOWN,
                       #0x203: self.LEFT_BTN_UP,
                       #0x204: self.RIGHT_BTN_DOWN,
                       #0x205: self.RIGHT_BTN_UP
                       }

        def low_level_handler_mouse(nCode, wParam, lParam): #nCode, wParam, lParam):
            """
            Processes a low level Windows mouse event.
            """
            try:
                #acdebug("ll_mouse: %d %x", nCode, wParam)
                if (nCode == 0 and # HC_ACTION
                  wParam in mouse_types):
                    x = lParam[0]
                    y = lParam[1]
                    e = mouse_types[wParam]
                    if e == self.MOUSE_WHEEL:
                        mouseData, = struct.unpack('h', struct.pack('I', lParam[2])[2:4])
                    else:
                        mouseData = 0
                    for h in self.mouseHandlers:
                        h.callback(e,x,y,mouseData)
            except:
                acdebug("Exception: %s", traceback.format_exc())
            return windll.user32.CallNextHookEx(0, nCode, wParam, lParam)

        # same for the mouse
        self.pointer_mouse = CMPFUNC(low_level_handler_mouse)
        hook_id_mouse = windll.user32.SetWindowsHookExA(0x0E, self.pointer_mouse, 0,0)
        if hook_id_mouse == 0: raise WinError()
        atexit.register(windll.user32.UnhookWindowsHookEx, hook_id_mouse)

    def pumpMessages(self):
        while True:
            try:
                msg = windll.user32.GetMessageW(None, 0, 0,0)
                windll.user32.TranslateMessage(byref(msg))
                windll.user32.DispatchMessageW(byref(msg))
            except:
                acdebug("Exception in message pump: %s", traceback.format_exc())

    def listen(self):
        """Start listening for hooks"""
        PRINT("hooked: Setting up hooks.")
        self.listener()
        PRINT("hooked: Starting event loop.")
        self.pumpMessages()

_hookInstance = None
_msgPumpThread = None
def hook(*args):
    """Factory function for hook objects related to Assetto Corsa / Ptracker"""
    global _hookInstance, _msgPumpThread
    if _hookInstance is None:

        from ptracker_lib import acsim
        import win32gui, win32process

        def iterate_windows(pid):
            def callback(hwnd, hwnds):
                _, found_pid = win32process.GetWindowThreadProcessId(hwnd)
                if found_pid == pid:
                    hwnds.append(hwnd)
                return True
            tids = set()
            hwnds = []
            win32gui.EnumWindows(callback, hwnds)
            return hwnds

        pid = acsim.ac.getACPid()
        hwnds = iterate_windows(pid)
        _hookInstance = _hook(hwnds)
        if acsim.ac.getACPid() != os.getpid():
            # server process -> we need to setup a message pumping thing
            if _msgPumpThread is None:
                _msgPumpThread = Thread(target=_hookInstance.listen, daemon=True)
                _msgPumpThread.start()
        else:
            _hookInstance.listener()
    return _hookInstance

if __name__ == "__main__":
    hk = _hook()
    hk.Hotkey([], lambda *args: print("Hotkey Args:",args,"; CurrentKeys:", hk.get_current_keys()))
    hk.RawKeyboardHandler(lambda *args: print("Raw Args:",args))
    Thread(target=hk.listen).start()
    while 1:
        pass