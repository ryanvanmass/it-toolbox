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

_IS_WINDOWS = platform.system() == "Windows"


def _load(name: str) -> ctypes.CDLL:
    return ctypes.WinDLL(name) if _IS_WINDOWS else ctypes.CDLL(name)


# libfreerdp-client3 provides the client-context scaffolding functions;
# libfreerdp3 provides the core connect/disconnect/settings API. Two
# separate shared objects on Linux; same split on Windows (libfreerdp-client3.dll
# / libfreerdp3.dll), untested there so far — see the module docstring in
# scripts/generate_freerdp_bindings.py for the Linux-only status of this work.
_client_lib = _load("libfreerdp-client3.so.3" if not _IS_WINDOWS else "libfreerdp-client3.dll")
_core_lib = _load("libfreerdp3.so.3" if not _IS_WINDOWS else "libfreerdp3.dll")

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

    try:
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

        instance = context.contents.instance
        if not _core_lib.freerdp_connect(instance):
            code = _core_lib.freerdp_get_last_error(context)
            message = _core_lib.freerdp_get_last_error_string(code)
            text = message.decode(errors="replace") if message else "unknown error"
            raise FreeRdpError(f"freerdp_connect failed: {text} (code {code:#x})", code=code)

        _core_lib.freerdp_disconnect(instance)
    finally:
        _client_lib.freerdp_client_context_free(context)


def _cli_main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description=(
            "Milestone-1 smoke test: connect to a real RDP server via the ctypes "
            "libfreerdp3 bindings and immediately disconnect. Proves the FFI layer "
            "works before any Qt/rendering code depends on it."
        )
    )
    parser.add_argument("--host", required=True)
    parser.add_argument("--port", type=int, default=3389)
    parser.add_argument("--username", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument("--domain", default="")
    args = parser.parse_args()

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
