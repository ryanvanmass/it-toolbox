"""Hand-written ctypes layer for libfreerdp3's clipboard (cliprdr) virtual
channel — CliprdrClientContext plus the CLIPRDR_* message structs, used to
announce local clipboard text to the remote session and respond when the
server asks for it.

Hand-written for the same reason as disp.py (see that module's docstring):
CliprdrClientContext lives in freerdp/client/cliprdr.h, which
scripts/generate_freerdp_bindings.py's default header list doesn't pull in
(confirmed empirically — grepping _freerdp3_bindings.py for "cliprdr"
returns nothing), and even if it did, a context struct meant to be
incrementally filled in by client code (only some callbacks set, others
left null) isn't something the generator has any notion of.

Source: freerdp/client/cliprdr.h and freerdp/channels/cliprdr.h, fetched
directly from github.com/FreeRDP/FreeRDP (current main branch) this
session, plus the actual protocol sequence read out of the real reference
client (client/X11/xf_cliprdr.c) and the channel-plugin internals
(channels/cliprdr/client/cliprdr_main.c, cliprdr_format.c) — not
reconstructed from memory. See docs/embedded-rdp-status.md's clipboard
section for why that mattered: an earlier attempt at this exact feature
was reverted after local-to-remote text sync never worked and the root
cause was never found, partly because that reference source wasn't
available at the time.

This module covers local-to-remote text only. Remote-to-local (reading
what the server's clipboard offers) is out of scope — ServerFormatList is
intentionally left unimplemented (null), so this client only ever
announces its own clipboard text, never requests the server's.
"""

import ctypes

from it_toolbox.core.rdp._freerdp3_bindings import UINT32

UINT16 = ctypes.c_uint16
UINT = UINT32

# freerdp/channels/cliprdr.h — CliprdrMsgType (CLIPRDR_HEADER.msgType)
CB_MONITOR_READY = 0x0001
CB_FORMAT_LIST = 0x0002
CB_FORMAT_DATA_REQUEST = 0x0004
CB_FORMAT_DATA_RESPONSE = 0x0005
CB_CLIP_CAPS = 0x0007

# CLIPRDR_HEADER.msgFlags
CB_RESPONSE_OK = 0x0001
CB_RESPONSE_FAIL = 0x0002

# CLIPRDR_CAPS_SET.capabilitySetType / CLIPRDR_GENERAL_CAPABILITY_SET.lengthCapability
CB_CAPSTYPE_GENERAL = 0x0001
CB_CAPSTYPE_GENERAL_LEN = 12

# CLIPRDR_GENERAL_CAPABILITY_SET.version
CB_CAPS_VERSION_2 = 0x00000002

# CLIPRDR_GENERAL_CAPABILITY_SET.generalFlags — the one we care about.
# Must be requested explicitly (see module docstring / status doc) rather
# than relying on FreeRDP's default, which is FALSE whenever the server
# never sends its own capabilities PDU (a legal, common case per the
# protocol comment in cliprdr_main.c's MonitorReady handler).
CB_USE_LONG_FORMAT_NAMES = 0x00000002

# include/freerdp/settings_types.h — clipboard feature mask, gates which
# directions/content types cliprdr_main.c will actually process. Already
# FreeRDP's own compiled-in default for a fresh settings object
# (libfreerdp/core/settings.c sets FreeRDP_ClipboardFeatureMask to exactly
# this on freerdp_settings_new()) — set explicitly in freerdp_client.py
# anyway, matching this project's style of not relying on an unstated
# library default for anything feature-relevant.
CLIPRDR_FLAG_LOCAL_TO_REMOTE = 0x01
CLIPRDR_FLAG_LOCAL_TO_REMOTE_FILES = 0x02
CLIPRDR_FLAG_REMOTE_TO_LOCAL = 0x10
CLIPRDR_FLAG_REMOTE_TO_LOCAL_FILES = 0x20
CLIPRDR_FLAG_DEFAULT_MASK = (
    CLIPRDR_FLAG_LOCAL_TO_REMOTE
    | CLIPRDR_FLAG_LOCAL_TO_REMOTE_FILES
    | CLIPRDR_FLAG_REMOTE_TO_LOCAL
    | CLIPRDR_FLAG_REMOTE_TO_LOCAL_FILES
)

