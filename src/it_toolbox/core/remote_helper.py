"""An SSH connection that runs a Cockpit module's privileged JSON helper
on a remote server, as root -- the plumbing behind the General Tools
managers for the user's Cockpit modules (see core/hosting_manager.py).

A Cockpit page calls its helper with
`cockpit.spawn([HELPER, subcommand], {superuser: "require"}).input(json)`
and gets one JSON object back, `{"error": ...}` on failure. This does the
same over paramiko: log in (key/agent first, a password only when asked
for), work out how to become root (already root, passwordless sudo, or
sudo with a password), then pipe the arguments to the helper through
`sudo`. Both UIs therefore read and write the same state on the server.

Every method that talks to the server is a plain blocking call, meant to
be invoked from a background thread via core.async_utils.run_in_background.
"""

from __future__ import annotations

import json
import shlex
from dataclasses import dataclass
from pathlib import Path

import paramiko

from it_toolbox.core.ftp_client import UnknownHostKeyError, _RaiseUnknownHostKey

SSH_PORT = 22
# Long enough for any ordinary helper call; slow ones (package installs,
# app downloads) pass their own timeout to call().
DEFAULT_TIMEOUT = 300


class RemoteHelperError(Exception):
    """Any connection, privilege, or helper-reported failure -- str(exc)
    is meant to be shown to the user as is."""


class LoginPasswordRequired(RemoteHelperError):
    """Key/agent login was refused (or a password was wrong); the caller
    prompts for the SSH password and reconnects with it set."""


class KeyPassphraseRequired(RemoteHelperError):
    """The configured SSH key is passphrase-protected."""


class SudoPasswordRequired(RemoteHelperError):
    """The SSH user needs a password for sudo; `incorrect` is True when
    one was given and sudo rejected it. The caller prompts and reconnects
    with sudo_password set."""

    def __init__(self, incorrect: bool = False) -> None:
        self.incorrect = incorrect
        super().__init__(
            "The sudo password was incorrect." if incorrect else "sudo needs a password on this server."
        )


@dataclass
class RemoteServer:
    """A saved server in a manager's sidebar. The SSH login is key/agent
    based by default (paramiko tries key_path, then the agent and default
    keys); a password is only ever prompted for, never stored."""

    name: str
    host: str
    username: str
    port: int = SSH_PORT
    key_path: str | None = None

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "host": self.host,
            "port": self.port,
            "username": self.username,
            "key_path": self.key_path,
        }

    @classmethod
    def from_dict(cls, data: dict) -> RemoteServer | None:
        try:
            return cls(
                name=str(data["name"]),
                host=str(data["host"]),
                username=str(data["username"]),
                port=int(data.get("port") or SSH_PORT),
                key_path=data.get("key_path") or None,
            )
        except (KeyError, TypeError, ValueError):
            return None

    @property
    def target(self) -> str:
        return f"{self.username}@{self.host}:{self.port}"


