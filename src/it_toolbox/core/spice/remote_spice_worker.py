"""Windows' SPICE worker: the same signal/method surface as
SpiceSessionWorker, but the session itself runs inside the Linux tools
WSL distro (it_toolbox.wsl_helper's "spice" service, which drives the
very same SpiceSessionRunner), with frames and input crossing over
core/wsl/transport.py. SpiceWidget can't tell the difference.

No gi import anywhere on this path -- that's the point: the Windows
build has no PyGObject.

Unlike SpiceSessionWorker it takes the libvirt URI and the VM's SPICE
port on that host, not a ready-to-use local port: the helper opens the
qemu+ssh:// tunnel itself, from inside the distro (see spice_service.py
for why).
"""

import threading

from it_toolbox.core import linux_backend
from it_toolbox.core.spice import remote_protocol as proto
from it_toolbox.core.spice.spice_signals import SpiceSessionSignals
from it_toolbox.core.wsl import transport
from it_toolbox.core.wsl.helper_process import HelperProcess


class RemoteSpiceWorker:
    def __init__(
        self,
        uri: str,
        spice_port: int,
        password: str = "",
        backend: linux_backend.LinuxBackend | None = None,
    ) -> None:
        self.signals = SpiceSessionSignals()
        self._helper = HelperProcess(
            "spice", {"uri": uri, "port": spice_port, "password": password}, backend=backend
        )
        self._conn: transport.Connection | None = None
        self._thread: threading.Thread | None = None
        self._stopping = threading.Event()
        self._disconnected_emitted = False

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 5) -> None:
        """Safe to call from any thread, any number of times."""
        self._stopping.set()
        self._helper.stop()
        if self._thread is not None and self._thread is not threading.current_thread():
            self._thread.join(timeout=timeout)

    # --- input — safe to call from the Qt thread ------------------------
    #
    # Not coalesced here: a send is one small sendall on a local socket,
    # and the helper's SpiceSessionRunner already coalesces mouse moves
    # before they reach its GLib loop.

    def _send(self, msg_type: int, payload: bytes) -> None:
        conn = self._conn
        if conn is None or self._stopping.is_set():
            return
        try:
            conn.send(msg_type, payload)
        except OSError:
            pass  # the reader thread reports the disconnect

    def send_mouse_move(self, x: int, y: int) -> None:
        self._send(proto.MOUSE_MOVE, proto.POINT.pack(x, y))

    def send_mouse_button(self, button: str, down: bool) -> None:
        self._send(proto.MOUSE_BUTTON, proto.BUTTON.pack(down) + button.encode())

    def send_mouse_wheel(self, steps: int) -> None:
        self._send(proto.MOUSE_WHEEL, proto.WHEEL.pack(steps))

    def send_key_scancode(self, code: int, extended: bool, down: bool) -> None:
        self._send(proto.KEY_SCANCODE, proto.KEY.pack(code, extended, down))

    def send_resize(self, width: int, height: int) -> None:
        self._send(proto.RESIZE, proto.SIZE.pack(width, height))

    # --- reader thread ----------------------------------------------------

    def _run(self) -> None:
        try:
            self._conn = self._helper.start()
        except (transport.TransportError, OSError) as exc:
            if not self._stopping.is_set():
                self.signals.error.emit(str(exc))
            self._emit_disconnected()
            return
        try:
            self._pump()
        finally:
            self._emit_disconnected()

    def _pump(self) -> None:
        while True:
            try:
                msg_type, payload = self._conn.recv()
            except (EOFError, OSError, transport.TransportError):
                if not self._stopping.is_set():
                    detail = self._helper.stderr_tail()
                    if detail:
                        self.signals.error.emit(f"The Linux tools helper stopped: {detail.splitlines()[-1]}")
                return
            if msg_type == proto.FRAME:
                band_top, band_height, canvas_width, canvas_height, stride = proto.FRAME_HEADER.unpack_from(payload)
                pixels = payload[proto.FRAME_HEADER.size :]
                self.signals.frame_ready.emit(pixels, band_top, band_height, canvas_width, canvas_height, stride)
            elif msg_type == proto.CONNECTED:
                self.signals.connected.emit()
            elif msg_type == proto.AGENT_CONNECTED:
                self.signals.agent_connected.emit()
            elif msg_type == transport.MSG_ERROR:
                self.signals.error.emit(payload.decode(errors="replace"))
            elif msg_type == proto.DISCONNECTED:
                return

    def _emit_disconnected(self) -> None:
        if not self._disconnected_emitted:
            self._disconnected_emitted = True
            self.signals.disconnected.emit()