# winuser.h — the only clipboard format this v1 supports.
CF_UNICODETEXT = 13


class CLIPRDR_HEADER(ctypes.Structure):
    _fields_ = [("msgType", UINT16), ("msgFlags", UINT16), ("dataLen", UINT32)]


class CLIPRDR_CAPABILITY_SET(ctypes.Structure):
    _fields_ = [("capabilitySetType", UINT16), ("capabilitySetLength", UINT16)]


class CLIPRDR_GENERAL_CAPABILITY_SET(ctypes.Structure):
    _fields_ = [
        ("capabilitySetType", UINT16),
        ("capabilitySetLength", UINT16),
        ("version", UINT32),
        ("generalFlags", UINT32),
    ]


class CLIPRDR_CAPABILITIES(ctypes.Structure):
    _fields_ = [
        ("common", CLIPRDR_HEADER),
        ("cCapabilitiesSets", UINT32),
        ("capabilitySets", ctypes.POINTER(CLIPRDR_CAPABILITY_SET)),
    ]


class CLIPRDR_MONITOR_READY(ctypes.Structure):
    _fields_ = [("common", CLIPRDR_HEADER)]


class CLIPRDR_FORMAT(ctypes.Structure):
    _fields_ = [("formatId", UINT32), ("formatName", ctypes.c_char_p)]


class CLIPRDR_FORMAT_LIST(ctypes.Structure):
    _fields_ = [
        ("common", CLIPRDR_HEADER),
        ("numFormats", UINT32),
        ("formats", ctypes.POINTER(CLIPRDR_FORMAT)),
    ]


class CLIPRDR_FORMAT_DATA_REQUEST(ctypes.Structure):
    _fields_ = [("common", CLIPRDR_HEADER), ("requestedFormatId", UINT32)]


class CLIPRDR_FORMAT_DATA_RESPONSE(ctypes.Structure):
    _fields_ = [
        ("common", CLIPRDR_HEADER),
        ("requestedFormatData", ctypes.POINTER(ctypes.c_ubyte)),
    ]


class CliprdrClientContext(ctypes.Structure):
    pass


