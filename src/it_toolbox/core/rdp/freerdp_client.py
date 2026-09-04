"""Thin, hand-written ctypes layer over libfreerdp3's connection lifecycle.

Deliberately separate from the auto-generated `_freerdp3_bindings` module:
struct layout is exactly the kind of thing that must come from the real
headers (70+ fields, actively evolving, silent corruption if transcribed
by hand), but a function's *signature* is small, stable, and easy to
verify by eye against the header — see the comment above each ctypes
declaration for the exact prototype it mirrors, from FreeRDP3's
freerdp.h/client.h/settings.h.

Settings are addressed by integer key, not struct field offset (FreeRDP3
made rdpSettings opaque and requires going through
freerdp_settings_set_*() accessors). The key values below are copied from
freerdp/settings_keys.h — a flat, stable, publicly documented enum — not
generated, since pulling in that entire 600-line enum via clang2py for a
handful of constants isn't worth the added moving part.

This module is Qt-free and holds no rendering/UI code: it only proves
out the connect/disconnect lifecycle, mirroring how core/iap_tunnel.py
was validated via a standalone CLI before any Qt code depended on it.
"""

import ctypes
import os
import platform

from it_toolbox.core.rdp._freerdp3_bindings import (
    struct_rdp_client_context as RdpClientContext,
)
from it_toolbox.core.rdp._freerdp3_bindings import (
    struct_rdp_client_entry_points_v1 as RdpClientEntryPointsV1,
)
from it_toolbox.core.rdp._freerdp3_bindings import (
    struct_rdp_context as RdpContext,
)
from it_toolbox.core.rdp._freerdp3_bindings import (
    struct_rdp_freerdp as RdpFreerdp,
)
from it_toolbox.core.rdp._freerdp3_bindings import (
    struct_ChannelConnectedEventArgs as ChannelConnectedEventArgs,
)
from it_toolbox.core.rdp._freerdp3_bindings import (
    struct_rdp_gdi as RdpGdi,
)
from it_toolbox.core.rdp._freerdp3_bindings import (
    struct_s_wPubSub as WPubSub,
)
from it_toolbox.core.rdp.disp import DispClientContext, DisplayChannel

RDP_CLIENT_INTERFACE_VERSION = 1  # freerdp/client.h

# freerdp/settings_keys.h — FreeRDP_Settings_Keys_{String,UInt32,Bool} values.
# Stable, documented ABI integers; not order-dependent auto-generated code.
SETTING_SERVER_PORT = 19  # FreeRDP_Settings_Keys_UInt32
SETTING_SERVER_HOSTNAME = 20  # FreeRDP_Settings_Keys_String
SETTING_USERNAME = 21  # FreeRDP_Settings_Keys_String
SETTING_PASSWORD = 22  # FreeRDP_Settings_Keys_String
SETTING_DOMAIN = 23  # FreeRDP_Settings_Keys_String
SETTING_TLS_SECURITY = 1088  # FreeRDP_Settings_Keys_Bool
SETTING_NLA_SECURITY = 1089  # FreeRDP_Settings_Keys_Bool
SETTING_RDP_SECURITY = 1090  # FreeRDP_Settings_Keys_Bool
SETTING_IGNORE_CERTIFICATE = 1408  # FreeRDP_Settings_Keys_Bool
SETTING_DYNAMIC_RESOLUTION_UPDATE = 1558  # FreeRDP_Settings_Keys_Bool
SETTING_SUPPORT_DISPLAY_CONTROL = 5185  # FreeRDP_Settings_Keys_Bool

# freerdp/codec/color.h — FREERDP_PIXEL_FORMAT(32, TYPE_BGRA, a=0, r=8, g=8, b=8).
# Computed rather than transcribed from a literal, since the header only
# defines it via macro arithmetic: (bpp<<24)|(type<<16)|(a<<12)|(r<<8)|(g<<4)|b.
# Chosen because it lines up byte-for-byte with Qt's QImage.Format_RGB32 on a
# little-endian host, letting the gdi primary_buffer be wrapped by a QImage
# with no per-pixel conversion.
PIXEL_FORMAT_BGRX32 = (32 << 24) | (4 << 16) | (0 << 12) | (8 << 8) | (8 << 4) | 8

