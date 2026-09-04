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


def test_apply_resize_also_requests_a_full_refresh(monkeypatch):
    """Regression test for the whitespace bug: a resize alone doesn't
    make the server repaint the newly-exposed area, so _apply_resize
    must also ask for a full refresh — see docs/embedded-rdp-status.md's
    "whitespace around the (correctly-sized) image" section for the full
    story (verified for real, at the pixel level, against a live
    server; this test only covers that the call happens, not that
    libfreerdp3 honors it).
    """

    class _FakeGdiContents:
        pass

    class _FakeContext:
        class contents:
            gdi = _FakeGdiContents()

    session = freerdp_client.FreeRdpSession()
    session._context = _FakeContext()
    calls = []
    monkeypatch.setattr(
        freerdp_client._core_lib,
        "gdi_resize",
        lambda gdi, w, h: calls.append(("gdi_resize", w, h)),
    )
    session.display.request_resize = lambda w, h: calls.append(("display", w, h))
    session._request_full_refresh = lambda w, h: calls.append(("refresh", w, h))

    session._apply_resize(1920, 1080)

    assert calls == [
        ("gdi_resize", 1920, 1080),
        ("display", 1920, 1080),
        ("refresh", 1920, 1080),
    ]


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