class RemoteHelperConnection:
    """One SSH connection to a server. paramiko's Transport multiplexes
    channels, so several background calls can run at once.

    Subclasses set HELPER_PATHS (tried in order; the first executable one
    is used) and MODULE_NAME (for messages)."""

    HELPER_PATHS: tuple[str, ...] = ()
    MODULE_NAME = "Cockpit module"

    def __init__(
        self,
        server: RemoteServer,
        password: str | None = None,
        key_passphrase: str | None = None,
        sudo_password: str | None = None,
    ) -> None:
        self.server = server
        self._password = password or None
        self._key_passphrase = key_passphrase or None
        self._sudo_password = sudo_password or None
        self._client: paramiko.SSHClient | None = None
        self._privilege: list[str] = []
        self._sends_sudo_password = False
        self.helper_path: str | None = None

    # -- Connection -------------------------------------------------------

    def connect(self) -> None:
        """Connects, works out how to get root, and finds the helper.
        Raises UnknownHostKeyError for a never-seen host key,
        SudoPasswordRequired when sudo needs a (correct) password, and
        RemoteHelperError for everything else."""
        client = paramiko.SSHClient()
        client.load_system_host_keys()
        try:
            client.load_host_keys(str(Path.home() / ".ssh" / "known_hosts"))
        except OSError:
            pass
        client.set_missing_host_key_policy(_RaiseUnknownHostKey())
        server = self.server
        try:
            client.connect(
                server.host,
                port=server.port,
                username=server.username,
                password=self._password,
                key_filename=server.key_path,
                passphrase=self._key_passphrase,
                allow_agent=True,
                look_for_keys=True,
                timeout=15,
            )
        except UnknownHostKeyError:
            raise
        except paramiko.PasswordRequiredException as exc:
            raise KeyPassphraseRequired(f"{server.key_path or 'Your SSH key'} needs its passphrase.") from exc
        except paramiko.AuthenticationException as exc:
            raise LoginPasswordRequired(
                f"Authentication failed for {server.username}@{server.host}."
            ) from exc
        except paramiko.BadHostKeyException as exc:
            raise RemoteHelperError(
                f"{server.host}'s host key doesn't match the one in your known_hosts file — "
                "refusing to connect. If the server was reinstalled, remove its old entry "
                "from ~/.ssh/known_hosts and try again."
            ) from exc
        except (paramiko.SSHException, OSError) as exc:
            raise RemoteHelperError(f"Couldn't connect to {server.host}:{server.port} — {exc}") from exc
        self._client = client
        try:
            self._detect_privilege()
            self.helper_path = self._find_helper()
        except Exception:
            self.close()
            raise

    def trust_host_key(self, hostname: str, key: paramiko.PKey) -> None:
        """Same as SftpSession.trust_host_key: appends to the real
        ~/.ssh/known_hosts after the user confirms the fingerprint."""
        known_hosts = Path.home() / ".ssh" / "known_hosts"
        host_keys = paramiko.HostKeys()
        try:
            host_keys.load(str(known_hosts))
        except OSError:
            pass
        host_keys.add(hostname, key.get_name(), key)
        known_hosts.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        host_keys.save(str(known_hosts))

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None

    @property
    def connected(self) -> bool:
        transport = self._client.get_transport() if self._client is not None else None
        return transport is not None and transport.is_active()

    def _detect_privilege(self) -> None:
        if self.server.username == "root":
            self._privilege = []
            return
        status, _, _ = self._exec_raw("sudo -n true")
        if status == 0:
            self._privilege = ["sudo", "-n", "--"]
            return
        if self._sudo_password is None:
            raise SudoPasswordRequired()
        # -k ignores any cached sudo ticket, so sudo always reads the
        # password line from stdin -- with a cached ticket it wouldn't,
        # and the password would flow on into the command's own stdin.
        self._privilege = ["sudo", "-k", "-S", "-p", "", "--"]
        self._sends_sudo_password = True
        status, _, _ = self.run(["true"])
        if status != 0:
            raise SudoPasswordRequired(incorrect=True)

    def _find_helper(self) -> str | None:
        for path in self.HELPER_PATHS:
            status, _, _ = self.run(["test", "-x", path])
            if status == 0:
                return path
        return None

    # -- Running commands --------------------------------------------------

    def _exec_raw(self, command: str, stdin: bytes = b"", timeout: float = DEFAULT_TIMEOUT) -> tuple[int, str, str]:
        if self._client is None:
            raise RemoteHelperError("Not connected.")
        try:
            chan_stdin, stdout, stderr = self._client.exec_command(command, timeout=timeout)
            if stdin:
                chan_stdin.write(stdin)
            chan_stdin.channel.shutdown_write()
            out = stdout.read().decode(errors="replace")
            err = stderr.read().decode(errors="replace")
            status = stdout.channel.recv_exit_status()
        except TimeoutError as exc:
            raise RemoteHelperError(f"{self.server.host} didn't answer in time.") from exc
        except (paramiko.SSHException, OSError) as exc:
            raise RemoteHelperError(f"Lost the connection to {self.server.host}: {exc}") from exc
        return status, out, err

    def command_line(self, argv: list[str]) -> str:
        """The full remote shell command for running argv as root."""
        return shlex.join([*self._privilege, *argv])

    def _stdin_prefix(self) -> bytes:
        if self._sends_sudo_password:
            return (self._sudo_password or "").encode() + b"\n"
        return b""

    def run(self, argv: list[str], stdin: bytes = b"", timeout: float = DEFAULT_TIMEOUT) -> tuple[int, str, str]:
        return self._exec_raw(self.command_line(argv), self._stdin_prefix() + stdin, timeout)

    def call(self, subcommand: str, args: dict | None = None, timeout: float = DEFAULT_TIMEOUT) -> dict:
        """Runs one helper subcommand, the same contract as a Cockpit
        page's callHelper(): {"error": ...} becomes a RemoteHelperError."""
        if self.helper_path is None:
            raise RemoteHelperError(f"The {self.MODULE_NAME} helper isn't installed on this server.")
        status, out, err = self.run([self.helper_path, subcommand], json.dumps(args or {}).encode(), timeout)
        try:
            result = json.loads(out)
        except ValueError:
            detail = (err or out).strip() or f"exit status {status}"
            raise RemoteHelperError(f"Could not run {subcommand}: {detail}") from None
        if not isinstance(result, dict):
            raise RemoteHelperError(f"Could not run {subcommand}: unexpected output")
        if "error" in result:
            raise RemoteHelperError(str(result["error"]))
        return result
