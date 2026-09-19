"""Generic SSH local-port-forward tunnel — spawns `ssh -N -L`, waits for
the local port to accept connections, and tears it down cleanly.

Extracted from qemu_tunnel.py's original QemuTunnel once a second,
non-libvirt caller needed the exact same spawn/wait/teardown mechanics —
a manual RDP/SSH connection routed through a user-configured SSH gateway
(see modules/connection_manager/models.py's ManualConnection.gateway_*
fields), mirroring mRemoteNG's SSH-tunneling feature. That caller can't
reuse QemuTunnel directly: it always forwards to 127.0.0.1 on the SSH
target (right for libvirt, since SPICE binds to localhost on the same
host virsh connects to), whereas a gateway gets used to reach some
*other* host on its own network (the classic bastion pattern — SSH into
host A, RDP to host B) just as often as it reaches itself. So this class
takes the destination host/port as plain arguments instead of parsing
them out of a libvirt connection URI; qemu_tunnel.QemuTunnel is now a
thin subclass that does that parsing and fixes the destination to
127.0.0.1.

Subprocess-based rather than asyncio (unlike core/iap_tunnel.py) — same
"spawn ssh, respect the user's existing keys/agent" pattern
session_launcher.py already uses for interactive SSH sessions, just held
open as a background tunnel instead of an interactive session. Closer in
spirit to core/tunnel_session.py's BackgroundTunnel than to the IAP
tunnel, but simpler: ssh itself does the byte-pumping, so there's no
event loop to own here, only a subprocess to supervise.
"""

import socket
import subprocess
import time

READY_POLL_INTERVAL_SEC = 0.1


class SshTunnelError(Exception):
    pass


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


class SshTunnel:
    """One SSH local-port-forward, spawned as a subprocess, exposing
    `dest_host:dest_port` — as reachable *from* `target`, not necessarily
    `target` itself — on a local port for the lifetime of a connection.
    """

    def __init__(
        self, target: str, dest_host: str, dest_port: int, *, ssh_port: int | None = None
    ) -> None:
        self._target = target
        self._ssh_port = ssh_port
        self._dest_host = dest_host
        self._dest_port = dest_port
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
            "-L", f"{self._local_port}:{self._dest_host}:{self._dest_port}",
        ]
        if self._ssh_port:
            cmd += ["-p", str(self._ssh_port)]
        cmd.append(self._target)

        try:
            self._process = subprocess.Popen(
                cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True
            )
        except FileNotFoundError as e:
            raise SshTunnelError("ssh not found — install an OpenSSH client") from e

        deadline = time.monotonic() + ready_timeout
        while time.monotonic() < deadline:
            exit_code = self._process.poll()
            if exit_code is not None:
                stderr = self._process.stderr.read() if self._process.stderr else ""
                raise SshTunnelError(f"ssh tunnel to {self._target} exited: {stderr.strip()}")
            if _can_connect(self._local_port):
                return self._local_port
            time.sleep(READY_POLL_INTERVAL_SEC)

        self.stop()
        raise SshTunnelError(f"timed out waiting for ssh tunnel to {self._target} to come up")

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