# freerdp/client/cliprdr.h — every pcCliprdr* function-pointer field, in
# declared order. Only MonitorReady/ServerFormatDataRequest are callbacks
# we assign (inbound); ClientCapabilities/ClientFormatList/
# ClientFormatDataResponse are actions we call (outbound, already
# implemented by FreeRDP — assigned by the library itself when the channel
# loads). Every other field is left null: confirmed safe by reading
# cliprdr_main.c/cliprdr_format.c — every dispatch site goes through
# IFCALLRET or an explicit null check, so an unset callback is silently
# skipped, never a null-pointer call. Getting every field's *type* right
# (even ones this module never touches) is what keeps the offsets of the
# fields it does use correct.
_ServerCapabilitiesFn = ctypes.CFUNCTYPE(
    UINT, ctypes.POINTER(CliprdrClientContext), ctypes.POINTER(CLIPRDR_CAPABILITIES)
)
_ClientCapabilitiesFn = ctypes.CFUNCTYPE(
    UINT, ctypes.POINTER(CliprdrClientContext), ctypes.POINTER(CLIPRDR_CAPABILITIES)
)
_MonitorReadyFn = ctypes.CFUNCTYPE(
    UINT, ctypes.POINTER(CliprdrClientContext), ctypes.POINTER(CLIPRDR_MONITOR_READY)
)
_TempDirectoryFn = ctypes.CFUNCTYPE(UINT, ctypes.POINTER(CliprdrClientContext), ctypes.c_void_p)
_ClientFormatListFn = ctypes.CFUNCTYPE(
    UINT, ctypes.POINTER(CliprdrClientContext), ctypes.POINTER(CLIPRDR_FORMAT_LIST)
)
_ServerFormatListFn = ctypes.CFUNCTYPE(
    UINT, ctypes.POINTER(CliprdrClientContext), ctypes.POINTER(CLIPRDR_FORMAT_LIST)
)
_FormatListResponseFn = ctypes.CFUNCTYPE(UINT, ctypes.POINTER(CliprdrClientContext), ctypes.c_void_p)
_LockClipboardDataFn = ctypes.CFUNCTYPE(UINT, ctypes.POINTER(CliprdrClientContext), ctypes.c_void_p)
_UnlockClipboardDataFn = ctypes.CFUNCTYPE(UINT, ctypes.POINTER(CliprdrClientContext), ctypes.c_void_p)
_ClientFormatDataRequestFn = ctypes.CFUNCTYPE(
    UINT, ctypes.POINTER(CliprdrClientContext), ctypes.POINTER(CLIPRDR_FORMAT_DATA_REQUEST)
)
_ServerFormatDataRequestFn = ctypes.CFUNCTYPE(
    UINT, ctypes.POINTER(CliprdrClientContext), ctypes.POINTER(CLIPRDR_FORMAT_DATA_REQUEST)
)
_ClientFormatDataResponseFn = ctypes.CFUNCTYPE(
    UINT, ctypes.POINTER(CliprdrClientContext), ctypes.POINTER(CLIPRDR_FORMAT_DATA_RESPONSE)
)
_ServerFormatDataResponseFn = ctypes.CFUNCTYPE(
    UINT, ctypes.POINTER(CliprdrClientContext), ctypes.POINTER(CLIPRDR_FORMAT_DATA_RESPONSE)
)
_FileContentsRequestFn = ctypes.CFUNCTYPE(UINT, ctypes.POINTER(CliprdrClientContext), ctypes.c_void_p)
_FileContentsResponseFn = ctypes.CFUNCTYPE(UINT, ctypes.POINTER(CliprdrClientContext), ctypes.c_void_p)

CliprdrClientContext._fields_ = [
    ("handle", ctypes.c_void_p),
    ("custom", ctypes.c_void_p),
    ("ServerCapabilities", _ServerCapabilitiesFn),
    ("ClientCapabilities", _ClientCapabilitiesFn),
    ("MonitorReady", _MonitorReadyFn),
    ("TempDirectory", _TempDirectoryFn),
    ("ClientFormatList", _ClientFormatListFn),
    ("ServerFormatList", _ServerFormatListFn),
    ("ClientFormatListResponse", _FormatListResponseFn),
    ("ServerFormatListResponse", _FormatListResponseFn),
    ("ClientLockClipboardData", _LockClipboardDataFn),
    ("ServerLockClipboardData", _LockClipboardDataFn),
    ("ClientUnlockClipboardData", _UnlockClipboardDataFn),
    ("ServerUnlockClipboardData", _UnlockClipboardDataFn),
    ("ClientFormatDataRequest", _ClientFormatDataRequestFn),
    ("ServerFormatDataRequest", _ServerFormatDataRequestFn),
    ("ClientFormatDataResponse", _ClientFormatDataResponseFn),
    ("ServerFormatDataResponse", _ServerFormatDataResponseFn),
    ("ClientFileContentsRequest", _FileContentsRequestFn),
    ("ServerFileContentsRequest", _FileContentsRequestFn),
    ("ClientFileContentsResponse", _FileContentsResponseFn),
    ("ServerFileContentsResponse", _FileContentsResponseFn),
    ("lastRequestedFormatId", UINT32),
    ("rdpcontext", ctypes.c_void_p),
]


