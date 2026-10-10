"""SPICE service message types on top of core/wsl/transport.py -- one per
SpiceSessionSignals signal (helper -> app) and per worker input method
(app -> helper), so RemoteSpiceWorker is a mechanical mirror of
SpiceSessionWorker. Standard library only: imported inside the WSL distro.

Errors use the transport's own MSG_ERROR (utf-8 text); STOP is the
transport's MSG_STOP.
"""

import struct

from it_toolbox.core.wsl.transport import MSG_SERVICE_BASE

# helper -> app
FRAME = MSG_SERVICE_BASE + 0  # FRAME_HEADER + BGRX pixels for the dirty band
CONNECTED = MSG_SERVICE_BASE + 1
AGENT_CONNECTED = MSG_SERVICE_BASE + 2
DISCONNECTED = MSG_SERVICE_BASE + 3

# app -> helper
MOUSE_MOVE = MSG_SERVICE_BASE + 16  # !ii x, y
MOUSE_BUTTON = MSG_SERVICE_BASE + 17  # !? down, then utf-8 button name
MOUSE_WHEEL = MSG_SERVICE_BASE + 18  # !i steps
KEY_SCANCODE = MSG_SERVICE_BASE + 19  # !I?? code, extended, down
RESIZE = MSG_SERVICE_BASE + 20  # !II width, height
CLIPBOARD_TEXT = MSG_SERVICE_BASE + 21  # utf-8 host clipboard text; empty = no text

# band_top, band_height, canvas_width, canvas_height, stride
FRAME_HEADER = struct.Struct("!IIIII")
POINT = struct.Struct("!ii")
BUTTON = struct.Struct("!?")
WHEEL = struct.Struct("!i")
KEY = struct.Struct("!I??")
SIZE = struct.Struct("!II")
