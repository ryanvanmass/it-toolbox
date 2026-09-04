"""Qt-free SPICE client session, built on SpiceClientGLib (PyGObject).

Verified against the real SpiceClientGLib GObject-Introspection typelib on
this machine (`GIRepository`), not just recalled from memory or docs —
see docs/qemu-spice-status.md for how that verification was done and why
this shape works for SPICE (no GTK widget needed at all; DisplayChannel's
raw-pixel signals are a closer match to QImage-painting than FreeRDP's GDI
hook was).

Milestones 3-4 scope: connect()/disconnect() and single-monitor frame
capture. Input (InputsChannel.motion/button_press/key_press) lands in a
later milestone — see docs/qemu-spice-status.md's milestone list.

One binding quirk worth flagging: both `SpiceClientGLib.Session` and
`SpiceClientGLib.Channel` (and so every Channel subclass — MainChannel,
DisplayChannel, InputsChannel, ...) have *native* `connect()`/
`disconnect()` methods (spice_session_connect/_disconnect,
spice_channel_connect/_disconnect in the C API), which shadow
GObject.Object's own `.connect()` used for signal hookup. Confirmed
empirically, not just inferred from the docs — `channel.connect("channel-
event", cb)` raises `TypeError: takes exactly 1 argument (3 given)`.
Signals on either kind of object are therefore always wired via
`GObject.Object.connect(obj, signal, callback)` explicitly, never
`obj.connect(signal, callback)`.

A second binding quirk, found while building frame capture:
`DisplayChannel.display_channel_get_primary()` (the "pull" API for the
current primary surface) comes back with garbage/misaligned fields
through this binding — confirmed by calling it and getting nonsense
values (e.g. `stride=-1`, `format` in the trillions) even though the VM
under test was rendering fine. The `display-primary-create` *signal*'s
arguments are reliable, though (verified pixel-perfect against `virsh
screenshot`'s independent capture — see below), so this module caches
format/width/height/stride/the raw pixel pointer from that signal instead
of ever calling the pull API.

Pixel format, empirically confirmed rather than assumed: SPICE surface
format 32 (32 bits/pixel) is byte order B,G,R,X in memory — i.e. the same
layout as `QImage.Format_RGB32` and FreeRDP's `PIXEL_FORMAT_BGRX32` here.
Confirmed by capturing a live frame from a real VM via this module and
comparing it pixel-by-pixel against `virsh screenshot`'s independent
libvirt-side capture at the same instant: 0 differing pixels across a
sparse full-frame sample, on a frame with real (non-black) content.
`imgdata` itself arrives as a plain Python int (a raw pointer address,
not a buffer/bytes object) — read via `ctypes.string_at`, same as
FreeRDP's GDI buffer.
"""

import ctypes
import threading
from collections.abc import Callable

import gi

gi.require_version("SpiceClientGLib", "2.0")
from gi.repository import GObject, SpiceClientGLib  # noqa: E402 - gi.require_version must run first

# This module only drives a single embedded display, matching RdpWidget's
# one-screen-per-tab shape — a VM with multiple monitors gets additional
# DisplayChannels with higher channel-ids, which are ignored here.
PRIMARY_DISPLAY_CHANNEL_ID = 0

# SPICE wire-protocol constants (spice/enums.h's SpiceMouseButton /
# SpiceMouseButtonMask) — verified against the upstream spice-protocol
# header (github.com/flexVDI/spice-protocol, a mirror of the canonical
# freedesktop.org source), not recalled from memory: button identifiers
# are LEFT=1/MIDDLE=2/RIGHT=3/UP=4(wheel up)/DOWN=5(wheel down); the
# button_state bitmask uses LEFT=1<<0/MIDDLE=1<<1/RIGHT=1<<2 (no mask
# bits exist for the wheel "buttons" — they're momentary, not held).
_MOUSE_BUTTON = {"left": 1, "middle": 2, "right": 3}
_MOUSE_BUTTON_MASK = {"left": 1 << 0, "middle": 1 << 1, "right": 1 << 2}
_WHEEL_UP_BUTTON = 4
_WHEEL_DOWN_BUTTON = 5