_IS_WINDOWS = platform.system() == "Windows"

# Set this to the folder holding freerdp3.dll/freerdp-client3.dll/winpr3.dll
# (e.g. a vcpkg installed/x64-windows/bin, or wherever you extracted a
# FreeRDP3 Windows build) if they aren't already on PATH. See
# docs/windows-freerdp-setup.md for how to obtain them — there's no
# official prebuilt package, so this is currently a self-built/vendored
# dependency on Windows, unlike Linux where it's a normal system package.
_FREERDP_DIR_ENV = "IT_TOOLBOX_FREERDP_DIR"

if _IS_WINDOWS:
    _freerdp_dir = os.environ.get(_FREERDP_DIR_ENV)
    if _freerdp_dir:
        # add_dll_directory is what actually matters for *dependency*
        # resolution (e.g. freerdp3.dll pulling in winpr3.dll) — ctypes.WinDLL
        # loading freerdp3.dll by an absolute path does not, on its own, add
        # that DLL's own folder to the search path Windows uses to resolve
        # its dependencies (a deliberate post-3.7 hardening against DLL
        # hijacking). Prepending to PATH too is belt-and-suspenders for
        # older-loader edge cases.
        os.add_dll_directory(_freerdp_dir)
        os.environ["PATH"] = _freerdp_dir + os.pathsep + os.environ.get("PATH", "")


def _load(candidates: list[str]) -> ctypes.CDLL:
    """Tries each candidate DLL/SO name in order — the exact Windows naming
    (lib prefix or not, version suffix or not) depends on how FreeRDP3 was
    built there, which nothing has verified yet (see the module docstring).
    Fails with every name tried and a pointer to the setup doc, rather than
    a bare "file not found" for whichever name happened to be tried first.
    """
    errors = []
    for name in candidates:
        try:
            return ctypes.WinDLL(name) if _IS_WINDOWS else ctypes.CDLL(name)
        except OSError as exc:
            errors.append(f"  {name}: {exc}")
    tried = "\n".join(errors)
    hint = (
        f"Set {_FREERDP_DIR_ENV} to the folder containing these DLLs — see "
        "docs/windows-freerdp-setup.md."
        if _IS_WINDOWS
        else "Is the freerdp/libfreerdp3 package installed?"
    )
    raise OSError(f"Could not load any of:\n{tried}\n{hint}")


# libfreerdp-client3 provides the client-context scaffolding functions;
# libfreerdp3 provides the core connect/disconnect/settings API. Two
# separate shared objects on Linux (confirmed via `nm -D`); Windows naming
# is unverified — CMake shared libraries don't get a "lib" prefix there by
# default, but some FreeRDP Windows builds have historically kept it, so
# both are tried.
_client_lib = _load(
    ["libfreerdp-client3.so.3"] if not _IS_WINDOWS else ["freerdp-client3.dll", "libfreerdp-client3.dll"]
)
_core_lib = _load(["libfreerdp3.so.3"] if not _IS_WINDOWS else ["freerdp3.dll", "libfreerdp3.dll"])
# winpr3 provides PubSub_Subscribe, used to learn when a virtual channel
# (disp/cliprdr/...) has connected — see FreeRdpSession._on_channel_connected.
_winpr_lib = _load(["libwinpr3.so.3"] if not _IS_WINDOWS else ["winpr3.dll", "libwinpr3.dll"])

# rdpContext* freerdp_client_context_new(const RDP_CLIENT_ENTRY_POINTS* pEntryPoints);
_client_lib.freerdp_client_context_new.argtypes = [ctypes.POINTER(RdpClientEntryPointsV1)]
_client_lib.freerdp_client_context_new.restype = ctypes.POINTER(RdpContext)

# void freerdp_client_context_free(rdpContext* context);
_client_lib.freerdp_client_context_free.argtypes = [ctypes.POINTER(RdpContext)]
_client_lib.freerdp_client_context_free.restype = None

