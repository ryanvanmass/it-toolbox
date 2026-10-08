"""Remote management of a ProFTPD server set up by the user's
cockpit-proftpd Cockpit module, for the General Tools ProFTPD Manager.

Everything goes over one SSH connection (paramiko) per manager tab. All
user/group/virtual-directory/setup work is done by running the module's
own privileged helper (`cockpit-proftpd-helper <subcommand>`, JSON on
stdin, one JSON object on stdout) exactly the way the Cockpit page's
cockpit.spawn() does, so both UIs read and write the same SQLite
database and generated config and can be used side by side. When the
Cockpit module isn't installed on the server, a bundled copy of the same
helper (resources/proftpd/) can be installed instead.

The one thing the Cockpit module doesn't have is the live traffic view:
an extra ProFTPD ExtendedLog (its own conf.d file, never touching the
module's managed one) records every FTP/SFTP command and its response,
and the manager tails it, plus `ftpwho -o json` for the session list.

Every method that talks to the server is a plain blocking call, meant to
be invoked from a background thread via core.async_utils.run_in_background.
"""

from __future__ import annotations

import base64
import json
import posixpath
import shlex
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import paramiko

from it_toolbox.core.ftp_client import UnknownHostKeyError, _RaiseUnknownHostKey

SSH_PORT = 22

# Where the cockpit-proftpd RPM installs its helper (see its
# packaging/cockpit-proftpd.spec.in and src/helper.ts's HELPER_PATH).
# The container image (TrueNAS build) uses the same path.
COCKPIT_HELPER_PATH = "/usr/libexec/cockpit-proftpd/cockpit-proftpd-helper"
# Where install_bundled_helper() puts our own copy -- deliberately not the
# RPM's path, so a later cockpit-proftpd install never collides with it.
# Persistent, not a temp dir: setup() writes a systemd timer whose
# ExecStart points at the helper's own path.
BUNDLED_HELPER_DIR = "/usr/local/libexec/it-toolbox-proftpd"
BUNDLED_HELPER_PATH = f"{BUNDLED_HELPER_DIR}/cockpit-proftpd-helper"
BUNDLED_HELPER_FILES = ("cockpit-proftpd-helper", "schema.sql", "proftpd-cockpit.conf.tmpl")
BUNDLED_HELPER_SOURCE = Path(__file__).resolve().parents[1] / "resources" / "proftpd"

LIVE_LOG_CONF_PATH = "/etc/proftpd/conf.d/it-toolbox-live-log.conf"
LIVE_LOG_PATH = "/var/log/proftpd/it-toolbox-live.log"
LIVE_LOG_FORMAT_NAME = "it_toolbox_live"
# Tab-separated: none of the fields can contain a tab in practice, and the
# two free-text ones (response text, then the command line) come last, so
# a stray tab in a filename only ever lands inside the command field.
# Confirmed against ProFTPD 1.3.8: quotes inside %r/%S are not escaped,
# which rules out a quoted format; %P is the session's pid; the CONNECT and
# EXIT classes log one line with an empty command at session start/end.
LIVE_LOG_FORMAT = "\t".join(
    ["%{epoch}", "%P", "%a", "%{protocol}", "%u", "%s", "%b", "%S", "%r"]
)
LIVE_LOG_CONF = (
    "# Written by IT Toolbox's ProFTPD Manager for its live traffic view.\n"
    "# Safe to delete (the manager's \"Turn Off Live Logging\" does that).\n"
    f'LogFormat {LIVE_LOG_FORMAT_NAME} "{LIVE_LOG_FORMAT}"\n'
    "<Global>\n"
    f"  ExtendedLog {LIVE_LOG_PATH} ALL,CONNECT,EXIT {LIVE_LOG_FORMAT_NAME}\n"
    "</Global>\n"
)
LIVE_LOG_LOGROTATE_PATH = "/etc/logrotate.d/it-toolbox-proftpd-live"
LIVE_LOG_LOGROTATE = (
    f"{LIVE_LOG_PATH} {{\n"
    "    weekly\n    rotate 4\n    compress\n    missingok\n    notifempty\n"
    "    copytruncate\n}\n"
)
LIVE_LOG_HISTORY_LINES = 200