_ERROR_EVENTS = {
    SpiceClientGLib.ChannelEvent.ERROR_CONNECT,
    SpiceClientGLib.ChannelEvent.ERROR_TLS,
    SpiceClientGLib.ChannelEvent.ERROR_LINK,
    SpiceClientGLib.ChannelEvent.ERROR_AUTH,
    SpiceClientGLib.ChannelEvent.ERROR_IO,
}


class SpiceError(Exception):
    pass


class SpiceSession:
    """One SPICE client session for the lifetime of a single VM connection.

    Signal callbacks from spice-glib fire on whatever thread runs the
    GLib main loop driving this session — this class itself creates no
    thread or main loop; that's SpiceSessionWorker's job (mirroring
    FreeRdpSession/RdpSessionWorker's split), so connect()/disconnect()
    here assume a GLib.MainLoop is already running elsewhere.
    """

    def __init__(self) -> None:
        self._session = SpiceClientGLib.Session()
        self._main_channel: SpiceClientGLib.MainChannel | None = None
        self._display_channel: SpiceClientGLib.DisplayChannel | None = None
        self._inputs_channel: SpiceClientGLib.InputsChannel | None = None
        self._connected = threading.Event()
        self._error: SpiceError | None = None
        # Bitmask of currently-held mouse buttons — SPICE's position()/
        # motion() calls always carry the full current button state
        # alongside the coordinates, not just "which button changed".
        self._button_mask: int = 0

        # Cached from the display-primary-create signal — see module
        # docstring for why this is read from the signal, not pulled via
        # display_channel_get_primary().
        self._format: int | None = None
        self._width: int = 0
        self._height: int = 0
        self._stride: int = 0
        self._imgdata: int | None = None

        # Called (from the GLib main loop thread) whenever a new frame is
        # available to read via get_frame() — on the initial full-frame
        # primary-create, and on every subsequent display-invalidate.
        self.on_frame: Callable[[], None] | None = None
        # Callback counterparts to connect()'s blocking wait, for a caller
        # (SpiceSessionWorker) that runs the GLib.MainLoop itself and so
        # can't block-and-wait on this same thread without deadlocking —
        # see start_connecting()'s docstring.
        self.on_connected: Callable[[], None] | None = None
        self.on_error: Callable[[SpiceError], None] | None = None
        self.on_disconnected: Callable[[], None] | None = None

        GObject.Object.connect(self._session, "channel-new", self._on_channel_new)
        GObject.Object.connect(self._session, "disconnected", self._on_session_disconnected)

    def start_connecting(self, host: str, port: int, password: str = "") -> None:
        """Kick off connecting and return immediately — spice_session_connect()
        itself is non-blocking; it just starts the process, whose outcome
        arrives later as signals (delivered to on_connected/on_error, and
        to connect()'s own internal wait). Use this (not connect()) from a
        thread that itself will drive the GLib main loop, e.g.
        SpiceSessionWorker — calling the blocking connect() there would
        deadlock, since the signals it waits on only ever get dispatched
        while a loop is actually running.
        """
        self._session.set_property("host", host)
        self._session.set_property("port", str(port))
        if password:
            self._session.set_property("password", password)

        if not self._session.connect():
            raise SpiceError(f"spice_session_connect failed for {host}:{port}")

    def connect(self, host: str, port: int, password: str = "", timeout: float = 15) -> None:
        """Start connecting and block until the main channel comes up (or
        the connection fails, or `timeout` elapses). Requires a
        GLib.MainLoop already running on a *different* thread (true of
        every CLI/smoke-test entry point below) — see start_connecting()'s
        docstring for why this can't be called from the loop's own thread.
        """
        self.start_connecting(host, port, password)

        if not self._connected.wait(timeout):
            raise SpiceError(f"Timed out connecting to {host}:{port}")
        if self._error is not None:
            raise self._error

    def disconnect(self) -> None:
        self._session.disconnect()

    def get_frame(self) -> tuple[bytes, int, int, int]:
        """The current primary display surface as (pixels, width, height,
        stride), pixels in BGRX32 byte order (see module docstring).
        Raises SpiceError if no primary surface has been created yet.
        """
        if self._imgdata is None:
            raise SpiceError("no primary display surface yet")
        size = self._stride * self._height
        pixels = ctypes.string_at(self._imgdata, size)
        return pixels, self._width, self._height, self._stride

    # --- input: absolute position + scancode-based keyboard -------------
    #
    # Unlike FreeRDP, SPICE's InputsChannel has no separate "unicode text"
    # fast path — every key goes through key_press/key_release's PC/AT
    # scancode. A character with no entry in core/rdp/scancodes.SCANCODES
    # (reused as-is here — same PC/AT Set 1 table, not RDP-specific) has
    # no way to reach the guest through this channel at all; that's a real
    # SPICE limitation, not an oversight here.

    def send_mouse_move(self, x: int, y: int) -> None:
        if self._inputs_channel is None:
            return
        self._inputs_channel.position(x, y, PRIMARY_DISPLAY_CHANNEL_ID, self._button_mask)

    def send_mouse_button(self, button: str, down: bool) -> None:
        if self._inputs_channel is None:
            return
        spice_button = _MOUSE_BUTTON.get(button)
        mask_bit = _MOUSE_BUTTON_MASK.get(button)
        if spice_button is None or mask_bit is None:
            return
        self._button_mask = (self._button_mask | mask_bit) if down else (self._button_mask & ~mask_bit)
        if down:
            self._inputs_channel.button_press(spice_button, self._button_mask)
        else:
            self._inputs_channel.button_release(spice_button, self._button_mask)

    def send_mouse_wheel(self, steps: int) -> None:
        """`steps` > 0 scrolls up, < 0 scrolls down — each step is sent as
        an immediate press+release, matching the wheel's momentary nature
        (there's no wheel bit in the button_state mask to hold)."""
        if self._inputs_channel is None or steps == 0:
            return
        button = _WHEEL_UP_BUTTON if steps > 0 else _WHEEL_DOWN_BUTTON
        for _ in range(abs(steps)):
            self._inputs_channel.button_press(button, self._button_mask)
            self._inputs_channel.button_release(button, self._button_mask)

    def send_key_scancode(self, code: int, extended: bool, down: bool) -> None:
        if self._inputs_channel is None:
            return
        scancode = (code | 0x100) if extended else code
        if down:
            self._inputs_channel.key_press(scancode)
        else:
            self._inputs_channel.key_release(scancode)

    def _on_channel_new(
        self, session: SpiceClientGLib.Session, channel: SpiceClientGLib.Channel
    ) -> None:
        if isinstance(channel, SpiceClientGLib.MainChannel):
            self._main_channel = channel
            GObject.Object.connect(channel, "channel-event", self._on_main_channel_event)
        elif isinstance(channel, SpiceClientGLib.DisplayChannel):
            if channel.get_property("channel-id") != PRIMARY_DISPLAY_CHANNEL_ID:
                return
            self._display_channel = channel
            GObject.Object.connect(channel, "display-primary-create", self._on_primary_create)
            GObject.Object.connect(channel, "display-primary-destroy", self._on_primary_destroy)
            GObject.Object.connect(channel, "display-invalidate", self._on_invalidate)
            channel.connect()
        elif isinstance(channel, SpiceClientGLib.InputsChannel):
            self._inputs_channel = channel
            channel.connect()

    def _on_main_channel_event(self, channel: SpiceClientGLib.Channel, event: int) -> None:
        if event == SpiceClientGLib.ChannelEvent.OPENED:
            self._connected.set()
            if self.on_connected is not None:
                self.on_connected()
        elif event in _ERROR_EVENTS:
            error = SpiceError(f"SPICE main channel error: {SpiceClientGLib.ChannelEvent(event).value_name}")
            self._error = error
            self._connected.set()
            if self.on_error is not None:
                self.on_error(error)

    def _on_session_disconnected(self, session: SpiceClientGLib.Session) -> None:
        self._connected.set()
        if self.on_disconnected is not None:
            self.on_disconnected()

    def _on_primary_create(
        self,
        channel: SpiceClientGLib.DisplayChannel,
        fmt: int,
        width: int,
        height: int,
        stride: int,
        shmid: int,
        imgdata: int,
    ) -> None:
        self._format = fmt
        self._width = width
        self._height = height
        self._stride = stride
        self._imgdata = imgdata
        if self.on_frame is not None:
            self.on_frame()

    def _on_primary_destroy(self, channel: SpiceClientGLib.DisplayChannel) -> None:
        # Stop pointing at a buffer the server may free/reuse once the
        # primary surface goes away (e.g. on a guest resolution change) —
        # the same stale-pointer hazard class as freerdp_client.py's
        # disconnect()/DisplayChannel issue.
        self._imgdata = None

    def _on_invalidate(
        self, channel: SpiceClientGLib.DisplayChannel, x: int, y: int, width: int, height: int
    ) -> None:
        if self.on_frame is not None:
            self.on_frame()