# BOOL freerdp_connect(freerdp* instance);
_core_lib.freerdp_connect.argtypes = [ctypes.POINTER(RdpFreerdp)]
_core_lib.freerdp_connect.restype = ctypes.c_int32

# BOOL freerdp_disconnect(freerdp* instance);
_core_lib.freerdp_disconnect.argtypes = [ctypes.POINTER(RdpFreerdp)]
_core_lib.freerdp_disconnect.restype = ctypes.c_int32

# UINT32 freerdp_get_last_error(const rdpContext* context);
_core_lib.freerdp_get_last_error.argtypes = [ctypes.POINTER(RdpContext)]
_core_lib.freerdp_get_last_error.restype = ctypes.c_uint32

# const char* freerdp_get_last_error_string(UINT32 code);
_core_lib.freerdp_get_last_error_string.argtypes = [ctypes.c_uint32]
_core_lib.freerdp_get_last_error_string.restype = ctypes.c_char_p

# BOOL freerdp_settings_set_string(rdpSettings* settings, FreeRDP_Settings_Keys_String id, const char* val);
_core_lib.freerdp_settings_set_string.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_char_p]
_core_lib.freerdp_settings_set_string.restype = ctypes.c_int32

# BOOL freerdp_settings_set_uint32(rdpSettings* settings, FreeRDP_Settings_Keys_UInt32 id, UINT32 val);
_core_lib.freerdp_settings_set_uint32.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_uint32]
_core_lib.freerdp_settings_set_uint32.restype = ctypes.c_int32

# BOOL freerdp_settings_set_bool(rdpSettings* settings, FreeRDP_Settings_Keys_Bool id, BOOL val);
_core_lib.freerdp_settings_set_bool.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int32]
_core_lib.freerdp_settings_set_bool.restype = ctypes.c_int32

# BOOL gdi_init(freerdp* instance, UINT32 format);   (freerdp/gdi/gdi.h)
_core_lib.gdi_init.argtypes = [ctypes.POINTER(RdpFreerdp), ctypes.c_uint32]
_core_lib.gdi_init.restype = ctypes.c_int32

# BOOL freerdp_check_event_handles(rdpContext* context);
_core_lib.freerdp_check_event_handles.argtypes = [ctypes.POINTER(RdpContext)]
_core_lib.freerdp_check_event_handles.restype = ctypes.c_int32

# BOOL gdi_resize(rdpGdi* gdi, UINT32 width, UINT32 height);  (freerdp/gdi/gdi.h)
# Resizes the local framebuffer to match a resolution change we requested
# via the disp channel — there's no "desktop was resized" callback the way
# PostConnect/EndPaint are exposed, since we're the one initiating the
# resize, so we're also responsible for keeping gdi's buffer in sync.
_core_lib.gdi_resize.argtypes = [ctypes.POINTER(RdpGdi), ctypes.c_uint32, ctypes.c_uint32]
_core_lib.gdi_resize.restype = ctypes.c_int32

# int PubSub_Subscribe(wPubSub* pubSub, const char* EventName, ...);
# Declared variadic in winpr/collections.h, but every real call site (via
# the DEFINE_EVENT_SUBSCRIBE macro) passes exactly one further argument, a
# specific event-handler function pointer — fixed 3-arg ctypes argtypes
# below match that actual calling pattern.
_winpr_lib.PubSub_Subscribe.argtypes = [ctypes.POINTER(WPubSub), ctypes.c_char_p, ctypes.c_void_p]
_winpr_lib.PubSub_Subscribe.restype = ctypes.c_int32

# rdpInput is treated as opaque here — every call below only ever passes the
# pointer straight through to libfreerdp, never dereferences a field of it.
_RdpInputP = ctypes.c_void_p

# BOOL freerdp_input_send_mouse_event(rdpInput* input, UINT16 flags, UINT16 x, UINT16 y);
_core_lib.freerdp_input_send_mouse_event.argtypes = [
    _RdpInputP,
    ctypes.c_uint16,
    ctypes.c_uint16,
    ctypes.c_uint16,
]
_core_lib.freerdp_input_send_mouse_event.restype = ctypes.c_int32

