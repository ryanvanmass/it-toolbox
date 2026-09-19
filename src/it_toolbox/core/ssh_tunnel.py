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

Password auth (`password=` below) is a real, if less secure, opt-in for
a gateway that doesn't have the app's key -- confirmed by a real gateway
that rejected key auth outright ("Permission denied (publickey,password)")
with no way to add a key to it from here. See _build_askpass_env's own
docstring for how a background subprocess with no controlling terminal
authenticates with a password at all.
"""

import os
import socket
import stat
import subprocess
import sys
import tempfile
import time

READY_POLL_INTERVAL_SEC = 0.1

def _popen_kwargs() -> dict:
    """subprocess.Popen kwargs that keep this background tunnel from
    popping up a real, visible console window on Windows for a console-
    subsystem executable like ssh.exe -- confirmed live: a real report of
    a bare "ssh.exe" window staying open behind the app for the whole
    session, titled after the binary's own path since nothing else sets
    one. A function, not a module-level constant, so this is actually
    testable without needing a real Windows Python interpreter to import
    this module at all -- CREATE_NO_WINDOW only exists as a subprocess
    attribute there, hence getattr with a harmless fallback rather than
    a direct attribute reference.
    """
    if sys.platform == "win32":
        return {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)}
    return {}


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
        self,
        target: str,
        dest_host: str,
        dest_port: int,
        *,
        ssh_port: int | None = None,
        password: str | None = None,
    ) -> None:
        self._target = target
        self._ssh_port = ssh_port
        self._dest_host = dest_host
        self._dest_port = dest_port
        self._password = password
        self._process: subprocess.Popen[str] | None = None
        self._local_port: int | None = None
        self._askpass_path: str | None = None

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
            "-L", f"{self._local_port}:{self._dest_host}:{self._dest_port}",
        ]
        env: dict[str, str] | None
        if self._password:
            # BatchMode (the no-password branch below) suppresses *every*
            # kind of interactive prompt, askpass included -- can't use it
            # here. Without it, host-key trust prompts have nothing to
            # answer them either (askpass only covers passphrase/password
            # prompts) -- accept-new avoids a silent hang the first time
            # this gateway is ever connected to.
            cmd += ["-o", "StrictHostKeyChecking=accept-new"]
            cmd += ["-o", "PreferredAuthentications=password"]
            env = self._build_askpass_env()
        else:
            cmd += ["-o", "BatchMode=yes"]  # never block waiting for a password prompt
            env = None
        if self._ssh_port:
            cmd += ["-p", str(self._ssh_port)]
        cmd.append(self._target)

        try:
            try:
                self._process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                    text=True,
                    env=env,
                    **_popen_kwargs(),
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
        finally:
            # The askpass helper is only ever invoked once, during the
            # initial auth handshake -- by the time start() returns
            # (success or failure) ssh has no further use for it, so
            # there's no reason to leave the password sitting in a temp
            # file for the tunnel's whole lifetime.
            self._cleanup_askpass()

    def _build_askpass_env(self) -> dict[str, str]:
        """Writes a tiny helper program that prints this tunnel's password
        to stdout when invoked -- what SSH_ASKPASS points ssh at -- and
        returns the environment to run ssh with.

        A background subprocess has no controlling terminal for ssh to
        prompt at directly; SSH_ASKPASS_REQUIRE=force (OpenSSH >= 8.4) is
        what makes ssh invoke an askpass helper anyway instead of just
        failing outright. The password itself travels via a separate env
        var the helper reads (not embedded directly in the script file),
        and the file is written owner-only (POSIX chmod 600) -- best
        effort, not a real secret store; see ManualConnection.gateway_password's
        own docstring for the plaintext-at-rest tradeoff this already
        accepts once the password leaves this process at all.

        Verified against a real sshd on Linux only. Windows OpenSSH also
        supports SSH_ASKPASS, so this writes a .cmd wrapper there instead
        of failing outright, but that path hasn't been exercised against
        a real Windows OpenSSH client.
        """
        is_windows = sys.platform == "win32"
        fd, path = tempfile.mkstemp(
            suffix=".cmd" if is_windows else ".sh", prefix="it-toolbox-askpass-"
        )
        script = (
            "@echo off\r\necho %IT_TOOLBOX_SSH_GATEWAY_PASSWORD%\r\n"
            if is_windows
            else '#!/bin/sh\nprintf "%s\\n" "$IT_TOOLBOX_SSH_GATEWAY_PASSWORD"\n'
        )
        with os.fdopen(fd, "w") as f:
            f.write(script)
        if not is_windows:
            os.chmod(path, stat.S_IRWXU)  # owner rwx only

        self._askpass_path = path
        env = dict(os.environ)
        env["IT_TOOLBOX_SSH_GATEWAY_PASSWORD"] = self._password
        env["SSH_ASKPASS"] = path
        env["SSH_ASKPASS_REQUIRE"] = "force"
        return env

    def _cleanup_askpass(self) -> None:
        if self._askpass_path is not None:
            try:
                os.unlink(self._askpass_path)
            except OSError:
                pass
            self._askpass_path = None

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
