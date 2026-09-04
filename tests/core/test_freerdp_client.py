"""Covers FreeRdpSession.request_resize's pending-resize handling —
pure Python control flow, exercised with real ctypes structures but
without a real RDP connection (this module has no other unit tests:
everything else needs a real server, per docs/embedded-rdp-status.md).
Native calls that need a live connection (gdi_resize, SendMonitorLayout)
are stubbed via _apply_resize rather than exercised for real.

Skipped entirely on a machine without libfreerdp3 installed — this
module raises OSError at import time in that case (see its _load()),
which must never break the rest of the suite.
"""

import ctypes

import pytest

try:
    import it_toolbox.core.rdp.freerdp_client as freerdp_client
except OSError:
    pytest.skip("libfreerdp3 not installed", allow_module_level=True)


def _make_channel_connected_event(name: bytes):
    disp_ctx = freerdp_client.DispClientContext()
    name_buf = ctypes.create_string_buffer(name)
    event_args = freerdp_client.ChannelConnectedEventArgs()
    event_args.name = ctypes.cast(name_buf, ctypes.POINTER(ctypes.c_char))
    event_args.pInterface = ctypes.cast(ctypes.pointer(disp_ctx), ctypes.c_void_p)
    # Keep the buffers alive for the caller's use of event_args.
    return event_args, name_buf, disp_ctx


def test_resize_before_disp_channel_binds_is_deferred_not_dropped():
    session = freerdp_client.FreeRdpSession()
    session._context = object()  # "connected" — only checked for is-None-ness
    applied = []
    session._apply_resize = lambda w, h: applied.append((w, h))

    session.request_resize(1920, 1080)

    assert session._pending_resize == (1920, 1080)
    assert applied == []


def test_pending_resize_is_replayed_once_disp_channel_binds():
    session = freerdp_client.FreeRdpSession()
    session._context = object()
    applied = []
    session._apply_resize = lambda w, h: applied.append((w, h))
    session.request_resize(1920, 1080)  # deferred, per the test above

    event_args, _buf, _ctx = _make_channel_connected_event(b"disp")
    session._on_channel_connected(None, ctypes.pointer(event_args))

    assert session._pending_resize is None
    assert applied == [(1920, 1080)]
    assert session.display._context is not None


def test_channel_connected_with_no_pending_resize_does_not_apply_anything():
    session = freerdp_client.FreeRdpSession()
    applied = []
    session._apply_resize = lambda w, h: applied.append((w, h))

    event_args, _buf, _ctx = _make_channel_connected_event(b"disp")
    session._on_channel_connected(None, ctypes.pointer(event_args))

    assert applied == []


def test_resize_after_disp_channel_bound_applies_immediately():
    session = freerdp_client.FreeRdpSession()
    session._context = object()
    session.display._context = object()  # already bound
    applied = []
    session._apply_resize = lambda w, h: applied.append((w, h))

    session.request_resize(1024, 768)

    assert session._pending_resize is None
    assert applied == [(1024, 768)]


def test_resize_with_no_connection_is_a_noop():
    session = freerdp_client.FreeRdpSession()  # _context is None: never connected

    session.request_resize(1024, 768)

    assert session._pending_resize is None


def test_unrelated_channel_connecting_does_not_bind_display_or_apply_resize():
    session = freerdp_client.FreeRdpSession()
    session._context = object()
    applied = []
    session._apply_resize = lambda w, h: applied.append((w, h))
    session.request_resize(1920, 1080)  # deferred

    event_args, _buf, _ctx = _make_channel_connected_event(b"cliprdr")
    session._on_channel_connected(None, ctypes.pointer(event_args))

    assert session.display._context is None
    assert session._pending_resize == (1920, 1080)  # still pending
    assert applied == []
