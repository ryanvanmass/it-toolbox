"""SSH local-port-forward tunnel to reach a libvirt-managed VM's SPICE port.

libvirt-managed VMs conventionally bind their SPICE server to 127.0.0.1 on
the host — a secure default. `virsh`/`virt-viewer` reach it because *they*
set up an SSH tunnel transparently as part of the `qemu+ssh://` connection
dance. Since this app's embedded SPICE client connects to the SPICE port
directly (bypassing virt-viewer entirely, see docs/qemu-spice-status.md),
it has to open that tunnel itself.

Subprocess-based rather than asyncio (unlike core/iap_tunnel.py) — same
"spawn ssh, respect the user's existing keys/agent" pattern
session_launcher.py already uses for interactive SSH sessions, just held
open as a background tunnel instead of an interactive session. Closer in
spirit to core/tunnel_session.py's BackgroundTunnel than to the IAP tunnel,
but simpler: ssh itself does the byte-pumping, so there's no event loop to
own here, only a subprocess to supervise.
"""

import socket
import subprocess
import time
from urllib.parse import urlsplit

READY_POLL_INTERVAL_SEC = 0.1


class QemuTunnelError(Exception):
    pass


def _parse_ssh_target(uri: str) -> tuple[str, int | None]:
    """Extract an ssh(1) "[user@]host" target and optional port from a
    qemu+ssh:// libvirt connection URI, e.g. "qemu+ssh://alice@lab-host:2222/system".
    """
    parsed = urlsplit(uri)
    if parsed.scheme != "qemu+ssh":
        raise QemuTunnelError(f"not an SSH-transport libvirt URI: {uri!r}")
    if not parsed.hostname:
        raise QemuTunnelError(f"no host in libvirt URI: {uri!r}")

    target = f"{parsed.username}@{parsed.hostname}" if parsed.username else parsed.hostname
    return target, parsed.port


def _free_local_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _can_connect(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.2):
            return True
    except OSError:
        return False


class QemuTunnel:
    """One SSH local-port-forward, spawned as a subprocess, exposing a VM's
    remote SPICE port on a local port for the lifetime of a connection.
    """

    def __init__(self, uri: str, remote_port: int) -> None:
        self._target, self._ssh_port = _parse_ssh_target(uri)
        self._remote_port = remote_port
        self._process: subprocess.Popen[str] | None = None
        self._local_port: int | None = None

    @property
    def port(self) -> int | None:
        """The bound local port, or None before start() has completed."""
        return self._local_port

    def start(self, ready_timeout: float = 10) -> int:
        """Spawn the ssh tunnel and block until the local port is accepting
        connections (or ready_timeout elapses). Returns the local port.

        Call from a background (worker-pool) thread, never the Qt main
        thread — this blocks on tunnel startup.
        """
        self._local_port = _free_local_port()
        cmd = [
            "ssh",
            "-N",  # no remote command — this is a pure port-forward
            "-o", "ExitOnForwardFailure=yes",
            "-o", "BatchMode=yes",  # never block waiting for a password prompt
            "-L", f"{self._local_port}:127.0.0.1:{self._remote_port}",
        ]
        if self._ssh_port:
            cmd += ["-p", str(self._ssh_port)]
        cmd.append(self._target)

        try:
            self._process = subprocess.Popen(
                cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True
            )
        except FileNotFoundError as e:
            raise QemuTunnelError("ssh not found — install an OpenSSH client") from e

        deadline = time.monotonic() + ready_timeout
        while time.monotonic() < deadline:
            exit_code = self._process.poll()
            if exit_code is not None:
                stderr = self._process.stderr.read() if self._process.stderr else ""
                raise QemuTunnelError(f"ssh tunnel to {self._target} exited: {stderr.strip()}")
            if _can_connect(self._local_port):
                return self._local_port
            time.sleep(READY_POLL_INTERVAL_SEC)

        self.stop()
        raise QemuTunnelError(f"timed out waiting for ssh tunnel to {self._target} to come up")

    def stop(self, timeout: float = 5) -> None:
        """Tear down the tunnel. Safe to call from any thread, more than
        once, or after a failed start().
        """
        if self._process is None:
            return
        self._process.terminate()
        try:
            self._process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            self._process.kill()
            self._process.wait()
        self._process = None
