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

from ptracker_lib.config import config

wstyle2frame = {
    config.WSTYLE_ROUND_FRAME: "apps\\python\\ptracker\\images\\rounded_frame\\frame.ini",
    config.WSTYLE_ROUND_NOFRAME: "apps\\python\\ptracker\\images\\rounded_noframe\\frame.ini",
    config.WSTYLE_RECT_FRAME : "apps\\python\\ptracker\\images\\rect_frame\\frame.ini",
    config.WSTYLE_RECT_NOFRAME: None
}

tstyle2frames = {
    config.TSTYLE_ORANGE_GREEN : ("apps\\python\\ptracker\\images\\table_row_green\\frame.ini","apps\\python\\ptracker\\images\\table_row_orange\\frame.ini"),
    config.TSTYLE_GRAY : ("apps\\python\\ptracker\\images\\table_row_darkgray\\frame.ini","apps\\python\\ptracker\\images\\table_row_lightgray\\frame.ini"),
    config.TSTYLE_GREEN : ("apps\\python\\ptracker\\images\\table_row_green\\frame.ini","apps\\python\\ptracker\\images\\table_row_lightgreen\\frame.ini"),
    config.TSTYLE_BLUE : ("apps\\python\\ptracker\\images\\table_row_darkblue\\frame.ini","apps\\python\\ptracker\\images\\table_row_lightblue\\frame.ini"),
    config.TSTYLE_RED : ("apps\\python\\ptracker\\images\\table_row_darkred\\frame.ini","apps\\python\\ptracker\\images\\table_row_lightred\\frame.ini"),
    config.TSTYLE_YELLOW : ("apps\\python\\ptracker\\images\\table_row_darkyellow\\frame.ini","apps\\python\\ptracker\\images\\table_row_lightyellow\\frame.ini"),
    config.TSTYLE_NONE : (None, None),
}

tabviewStyles = {
    False : "apps\\python\\ptracker\\images\\tab_disabled\\frame.ini",
    True : "apps\\python\\ptracker\images\\tab_enabled\\frame.ini",
    'content' : "apps\\python\\ptracker\images\\tab_content_frame\\frame.ini",
}
seperators = {
    'hor' : "apps\\python\\ptracker\\images\\sep_hor\\frame.ini",
    'vert': "apps\\python\\ptracker\\images\\sep_vert\\frame.ini"
}

pageIcons = {
    'first': ["apps\\python\\ptracker\\images\\page_first.png","apps\\python\\ptracker\\images\\page_first_disabled.png"],
    'prev' : ["apps\\python\\ptracker\\images\\page_prev.png","apps\\python\\ptracker\\images\\page_prev_disabled.png"],
    'me'   : ["apps\\python\\ptracker\\images\\page_me.png","apps\\python\\ptracker\\images\\page_me_disabled.png"],
    'next' : ["apps\\python\\ptracker\\images\\page_next.png","apps\\python\\ptracker\\images\\page_next_disabled.png"],
    'last' : ["apps\\python\\ptracker\\images\\page_last.png","apps\\python\\ptracker\\images\\page_last_disabled.png"],
}

paneIcons = {
    'opened' : "apps\\python\\ptracker\\images\\pane_opened.png",
    'closed' : "apps\\python\\ptracker\\images\\pane_closed.png"
}

transparentIcon = "apps\\python\\ptracker\\images\\transparent.png"