# Re-reads the config without dropping connected sessions. systemd hosts
# reload the unit (falling back to HUP-ing its main process if the unit
# has no ExecReload); the container image has no systemd, and its
# proftpd re-reads its config on SIGHUP (same as the helper's setup()).
_RELOAD_PROFTPD = (
    "if command -v systemctl >/dev/null 2>&1 && systemctl is-active -q proftpd; then "
    "systemctl reload proftpd 2>/dev/null || systemctl kill -s HUP --kill-whom=main proftpd; "
    "else pkill -HUP -x proftpd; fi"
)

_ENABLE_LIVE_LOG_SCRIPT = f"""
set -e
cat > {LIVE_LOG_CONF_PATH}
mkdir -p {posixpath.dirname(LIVE_LOG_PATH)}
if ! out=$(proftpd --configtest 2>&1); then
    rm -f {LIVE_LOG_CONF_PATH}
    echo "$out" >&2
    exit 1
fi
if [ -d /etc/logrotate.d ] && ! grep -qs 'proftpd/\\*\\.log\\|{LIVE_LOG_PATH}' /etc/logrotate.d/*; then
    printf '%s' {shlex.quote(LIVE_LOG_LOGROTATE)} > {LIVE_LOG_LOGROTATE_PATH}
fi
{_RELOAD_PROFTPD}
"""

_DISABLE_LIVE_LOG_SCRIPT = f"""
rm -f {LIVE_LOG_CONF_PATH} {LIVE_LOG_LOGROTATE_PATH}
{_RELOAD_PROFTPD}
"""

# Runs `tail -F` until the SSH channel's stdin closes (when the viewer
# stops), then kills it -- without a pty, closing the channel alone would
# leave tail running on the server until it next failed to write.
_FOLLOW_SCRIPT = (
    f"tail -n {LIVE_LOG_HISTORY_LINES} -F {LIVE_LOG_PATH} 2>/dev/null & pid=$!; "
    "cat >/dev/null; kill $pid 2>/dev/null"
)

# Only ever signals an actual proftpd session process, so a stale or
# mistyped pid can't take down something else on the server.
_KICK_SCRIPT = '[ "$(cat /proc/"$1"/comm 2>/dev/null)" = proftpd ] && kill "$1"'

PROTOCOL_LABELS = {"both": "FTP and SFTP", "ftp": "FTP only", "sftp": "SFTP only"}
RATE_LIMIT_LABELS = {
    "unlimited": "Unlimited",
    "medium": "Medium (1 MB/s)",
    "slow": "Slow (128 KB/s)",
}


class ProftpdError(Exception):
    """Any connection, privilege, or helper-reported failure -- str(exc)
    is meant to be shown to the user as is."""


class LoginPasswordRequired(ProftpdError):
    """Key/agent login was refused (or a password was wrong); the caller
    prompts for the SSH password and reconnects with it set."""


class KeyPassphraseRequired(ProftpdError):
    """The configured SSH key is passphrase-protected."""


class SudoPasswordRequired(ProftpdError):
    """The SSH user needs a password for sudo; `incorrect` is True when
    one was given and sudo rejected it. The caller prompts and reconnects
    with sudo_password set."""

    def __init__(self, incorrect: bool = False) -> None:
        self.incorrect = incorrect
        super().__init__(
            "The sudo password was incorrect." if incorrect else "sudo needs a password on this server."
        )


@dataclass
class ProftpdServer:
    """A saved server in the ProFTPD Manager's sidebar. The SSH login is
    key/agent-based by default (paramiko tries key_path, then the agent
    and default keys); a password is only ever prompted for, never stored.
    docker_container is set for the cockpit-proftpd container build
    (TrueNAS app): the helper, ftpwho and the live log are then reached
    with `docker exec` inside that container.
    """

    name: str
    host: str
    username: str
    port: int = SSH_PORT
    key_path: str | None = None
    docker_container: str | None = None

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "host": self.host,
            "port": self.port,
            "username": self.username,
            "key_path": self.key_path,
            "docker_container": self.docker_container,
        }

    @classmethod
    def from_dict(cls, data: dict) -> ProftpdServer | None:
        try:
            return cls(
                name=str(data["name"]),
                host=str(data["host"]),
                username=str(data["username"]),
                port=int(data.get("port") or SSH_PORT),
                key_path=data.get("key_path") or None,
                docker_container=data.get("docker_container") or None,
            )
        except (KeyError, TypeError, ValueError):
            return None