# BOOL freerdp_input_send_extended_mouse_event(rdpInput* input, UINT16 flags, UINT16 x, UINT16 y);
_core_lib.freerdp_input_send_extended_mouse_event.argtypes = [
    _RdpInputP,
    ctypes.c_uint16,
    ctypes.c_uint16,
    ctypes.c_uint16,
]
_core_lib.freerdp_input_send_extended_mouse_event.restype = ctypes.c_int32

# BOOL freerdp_input_send_keyboard_event(rdpInput* input, UINT16 flags, UINT8 code);
_core_lib.freerdp_input_send_keyboard_event.argtypes = [
    _RdpInputP,
    ctypes.c_uint16,
    ctypes.c_uint8,
]
_core_lib.freerdp_input_send_keyboard_event.restype = ctypes.c_int32

# BOOL freerdp_input_send_unicode_keyboard_event(rdpInput* input, UINT16 flags, UINT16 code);
_core_lib.freerdp_input_send_unicode_keyboard_event.argtypes = [
    _RdpInputP,
    ctypes.c_uint16,
    ctypes.c_uint16,
]
_core_lib.freerdp_input_send_unicode_keyboard_event.restype = ctypes.c_int32

# freerdp/input.h — keyboard/mouse event flag bits.
KBD_FLAGS_EXTENDED = 0x0100
KBD_FLAGS_RELEASE = 0x8000
PTR_FLAGS_WHEEL = 0x0200
PTR_FLAGS_WHEEL_NEGATIVE = 0x0100
PTR_FLAGS_MOVE = 0x0800
PTR_FLAGS_DOWN = 0x8000
PTR_FLAGS_BUTTON1 = 0x1000  # left
PTR_FLAGS_BUTTON2 = 0x2000  # right
PTR_FLAGS_BUTTON3 = 0x4000  # middle
PTR_XFLAGS_DOWN = 0x8000
PTR_XFLAGS_BUTTON1 = 0x0001  # X1 (back)
PTR_XFLAGS_BUTTON2 = 0x0002  # X2 (forward)

# ClientNew/ClientFree are optional per-context init/teardown hooks; we don't
# need any custom per-context state for a bare connect/disconnect smoke test,
# but they must be real callable CFUNCTYPE instances (not None) — FreeRDP
# calls them unconditionally rather than null-checking. A Python reference is
# kept at module scope so ctypes doesn't garbage-collect the trampoline while
# libfreerdp still holds a pointer to it.
_CLIENT_NEW_TYPE = ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.POINTER(RdpFreerdp), ctypes.POINTER(RdpContext))
_CLIENT_FREE_TYPE = ctypes.CFUNCTYPE(None, ctypes.POINTER(RdpFreerdp), ctypes.POINTER(RdpContext))
_client_new_cb = _CLIENT_NEW_TYPE(lambda instance, context: 1)
_client_free_cb = _CLIENT_FREE_TYPE(lambda instance, context: None)


class FreeRdpError(Exception):
    """A libfreerdp call failed. `code`/`name` come straight from
    freerdp_get_last_error()/freerdp_get_last_error_string() when available."""

    def __init__(self, message: str, code: int | None = None) -> None:
        super().__init__(message)
        self.code = code


def _new_context() -> ctypes.POINTER(RdpContext):
    entry_points = RdpClientEntryPointsV1()
    entry_points.Size = ctypes.sizeof(RdpClientEntryPointsV1)
    entry_points.Version = RDP_CLIENT_INTERFACE_VERSION
    # Must be sized for the full rdpClientContext, not just the base
    # rdpContext embedded at its front — libfreerdp's virtual-channel
    # plumbing (rdpsnd/drdynvc/ainput etc.) writes into rdpClientContext
    # fields during connect, so an undersized buffer here is a heap
    # overflow: reproduced as "double free or corruption (!prev)" against
    # a real server before this was corrected.
    entry_points.ContextSize = ctypes.sizeof(RdpClientContext)
    entry_points.ClientNew = _client_new_cb
    entry_points.ClientFree = _client_free_cb

    context = _client_lib.freerdp_client_context_new(ctypes.byref(entry_points))
    if not context:
        raise FreeRdpError("freerdp_client_context_new returned NULL")
    return context