# -- CLI (smoke-test entry point, no Qt involved) --------------------------


def connect_and_disconnect(host: str, port: int, password: str = "") -> None:
    """Milestone 3 smoke test: connect, confirm the main channel opens,
    disconnect. Must be run with a GLib.MainLoop pumping on another
    thread — see _cli_main() below.
    """
    session = SpiceSession()
    session.connect(host, port, password)
    session.disconnect()


def _write_ppm(path: str, pixels: bytes, width: int, height: int, stride: int) -> None:
    """Writes a raw PPM (P6), converting BGRX to RGB row by row — same
    convention as freerdp_client._write_ppm (kept as its own small copy
    here rather than a shared import, matching that module's own
    self-contained CLI-helper style).
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
    password: str,
    output_path: str,
    timeout_sec: float = 15.0,
    settle_sec: float = 2.0,
) -> None:
    """Milestone 4 smoke test: connect, wait until the primary display
    surface has stopped changing for `settle_sec` (mirrors
    freerdp_client.capture_one_frame's reasoning — confirmed the hard way
    here too: the very first primary-create can still be a stale/blank
    surface, e.g. before the guest's display has actually woken up, and
    capturing on that first signal alone grabbed a black frame while the
    real screen already had content), save it as a PPM, disconnect.
    """
    import time

    session = SpiceSession()
    last_frame_at = 0.0

    def _on_frame() -> None:
        nonlocal last_frame_at
        last_frame_at = time.monotonic()

    session.on_frame = _on_frame
    session.connect(host, port, password)
    try:
        deadline = time.monotonic() + timeout_sec
        while time.monotonic() < deadline:
            if last_frame_at and time.monotonic() - last_frame_at > settle_sec:
                break
            time.sleep(0.1)
        if not last_frame_at:
            raise SpiceError(f"no frame painted within {timeout_sec}s")
        pixels, width, height, stride = session.get_frame()
        _write_ppm(output_path, pixels, width, height, stride)
        print(f"Wrote {width}x{height} frame to {output_path}")
    finally:
        session.disconnect()


def _cli_main() -> None:
    import argparse
    import threading as _threading

    from gi.repository import GLib

    parser = argparse.ArgumentParser(
        description=(
            "Connect to a real SPICE server via SpiceClientGLib. By default "
            "performs the Milestone-3 connect/disconnect smoke test; with "
            "--capture-frame, performs the Milestone-4 frame-capture smoke test."
        )
    )
    parser.add_argument("--host", required=True)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--password", default="")
    parser.add_argument(
        "--capture-frame",
        metavar="PATH",
        help="Also capture and save the primary display surface as a PPM image to this path.",
    )
    args = parser.parse_args()

    loop = GLib.MainLoop()
    loop_thread = _threading.Thread(target=loop.run, daemon=True)
    loop_thread.start()
    try:
        if args.capture_frame:
            capture_one_frame(args.host, args.port, args.password, args.capture_frame)
        else:
            connect_and_disconnect(args.host, args.port, args.password)
            print("Connected and disconnected successfully.")
    finally:
        loop.quit()
        loop_thread.join(timeout=5)


if __name__ == "__main__":
    _cli_main()