@dataclass(frozen=True)
class LiveEvent:
    """One line of the live traffic log."""

    timestamp: int
    pid: int
    address: str
    protocol: str
    user: str | None
    code: str | None
    bytes: int | None
    response: str | None
    command: str

    @property
    def is_session_event(self) -> bool:
        """True for the CONNECT/EXIT lines logged at a session's start and
        end, which have no command."""
        return not self.command


def _dash_none(value: str) -> str | None:
    return None if value in ("", "-") else value


def parse_live_line(line: str) -> LiveEvent | None:
    """Parses one LIVE_LOG_FORMAT line; None for anything else (a partial
    line, or another format's line after someone edits the config)."""
    parts = line.rstrip("\r\n").split("\t", 8)
    if len(parts) != 9:
        return None
    epoch, pid, address, protocol, user, code, num_bytes, response, command = parts
    try:
        timestamp = int(epoch)
        pid_value = int(pid)
    except ValueError:
        return None
    bytes_value = _dash_none(num_bytes)
    try:
        bytes_value = int(bytes_value) if bytes_value is not None else None
    except ValueError:
        bytes_value = None
    return LiveEvent(
        timestamp=timestamp,
        pid=pid_value,
        address=address,
        protocol=protocol,
        user=_dash_none(user),
        code=_dash_none(code),
        bytes=bytes_value,
        response=_dash_none(response),
        command=command if command != "-" else "",
    )


@dataclass(frozen=True)
class LiveSession:
    """One connected client, from `ftpwho -o json`."""

    pid: int
    address: str
    user: str | None
    protocol: str
    location: str | None
    connected_since: float | None
    idle: bool
    command: str | None = None
    extra: dict = field(default_factory=dict, compare=False)


def parse_ftpwho_json(text: str) -> list[LiveSession]:
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise ProftpdError(f"Couldn't read the session list from ftpwho: {exc}") from exc
    sessions = []
    for conn in data.get("connections") or []:
        if not isinstance(conn, dict) or "pid" not in conn:
            continue
        since_ms = conn.get("connected_since_ms")
        command = conn.get("command")
        if command and conn.get("command_args"):
            command = f"{command} {conn['command_args']}"
        sessions.append(
            LiveSession(
                pid=int(conn["pid"]),
                address=str(conn.get("remote_address") or conn.get("remote_name") or ""),
                user=conn.get("user") or None,
                protocol=str(conn.get("protocol") or ""),
                location=conn.get("location") or None,
                connected_since=since_ms / 1000 if isinstance(since_ms, (int, float)) else None,
                idle=bool(conn.get("idling")),
                command=command or None,
                extra=conn,
            )
        )
    return sessions