def _configure_settings(
    context: ctypes.POINTER(RdpContext),
    host: str,
    port: int,
    username: str,
    password: str,
    domain: str,
    ignore_certificate: bool,
) -> None:
    settings = context.contents.settings  # c_void_p, opaque — accessed via accessors only
    _core_lib.freerdp_settings_set_string(settings, SETTING_SERVER_HOSTNAME, host.encode())
    _core_lib.freerdp_settings_set_uint32(settings, SETTING_SERVER_PORT, port)
    _core_lib.freerdp_settings_set_string(settings, SETTING_USERNAME, username.encode())
    _core_lib.freerdp_settings_set_string(settings, SETTING_PASSWORD, password.encode())
    if domain:
        _core_lib.freerdp_settings_set_string(settings, SETTING_DOMAIN, domain.encode())
    _core_lib.freerdp_settings_set_bool(settings, SETTING_IGNORE_CERTIFICATE, int(ignore_certificate))
    _core_lib.freerdp_settings_set_bool(settings, SETTING_NLA_SECURITY, 1)
    _core_lib.freerdp_settings_set_bool(settings, SETTING_TLS_SECURITY, 1)
    _core_lib.freerdp_settings_set_bool(settings, SETTING_RDP_SECURITY, 1)
    _core_lib.freerdp_settings_set_bool(settings, SETTING_SUPPORT_DISPLAY_CONTROL, 1)
    _core_lib.freerdp_settings_set_bool(settings, SETTING_DYNAMIC_RESOLUTION_UPDATE, 1)


def _raise_last_error(context: ctypes.POINTER(RdpContext), prefix: str) -> None:
    code = _core_lib.freerdp_get_last_error(context)
    message = _core_lib.freerdp_get_last_error_string(code)
    text = message.decode(errors="replace") if message else "unknown error"
    raise FreeRdpError(f"{prefix}: {text} (code {code:#x})", code=code)


def connect_and_disconnect(
    host: str,
    port: int,
    username: str,
    password: str,
    domain: str = "",
    ignore_certificate: bool = True,
) -> None:
    """Milestone-1 smoke test: perform a full RDP handshake and immediately
    tear it down. Proves the ctypes binding layer is wired correctly
    end-to-end before any rendering or Qt integration is attempted.

    Raises FreeRdpError on failure to connect.
    """
    context = _new_context()
    try:
        _configure_settings(context, host, port, username, password, domain, ignore_certificate)
        instance = context.contents.instance
        if not _core_lib.freerdp_connect(instance):
            _raise_last_error(context, "freerdp_connect failed")
        _core_lib.freerdp_disconnect(instance)
    finally:
        _client_lib.freerdp_client_context_free(context)


# BOOL (*pPostConnect)(freerdp* instance); called by freerdp_connect() once the
# handshake is complete — this is where a client is expected to set up
# rendering (gdi_init) and hook the update callbacks it cares about.
_POST_CONNECT_TYPE = ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.POINTER(RdpFreerdp))
# BOOL (*pEndPaint)(rdpContext* context); fired after each frame update is
# fully applied to the GDI surface — the signal to go read gdi->primary_buffer.
_END_PAINT_TYPE = ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.POINTER(RdpContext))
# void (*)(void* context, const ChannelConnectedEventArgs* e); fired once per
# virtual channel as each one finishes connecting — the disp/cliprdr client
# contexts only exist from this point on, unlike PostConnect/EndPaint which
# are fixed single-slot callbacks set up front.
_CHANNEL_CONNECTED_TYPE = ctypes.CFUNCTYPE(
    None, ctypes.c_void_p, ctypes.POINTER(ChannelConnectedEventArgs)
)