class ClipboardChannel:
    """Qt-free local-to-remote text clipboard logic, bound to a live
    CliprdrClientContext* once the "cliprdr" static channel connects (see
    freerdp_client.py's ChannelConnected subscription — same mechanism as
    disp.py's DisplayChannel, except "cliprdr" reports its literal short
    name on ChannelConnected, unlike "disp"'s full DVC name — confirmed in
    both this repo's own status doc and the real cliprdr_main.c, no
    name-matching gotcha here).
    """

    def __init__(self) -> None:
        self._context: ctypes.POINTER(CliprdrClientContext) | None = None
        # True once MonitorReady has fired at least once — announcing a
        # format list before then has no live reference implementation to
        # justify it and the real x11 client never does it either.
        self._ready = False
        self._local_text: str | None = None
        # Kept alive for the channel's lifetime — same reasoning as every
        # other CFUNCTYPE keepalive in this project.
        self._monitor_ready_cb = _MonitorReadyFn(self._on_monitor_ready)
        self._format_data_request_cb = _ServerFormatDataRequestFn(self._on_format_data_request)

    def bind(self, context: ctypes.POINTER(CliprdrClientContext)) -> None:
        """Called once, when the "cliprdr" channel connects."""
        self._context = context
        context.contents.MonitorReady = self._monitor_ready_cb
        context.contents.ServerFormatDataRequest = self._format_data_request_cb

    def _on_monitor_ready(self, context, monitor_ready) -> int:
        self._send_client_capabilities()
        self._ready = True
        self._send_format_list()
        return 0  # CHANNEL_RC_OK

    def announce_text(self, text: str | None) -> None:
        """Call whenever the local clipboard changes. Caches the text
        regardless of channel state; only actually sends a format list if
        MonitorReady has already fired — mirrors DisplayChannel's "no
        server cooperation possible yet" gating in disp.py. Must be called
        from the same thread driving the connection (see
        rdp_session_worker.py's _drain_input_queue).
        """
        self._local_text = text
        if self._ready:
            self._send_format_list()

    def _send_client_capabilities(self) -> None:
        general = CLIPRDR_GENERAL_CAPABILITY_SET(
            capabilitySetType=CB_CAPSTYPE_GENERAL,
            capabilitySetLength=CB_CAPSTYPE_GENERAL_LEN,
            version=CB_CAPS_VERSION_2,
            generalFlags=CB_USE_LONG_FORMAT_NAMES,
        )
        caps = CLIPRDR_CAPABILITIES(
            cCapabilitiesSets=1,
            capabilitySets=ctypes.cast(ctypes.byref(general), ctypes.POINTER(CLIPRDR_CAPABILITY_SET)),
        )
        self._context.contents.ClientCapabilities(self._context, ctypes.byref(caps))

    def _send_format_list(self) -> None:
        if self._local_text:
            fmt = CLIPRDR_FORMAT(formatId=CF_UNICODETEXT, formatName=None)
            format_list = CLIPRDR_FORMAT_LIST(numFormats=1, formats=ctypes.pointer(fmt))
        else:
            format_list = CLIPRDR_FORMAT_LIST(numFormats=0, formats=None)
        self._context.contents.ClientFormatList(self._context, ctypes.byref(format_list))

    def _on_format_data_request(self, context, request) -> int:
        # common.msgFlags/dataLen must be set here (unlike Capabilities/
        # FormatList, whose own serializers ignore .common and build the
        # wire header themselves from the message type + payload) —
        # confirmed by reading cliprdr_client_format_data_response's own
        # implementation, which reads these two fields plus
        # requestedFormatData directly.
        if request.contents.requestedFormatId == CF_UNICODETEXT and self._local_text:
            payload = (self._local_text + "\0").encode("utf-16-le")
            buf = ctypes.create_string_buffer(payload, len(payload))
            response = CLIPRDR_FORMAT_DATA_RESPONSE(
                common=CLIPRDR_HEADER(
                    msgType=CB_FORMAT_DATA_RESPONSE, msgFlags=CB_RESPONSE_OK, dataLen=len(payload)
                ),
                requestedFormatData=ctypes.cast(buf, ctypes.POINTER(ctypes.c_ubyte)),
            )
        else:
            response = CLIPRDR_FORMAT_DATA_RESPONSE(
                common=CLIPRDR_HEADER(
                    msgType=CB_FORMAT_DATA_RESPONSE, msgFlags=CB_RESPONSE_FAIL, dataLen=0
                ),
                requestedFormatData=None,
            )
        context.contents.ClientFormatDataResponse(context, ctypes.byref(response))
        return 0  # CHANNEL_RC_OK
