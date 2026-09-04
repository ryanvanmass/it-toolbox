"""Qt-free SPICE client session, built on SpiceClientGLib (PyGObject).

Verified against the real SpiceClientGLib GObject-Introspection typelib on
this machine (`GIRepository`), not just recalled from memory or docs —
see docs/qemu-spice-status.md for how that verification was done and why
this shape works for SPICE (no GTK widget needed at all; DisplayChannel's
raw-pixel signals are a closer match to QImage-painting than FreeRDP's GDI
hook was).

Milestone 3 scope: connect()/disconnect() only. Frame capture
(display-primary-create/display-invalidate) and input
(InputsChannel.motion/button_press/key_press) land in later milestones —
see docs/qemu-spice-status.md's milestone list.

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
"""

import threading

import gi

gi.require_version("SpiceClientGLib", "2.0")
from gi.repository import GObject, SpiceClientGLib  # noqa: E402 - gi.require_version must run first

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
        self._connected = threading.Event()
        self._error: SpiceError | None = None

        GObject.Object.connect(self._session, "channel-new", self._on_channel_new)
        GObject.Object.connect(self._session, "disconnected", self._on_disconnected)

    def connect(self, host: str, port: int, password: str = "", timeout: float = 15) -> None:
        """Start connecting and block until the main channel comes up (or
        the connection fails, or `timeout` elapses).
        """
        self._session.set_property("host", host)
        self._session.set_property("port", str(port))
        if password:
            self._session.set_property("password", password)

        if not self._session.connect():
            raise SpiceError(f"spice_session_connect failed for {host}:{port}")

        if not self._connected.wait(timeout):
            raise SpiceError(f"Timed out connecting to {host}:{port}")
        if self._error is not None:
            raise self._error

    def disconnect(self) -> None:
        self._session.disconnect()

    def _on_channel_new(
        self, session: SpiceClientGLib.Session, channel: SpiceClientGLib.Channel
    ) -> None:
        if isinstance(channel, SpiceClientGLib.MainChannel):
            self._main_channel = channel
            GObject.Object.connect(channel, "channel-event", self._on_main_channel_event)

    def _on_main_channel_event(self, channel: SpiceClientGLib.Channel, event: int) -> None:
        if event == SpiceClientGLib.ChannelEvent.OPENED:
            self._connected.set()
        elif event in _ERROR_EVENTS:
            self._error = SpiceError(f"SPICE main channel error: {SpiceClientGLib.ChannelEvent(event).value_name}")
            self._connected.set()

    def _on_disconnected(self, session: SpiceClientGLib.Session) -> None:
        self._connected.set()


# -- CLI (smoke-test entry point, no Qt involved) --------------------------


def connect_and_disconnect(host: str, port: int, password: str = "") -> None:
    """Milestone 3 smoke test: connect, confirm the main channel opens,
    disconnect. Must be run with a GLib.MainLoop pumping on another
    thread — see _cli_main() below.
    """
    session = SpiceSession()
    session.connect(host, port, password)
    session.disconnect()


def _cli_main() -> None:
    import argparse
    import threading as _threading

    from gi.repository import GLib

    parser = argparse.ArgumentParser(description="Connect to and disconnect from a SPICE server.")
    parser.add_argument("--host", required=True)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--password", default="")
    args = parser.parse_args()

    loop = GLib.MainLoop()
    loop_thread = _threading.Thread(target=loop.run, daemon=True)
    loop_thread.start()
    try:
        connect_and_disconnect(args.host, args.port, args.password)
        print("Connected and disconnected successfully.")
    finally:
        loop.quit()
        loop_thread.join(timeout=5)


if __name__ == "__main__":
    _cli_main()
