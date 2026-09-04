"""Hand-written ctypes layer for libfreerdp3's display-control (disp)
virtual channel — DispClientContext plus DISPLAY_CONTROL_MONITOR_LAYOUT,
used to ask the server to resize the remote desktop to match the local
widget's size.

Hand-written for the same reason as cliprdr.py (see that module's
docstring for why scripts/generate_freerdp_bindings.py doesn't work on
Windows) — and an even better fit for it here: DispClientContext is just
two callback fields plus handle/custom, and DISPLAY_CONTROL_MONITOR_LAYOUT
is ten flat UINT32/INT32 fields with no embedded pointers, so there's none
of the array-lifetime care cliprdr.py's CLIPRDR_FORMAT_LIST needed.

Source: freerdp/client/disp.h and freerdp/channels/disp.h, from the same
real FreeRDP3 3.31.0 install (vcpkg, x64-windows) used for cliprdr.py.
"""

import ctypes

from it_toolbox.core.rdp._freerdp3_bindings import UINT32

UINT = UINT32
INT32 = ctypes.c_int32

DISPLAY_CONTROL_MONITOR_PRIMARY = 0x00000001

# freerdp/channels/disp.h — the server is entitled to reject a layout
# outside this range, so clamp rather than let a not-yet-laid-out or
# tiny widget send a nonsensical request.
DISPLAY_CONTROL_MIN_MONITOR_WIDTH = 200
DISPLAY_CONTROL_MAX_MONITOR_WIDTH = 8192
DISPLAY_CONTROL_MIN_MONITOR_HEIGHT = 200
DISPLAY_CONTROL_MAX_MONITOR_HEIGHT = 8192


class DISPLAY_CONTROL_MONITOR_LAYOUT(ctypes.Structure):
    _fields_ = [
        ("Flags", UINT32),
        ("Left", INT32),
        ("Top", INT32),
        ("Width", UINT32),
        ("Height", UINT32),
        ("PhysicalWidth", UINT32),
        ("PhysicalHeight", UINT32),
        ("Orientation", UINT32),
        ("DesktopScaleFactor", UINT32),
        ("DeviceScaleFactor", UINT32),
    ]


class DispClientContext(ctypes.Structure):
    pass


# freerdp/client/disp.h
_CapsFn = ctypes.CFUNCTYPE(UINT, ctypes.POINTER(DispClientContext), UINT32, UINT32, UINT32)
_SendMonitorLayoutFn = ctypes.CFUNCTYPE(
    UINT, ctypes.POINTER(DispClientContext), UINT32, ctypes.POINTER(DISPLAY_CONTROL_MONITOR_LAYOUT)
)

DispClientContext._fields_ = [
    ("handle", ctypes.c_void_p),
    ("custom", ctypes.c_void_p),
    ("DisplayControlCaps", _CapsFn),
    ("SendMonitorLayout", _SendMonitorLayoutFn),
]


class DisplayChannel:
    """Qt-free display-control logic, bound to a live DispClientContext*
    once the "disp" virtual channel connects (see freerdp_client.py's
    ChannelConnected subscription — same mechanism as cliprdr.py's
    ClipboardChannel). Single monitor only: this project has no
    multi-monitor story anywhere else, so NumMonitors is always 1.
    """

    def __init__(self) -> None:
        self._context: ctypes.POINTER(DispClientContext) | None = None
        # Kept alive for the channel's lifetime — same reasoning as every
        # other CFUNCTYPE keepalive in this project.
        self._caps_cb = _CapsFn(self._on_caps)

    def bind(self, context: ctypes.POINTER(DispClientContext)) -> None:
        """Called once, when the "disp" channel connects."""
        self._context = context
        context.contents.DisplayControlCaps = self._caps_cb

    def _on_caps(self, context, max_monitors, max_area_a, max_area_b) -> int:
        return 0  # informational only — nothing to act on for a single monitor

    def request_resize(self, width: int, height: int) -> None:
        """Ask the server to resize the remote desktop. Must be called from
        the same thread driving the connection (see
        rdp_session_worker.py's _drain_input_queue) — SendMonitorLayout,
        like every other Client* call, goes through libfreerdp."""
        if self._context is None:
            return
        width = max(DISPLAY_CONTROL_MIN_MONITOR_WIDTH, min(width, DISPLAY_CONTROL_MAX_MONITOR_WIDTH))
        height = max(DISPLAY_CONTROL_MIN_MONITOR_HEIGHT, min(height, DISPLAY_CONTROL_MAX_MONITOR_HEIGHT))
        layout = DISPLAY_CONTROL_MONITOR_LAYOUT()
        layout.Flags = DISPLAY_CONTROL_MONITOR_PRIMARY
        layout.Left = 0
        layout.Top = 0
        layout.Width = width
        layout.Height = height
        layout.PhysicalWidth = 0
        layout.PhysicalHeight = 0
        layout.Orientation = 0  # ORIENTATION_LANDSCAPE
        layout.DesktopScaleFactor = 100
        layout.DeviceScaleFactor = 100
        self._context.contents.SendMonitorLayout(self._context, 1, ctypes.byref(layout))