class ProftpdConnection:
    """One SSH connection to a ProFTPD server. paramiko's Transport
    multiplexes channels, so several background calls (a user list
    refresh, an ftpwho poll, the live log tail) can run at once.
    """

    def __init__(
        self,
        server: ProftpdServer,
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
        """Connects, works out how to get root (none needed for root,
        passwordless sudo, or sudo with sudo_password), and finds the
        helper. Raises UnknownHostKeyError for a never-seen host key,
        SudoPasswordRequired when sudo needs a (correct) password, and
        ProftpdError for everything else."""
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
            raise ProftpdError(
                f"{server.host}'s host key doesn't match the one in your known_hosts file — "
                "refusing to connect. If the server was reinstalled, remove its old entry "
                "from ~/.ssh/known_hosts and try again."
            ) from exc
        except (paramiko.SSHException, OSError) as exc:
            raise ProftpdError(f"Couldn't connect to {server.host}:{server.port} — {exc}") from exc
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
        for path in (COCKPIT_HELPER_PATH, BUNDLED_HELPER_PATH):
            status, _, _ = self.run(["test", "-x", path])
            if status == 0:
                return path
        return None

    # -- Running commands --------------------------------------------------

    def _exec_raw(self, command: str, stdin: bytes = b"") -> tuple[int, str, str]:
        if self._client is None:
            raise ProftpdError("Not connected.")
        try:
            chan_stdin, stdout, stderr = self._client.exec_command(command, timeout=300)
            if stdin:
                chan_stdin.write(stdin)
            chan_stdin.channel.shutdown_write()
            out = stdout.read().decode(errors="replace")
            err = stderr.read().decode(errors="replace")
            status = stdout.channel.recv_exit_status()
        except (paramiko.SSHException, OSError) as exc:
            raise ProftpdError(f"Lost the connection to {self.server.host}: {exc}") from exc
        return status, out, err

    def command_line(self, argv: list[str], in_container: bool = True) -> str:
        """The full remote shell command for running argv as root --
        inside the configured Docker container when there is one."""
        full = list(self._privilege)
        if in_container and self.server.docker_container:
            full += ["docker", "exec", "-i", self.server.docker_container]
        return shlex.join(full + argv)

    def _stdin_prefix(self) -> bytes:
        if self._sends_sudo_password:
            return (self._sudo_password or "").encode() + b"\n"
        return b""

    def run(self, argv: list[str], stdin: bytes = b"", in_container: bool = True) -> tuple[int, str, str]:
        return self._exec_raw(self.command_line(argv, in_container), self._stdin_prefix() + stdin)

    def run_script(self, script: str, stdin: bytes = b"") -> tuple[int, str, str]:
        return self.run(["sh", "-c", script], stdin)

    def call(self, subcommand: str, args: dict | None = None) -> dict:
        """Runs one helper subcommand, the same contract as the Cockpit
        page's callHelper(): {"error": ...} becomes a ProftpdError."""
        if self.helper_path is None:
            raise ProftpdError("The cockpit-proftpd helper isn't installed on this server.")
        status, out, err = self.run(
            [self.helper_path, subcommand], json.dumps(args or {}).encode()
        )
        try:
            result = json.loads(out)
        except ValueError:
            detail = (err or out).strip() or f"exit status {status}"
            raise ProftpdError(f"Could not run {subcommand}: {detail}") from None
        if not isinstance(result, dict):
            raise ProftpdError(f"Could not run {subcommand}: unexpected output")
        if "error" in result:
            raise ProftpdError(str(result["error"]))
        return result

    def install_bundled_helper(self) -> str:
        """Copies resources/proftpd/ to BUNDLED_HELPER_DIR on the server
        (for a server without the Cockpit module). Not supported for a
        container, whose image always ships the helper."""
        if self.server.docker_container:
            raise ProftpdError("The cockpit-proftpd container image already includes the helper.")
        script = (
            f"set -e; mkdir -p {BUNDLED_HELPER_DIR}; "
            f'cd {BUNDLED_HELPER_DIR}; python3 -c "import sys, json, base64, pathlib\n'
            'for name, data in json.load(sys.stdin).items():\n'
            '    pathlib.Path(name).write_bytes(base64.b64decode(data))"; '
            f"chmod 755 cockpit-proftpd-helper; chmod 644 schema.sql proftpd-cockpit.conf.tmpl"
        )
        payload = {
            name: base64.b64encode((BUNDLED_HELPER_SOURCE / name).read_bytes()).decode()
            for name in BUNDLED_HELPER_FILES
        }
        status, _, err = self.run_script(script, json.dumps(payload).encode())
        if status != 0:
            raise ProftpdError(f"Couldn't install the helper: {err.strip() or f'exit status {status}'}")
        self.helper_path = BUNDLED_HELPER_PATH
        return self.helper_path

    # -- Helper subcommands (same set as the Cockpit page's helper.ts) -----

    def status(self) -> dict:
        return self.call("status")

    def setup(self, require_tls: bool = True) -> dict:
        return self.call("setup", {"require_tls": require_tls})

    def open_firewall(self) -> list[str]:
        return self.call("open-firewall").get("opened", [])

    def list_users(self) -> list[dict]:
        return self.call("list-users").get("users", [])

    def list_transfers(self) -> list[dict]:
        return self.call("list-transfers").get("transfers", [])

    def create_user(self, username: str, password: str, options: dict) -> dict:
        return self.call("create-user", {"username": username, "password": password, **options})

    def update_user(self, username: str, password: str | None, options: dict) -> dict:
        args = {"username": username, **options}
        if password:
            args["password"] = password
        return self.call("update-user", args)

    def set_permissions(self, username: str) -> dict:
        return self.call("set-permissions", {"username": username})

    def delete_user(self, username: str) -> dict:
        return self.call("delete-user", {"username": username})

    def list_virtual_mounts(self, username: str | None = None) -> list[dict]:
        return self.call("list-virtual-mounts", {"username": username}).get("mounts", [])

    def add_virtual_mount(self, username: str, virtual_name: str, real_path: str, readonly: bool) -> dict:
        return self.call(
            "add-virtual-mount",
            {"username": username, "virtual_name": virtual_name, "real_path": real_path, "readonly": readonly},
        )

    def remove_virtual_mount(self, username: str, virtual_name: str) -> dict:
        return self.call("remove-virtual-mount", {"username": username, "virtual_name": virtual_name})

    def list_groups(self) -> list[dict]:
        return self.call("list-groups").get("groups", [])

    def create_group(self, groupname: str) -> dict:
        return self.call("create-group", {"groupname": groupname})

    def delete_group(self, groupname: str) -> dict:
        return self.call("delete-group", {"groupname": groupname})

    def add_group_member(self, groupname: str, username: str) -> dict:
        return self.call("add-group-member", {"groupname": groupname, "username": username})

    def remove_group_member(self, groupname: str, username: str) -> dict:
        return self.call("remove-group-member", {"groupname": groupname, "username": username})

    def add_group_mount(self, groupname: str, virtual_name: str, real_path: str, readonly: bool) -> dict:
        return self.call(
            "add-group-mount",
            {"groupname": groupname, "virtual_name": virtual_name, "real_path": real_path, "readonly": readonly},
        )

    def remove_group_mount(self, groupname: str, virtual_name: str) -> dict:
        return self.call("remove-group-mount", {"groupname": groupname, "virtual_name": virtual_name})

    # -- Live traffic -------------------------------------------------------

    def live_log_enabled(self) -> bool:
        status, _, _ = self.run(["test", "-f", LIVE_LOG_CONF_PATH])
        return status == 0

    def enable_live_log(self) -> None:
        status, out, err = self.run_script(_ENABLE_LIVE_LOG_SCRIPT, LIVE_LOG_CONF.encode())
        if status != 0:
            detail = (err or out).strip() or f"exit status {status}"
            raise ProftpdError(f"Couldn't turn on live logging: {detail}")

    def disable_live_log(self) -> None:
        status, out, err = self.run_script(_DISABLE_LIVE_LOG_SCRIPT)
        if status != 0:
            detail = (err or out).strip() or f"exit status {status}"
            raise ProftpdError(f"Couldn't turn off live logging: {detail}")

    def list_sessions(self) -> list[LiveSession]:
        status, out, err = self.run(["ftpwho", "-o", "json"])
        if status != 0 and not out.strip():
            raise ProftpdError(f"ftpwho failed: {(err or '').strip() or f'exit status {status}'}")
        return parse_ftpwho_json(out)

    def kick_session(self, pid: int) -> None:
        status, _, err = self.run(["sh", "-c", _KICK_SCRIPT, "sh", str(int(pid))])
        if status != 0:
            raise ProftpdError(
                f"Couldn't disconnect session {pid} — it may have already ended. {err.strip()}".strip()
            )

    def follow_live_log(
        self, on_lines: Callable[[list[str]], None], should_stop: Callable[[], bool]
    ) -> None:
        """Blocks, calling on_lines(lines) with the last
        LIVE_LOG_HISTORY_LINES lines and then every new batch, until
        should_stop() returns True or the connection drops."""
        if self._client is None:
            raise ProftpdError("Not connected.")
        transport = self._client.get_transport()
        if transport is None:
            raise ProftpdError("Not connected.")
        try:
            channel = transport.open_session()
            channel.settimeout(0.5)
            channel.exec_command(self.command_line(["sh", "-c", _FOLLOW_SCRIPT]))
            prefix = self._stdin_prefix()
            if prefix:
                channel.sendall(prefix)
        except (paramiko.SSHException, OSError) as exc:
            raise ProftpdError(f"Couldn't start the live log: {exc}") from exc
        buffer = b""
        try:
            while not should_stop():
                try:
                    chunk = channel.recv(65536)
                except TimeoutError:
                    continue
                except OSError as exc:
                    raise ProftpdError(f"Lost the connection to {self.server.host}: {exc}") from exc
                if not chunk:
                    break
                buffer += chunk
                *lines, buffer = buffer.split(b"\n")
                if lines:
                    on_lines([line.decode(errors="replace") for line in lines])
        finally:
            try:
                channel.shutdown_write()
                channel.close()
            except (paramiko.SSHException, OSError):
                pass
