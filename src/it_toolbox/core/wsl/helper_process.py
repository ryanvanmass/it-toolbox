"""App side of an it_toolbox.wsl_helper service: spawn it through a
LinuxBackend, read its handshake, connect. See core/wsl/transport.py.

No Qt here -- RemoteSpiceWorker (and Settings' self-test) layer their own
threading/signals on top.
"""

import subprocess
import threading
from pathlib import Path

import it_toolbox
from it_toolbox.core import linux_backend
from it_toolbox.core.wsl import transport

HANDSHAKE_TIMEOUT_SEC = 60  # includes a cold WSL distro boot
_STOP_TIMEOUT_SEC = 5


def package_root() -> str:
    """The directory containing the it_toolbox package -- site-packages in
    an installed app, src/ in a checkout. The helper runs straight from
    here (PYTHONPATH), so it can never drift from the running app."""
    return str(Path(it_toolbox.__file__).resolve().parent.parent)


def helper_argv(backend: linux_backend.LinuxBackend, service: str, python: str = "python3") -> list[str]:
    pythonpath = backend.to_linux_path(package_root())
    # `env` rather than Popen(env=...): on Windows that env would apply to
    # wsl.exe, not to the Linux process it starts.
    return backend.popen_argv(
        ["env", f"PYTHONPATH={pythonpath}", python, "-m", "it_toolbox.wsl_helper", service]
    )


class HelperProcess:
    """One running helper service. start() blocks until connected, so call
    it off the UI thread."""

    def __init__(self, service: str, params: dict, backend: linux_backend.LinuxBackend | None = None) -> None:
        self._service = service
        self._params = params
        self._backend = backend
        self._process: subprocess.Popen | None = None
        self.conn: transport.Connection | None = None
        self._stderr_tail: list[str] = []

    def start(self, handshake_timeout: float = HANDSHAKE_TIMEOUT_SEC) -> transport.Connection:
        backend = self._backend or linux_backend.get_backend()
        if backend is None:
            raise transport.TransportError("Linux tools aren't set up — see Settings > Linux tools (WSL).")
        self._process = subprocess.Popen(
            helper_argv(backend, self._service),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            **backend.popen_kwargs(),
        )
        threading.Thread(target=self._drain_stderr, daemon=True).start()

        line = self._read_handshake_line(handshake_timeout)
        port, token = transport.parse_handshake_line(line)
        try:
            self.conn = transport.connect(port, token, self._params)
        except OSError as e:
            self.stop()
            raise transport.TransportError(f"Couldn't connect to the Linux tools helper on port {port}: {e}") from e
        return self.conn

    def _read_handshake_line(self, timeout: float) -> str:
        result: dict[str, bytes] = {}
        reader = threading.Thread(target=lambda: result.update(line=self._process.stdout.readline()), daemon=True)
        reader.start()
        reader.join(timeout)
        line = result.get("line", b"").decode(errors="replace")
        if not line.strip():
            self.stop()
            detail = self.stderr_tail() or "no output"
            raise transport.TransportError(f"The Linux tools helper didn't start: {detail}")
        return line

    def _drain_stderr(self) -> None:
        # Keeps the pipe from filling (and blocking the helper), and keeps
        # the last few lines for error messages.
        for raw in self._process.stderr:
            self._stderr_tail = ([*self._stderr_tail, raw.decode(errors="replace").rstrip()])[-20:]

    def stderr_tail(self) -> str:
        return "\n".join(line for line in self._stderr_tail if line)

    def stop(self) -> None:
        if self.conn is not None:
            try:
                self.conn.send(transport.MSG_STOP)
            except OSError:
                pass
            self.conn.close()
        process = self._process
        if process is None:
            return
        try:
            process.stdin.close()  # the helper exits on stdin EOF too
        except OSError:
            pass
        try:
            process.wait(timeout=_STOP_TIMEOUT_SEC)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