class FreeRdpSession:
    """A connected RDP session with software (GDI) rendering.

    Not thread-safe and not Qt-aware by design — this is the Qt-free core,
    meant to be driven from a dedicated background thread the same way
    core/tunnel_session.py drives the IAP tunnel's asyncio loop, with a
    Qt widget subscribing to on_frame via a queued-connection signal
    rather than touching this object directly from the GUI thread.
    """

    def __init__(self) -> None:
        self._context: ctypes.POINTER(RdpContext) | None = None
        self.on_frame: callable | None = None  # called with no args after each EndPaint
        self.display = DisplayChannel()
        # A resize requested before "disp" (a dynamic virtual channel,
        # negotiated *after* the main handshake) has bound is otherwise
        # silently dropped by request_resize's guard below — exactly what
        # happens when a session opens straight into an already-sized
        # widget (e.g. a maximized window): the initial resize-to-fit
        # races the channel negotiation and loses, leaving the session
        # stuck at FreeRDP's default resolution until something happens
        # to trigger a second resize. Remembered here and replayed once
        # the channel binds (_on_channel_connected) instead of lost.
        self._pending_resize: tuple[int, int] | None = None
        # Kept alive for the lifetime of the session — ctypes does not keep
        # a reference to a CFUNCTYPE instance on its own, and libfreerdp
        # holds these pointers for as long as the connection is open.
        self._post_connect_cb = _POST_CONNECT_TYPE(self._on_post_connect)
        self._end_paint_cb = _END_PAINT_TYPE(self._on_end_paint)
        self._channel_connected_cb = _CHANNEL_CONNECTED_TYPE(self._on_channel_connected)

    def _on_post_connect(self, instance: ctypes.POINTER(RdpFreerdp)) -> int:
        if not _core_lib.gdi_init(instance, PIXEL_FORMAT_BGRX32):
            return 0
        context = instance.contents.context
        context.contents.update.contents.EndPaint = self._end_paint_cb
        return 1

    def _on_end_paint(self, context: ctypes.POINTER(RdpContext)) -> int:
        if self.on_frame is not None:
            self.on_frame()
        return 1

    def _on_channel_connected(self, sender, event_args: ctypes.POINTER(ChannelConnectedEventArgs)) -> None:
        # .name is POINTER(c_char), not c_char_p — doesn't auto-convert to
        # bytes on comparison, needs an explicit cast to read it as a string.
        name = ctypes.cast(event_args.contents.name, ctypes.c_char_p).value
        # disp is a Dynamic Virtual Channel (unlike cliprdr's static
        # channel) — freerdp/channels/disp.h defines two different name
        # constants ("disp" the addin name vs. the DVC's actual protocol
        # name), and it's unverified which one ChannelConnected reports,
        # so match either rather than guess wrong and silently never bind.
        if name in (b"disp", b"Microsoft::Windows::RDS::DisplayControl"):
            disp_context = ctypes.cast(event_args.contents.pInterface, ctypes.POINTER(DispClientContext))
            self.display.bind(disp_context)
            if self._pending_resize is not None:
                width, height = self._pending_resize
                self._pending_resize = None
                self._apply_resize(width, height)

    def request_resize(self, width: int, height: int) -> None:
        """Ask the server to resize the remote desktop, and resize the
        local framebuffer to match. Call only from the thread driving the
        connection (see rdp_session_worker.py's _drain_input_queue)."""
        if self._context is None:
            return
        if self.display._context is None:
            # "disp" hasn't bound yet (see _on_channel_connected) — no
            # server-side cooperation possible right now, and resizing the
            # local GDI buffer alone without the server also resizing
            # would desync the two (stale bitmap data reinterpreted at
            # wrong dimensions), which is worse than a no-op: produces a
            # cropped/corrupted display instead of just not resizing yet.
            # Remember the request and replay it once the channel binds,
            # rather than dropping it on the floor.
            self._pending_resize = (width, height)
            return
        self._apply_resize(width, height)

    def _apply_resize(self, width: int, height: int) -> None:
        gdi = self._context.contents.gdi
        _core_lib.gdi_resize(gdi, width, height)
        self.display.request_resize(width, height)

    def connect(
        self,
        host: str,
        port: int,
        username: str,
        password: str,
        domain: str = "",
        ignore_certificate: bool = True,
    ) -> None:
        context = _new_context()
        self._context = context
        _configure_settings(context, host, port, username, password, domain, ignore_certificate)
        context.contents.instance.contents.PostConnect = self._post_connect_cb
        _winpr_lib.PubSub_Subscribe(
            context.contents.pubSub,
            b"ChannelConnected",
            ctypes.cast(self._channel_connected_cb, ctypes.c_void_p),
        )
        if not _core_lib.freerdp_connect(context.contents.instance):
            self._context = None
            error = context  # capture before freeing, for the error message
            try:
                _raise_last_error(error, "freerdp_connect failed")
            finally:
                _client_lib.freerdp_client_context_free(context)

    def pump_once(self) -> bool:
        """Process any pending protocol data (drives PDU parsing, which in
        turn fires on_frame via EndPaint). Returns False when the connection
        has gone away and should be torn down."""
        if self._context is None:
            return False
        return bool(_core_lib.freerdp_check_event_handles(self._context))

    def get_frame(self) -> tuple[bytes, int, int, int]:
        """Returns (bgrx_pixels, width, height, stride) — a copy of the
        current GDI surface, safe to hand off across threads."""
        if self._context is None:
            raise FreeRdpError("not connected")
        gdi = self._context.contents.gdi.contents  # rdpContext.gdi: POINTER(struct_rdp_gdi)
        size = gdi.stride * gdi.height
        pixels = ctypes.string_at(gdi.primary_buffer, size)
        return pixels, gdi.width, gdi.height, gdi.stride

    def disconnect(self) -> None:
        if self._context is None:
            return
        instance = self._context.contents.instance
        _core_lib.freerdp_disconnect(instance)
        _client_lib.freerdp_client_context_free(self._context)
        self._context = None

    # --- input ---------------------------------------------------------
    # Call these only from the same thread that owns the connection (i.e.
    # the thread calling pump_once()), matching how libfreerdp's own event
    # loop is documented to be single-threaded per session.

    def send_mouse_move(self, x: int, y: int) -> None:
        self._send_mouse(PTR_FLAGS_MOVE, x, y)

    def send_mouse_button(self, x: int, y: int, button: str, down: bool) -> None:
        button_flag = {"left": PTR_FLAGS_BUTTON1, "right": PTR_FLAGS_BUTTON2, "middle": PTR_FLAGS_BUTTON3}
        if button in button_flag:
            flags = button_flag[button] | (PTR_FLAGS_DOWN if down else 0)
            self._send_mouse(flags, x, y)
        elif button in ("x1", "x2"):
            xflag = PTR_XFLAGS_BUTTON1 if button == "x1" else PTR_XFLAGS_BUTTON2
            flags = xflag | (PTR_XFLAGS_DOWN if down else 0)
            self._send_extended_mouse(flags, x, y)

    def send_mouse_wheel(self, x: int, y: int, delta_steps: int) -> None:
        """delta_steps > 0 scrolls up/away, < 0 scrolls down/toward — matches
        the sign of Qt's QWheelEvent.angleDelta().y() // 120."""
        magnitude = min(abs(delta_steps) * 120, 0xFF)
        flags = PTR_FLAGS_WHEEL | magnitude
        if delta_steps < 0:
            flags |= PTR_FLAGS_WHEEL_NEGATIVE
        self._send_mouse(flags, x, y)

    def _send_mouse(self, flags: int, x: int, y: int) -> None:
        if self._context is None:
            return
        _core_lib.freerdp_input_send_mouse_event(
            self._context.contents.input, flags, max(x, 0), max(y, 0)
        )

    def _send_extended_mouse(self, flags: int, x: int, y: int) -> None:
        if self._context is None:
            return
        _core_lib.freerdp_input_send_extended_mouse_event(
            self._context.contents.input, flags, max(x, 0), max(y, 0)
        )

    def send_key_scancode(self, code: int, extended: bool, down: bool) -> None:
        if self._context is None:
            return
        flags = (KBD_FLAGS_EXTENDED if extended else 0) | (0 if down else KBD_FLAGS_RELEASE)
        _core_lib.freerdp_input_send_keyboard_event(self._context.contents.input, flags, code)

    def send_key_unicode(self, codepoint: int, down: bool) -> None:
        if self._context is None:
            return
        flags = 0 if down else KBD_FLAGS_RELEASE
        _core_lib.freerdp_input_send_unicode_keyboard_event(
            self._context.contents.input, flags, codepoint
        )


def _write_ppm(path: str, pixels: bytes, width: int, height: int, stride: int) -> None:
    """Writes a raw PPM (P6) — trivial, uncompressed, no dependency beyond
    stdlib, good enough for a one-off "did rendering actually work" check.
    Converts BGRX (our PIXEL_FORMAT_BGRX32 surface) to RGB row by row,
    since PPM has no BGR/padding variant.
    """
    with open(path, "wb") as f:
        f.write(f"P6\n{width} {height}\n255\n".encode())
        for y in range(height):
            row = pixels[y * stride : y * stride + width * 4]
            rgb = bytearray(width * 3)
            rgb[0::3] = row[2::4]  # R
            rgb[1::3] = row[1::4]  # G
            rgb[2::3] = row[0::4]  # B
            f.write(rgb)


def capture_one_frame(
    host: str,
    port: int,
    username: str,
    password: str,
    output_path: str,
    domain: str = "",
    timeout_sec: float = 15.0,
    settle_sec: float = 2.0,
) -> None:
    """Milestone-2 smoke test: connect with GDI rendering enabled, pump the
    protocol until at least one frame has been painted, keep pumping for a
    short settle period (the desktop arrives as many incremental bitmap
    updates, not one shot — the very first EndPaint is typically still
    mostly blank), save the result as a PPM, then disconnect. Proves
    gdi_init + the EndPaint hook + reading the GDI surface all work before
    any Qt widget is built around this.
    """
    import time

    session = FreeRdpSession()
    frame_ready = False
    last_frame_at = 0.0

    def _on_frame() -> None:
        nonlocal frame_ready, last_frame_at
        frame_ready = True
        last_frame_at = time.monotonic()

    session.on_frame = _on_frame
    session.connect(host, port, username, password, domain=domain)
    try:
        deadline = time.monotonic() + timeout_sec
        while time.monotonic() < deadline:
            if not session.pump_once():
                raise FreeRdpError("connection closed before any frame was painted")
            if frame_ready and time.monotonic() - last_frame_at > settle_sec:
                break
        if not frame_ready:
            raise FreeRdpError(f"no frame painted within {timeout_sec}s")
        pixels, width, height, stride = session.get_frame()
        _write_ppm(output_path, pixels, width, height, stride)
        print(f"Wrote {width}x{height} frame to {output_path}")
    finally:
        session.disconnect()


def _cli_main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description=(
            "Connect to a real RDP server via the ctypes libfreerdp3 bindings. "
            "By default performs the Milestone-1 connect/disconnect smoke test; "
            "with --capture-frame, performs the Milestone-2 rendering smoke test."
        )
    )
    parser.add_argument("--host", required=True)
    parser.add_argument("--port", type=int, default=3389)
    parser.add_argument("--username", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument("--domain", default="")
    parser.add_argument(
        "--capture-frame",
        metavar="PATH",
        help="Also render and save the first frame as a PPM image to this path.",
    )
    args = parser.parse_args()

    if args.capture_frame:
        capture_one_frame(
            host=args.host,
            port=args.port,
            username=args.username,
            password=args.password,
            domain=args.domain,
            output_path=args.capture_frame,
        )
    else:
        connect_and_disconnect(
            host=args.host,
            port=args.port,
            username=args.username,
            password=args.password,
            domain=args.domain,
        )
        print("Connected and disconnected successfully.")


if __name__ == "__main__":
    _cli_main()
