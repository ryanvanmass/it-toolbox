"""Installing the user's SSH public key on a server they just logged in
to with a password -- what `ssh-copy-id` does, for the Cockpit managers
(see widgets/remote_helper_widget.offer_key_install).

The key comes from the server's own SSH key setting when it has a .pub
next to it, else ~/.ssh/id_ed25519 / id_rsa (the same keys paramiko's
look_for_keys tries on the next connect). With no key at all, a new
ed25519 key is written to ~/.ssh/id_ed25519 with the `cryptography`
package paramiko already depends on, so no ssh-keygen (and no console
window on Windows) is needed.

The install and verify calls are plain blocking calls, meant to run in a
background thread via core.async_utils.run_in_background.
"""

from __future__ import annotations

import getpass
import os
import platform
import socket
from dataclasses import dataclass
from pathlib import Path

import paramiko
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from it_toolbox.core import settings
from it_toolbox.core.ftp_client import UnknownHostKeyError, _RaiseUnknownHostKey

# Run as the login user, not root: it's that user's authorized_keys. The
# key arrives on stdin so it never shows up in the remote process list.
# A file that doesn't end in a newline gets one first, or the appended key
# would be glued onto the last line; restorecon fixes the SELinux label of
# a freshly created ~/.ssh, without which sshd ignores it.
INSTALL_SCRIPT = (
    'umask 077; mkdir -p "$HOME/.ssh" || exit 1; f="$HOME/.ssh/authorized_keys"; '
    'IFS= read -r key || [ -n "$key" ] || exit 1; touch "$f" || exit 1; '
    'if ! grep -qxF "$key" "$f"; then '
    '[ -s "$f" ] && [ -n "$(tail -c 1 "$f")" ] && echo >> "$f"; '
    'printf "%s\\n" "$key" >> "$f" || exit 1; fi; '
    'chmod 700 "$HOME/.ssh"; chmod 600 "$f"; '
    'command -v restorecon >/dev/null 2>&1 && restorecon -R "$HOME/.ssh" >/dev/null 2>&1; '
    "exit 0"
)

PUBLIC_KEY_PREFIXES = ("ssh-", "ecdsa-", "sk-")


class KeyInstallError(Exception):
    """str(exc) is meant to be shown to the user as is."""


@dataclass
class LocalKey:
    """The private key to log in with and its public half; `public_key`
    is None for a key that doesn't exist yet and will be generated."""

    private_path: Path
    public_key: str | None

    @property
    def exists(self) -> bool:
        return self.public_key is not None


def _public_key_for(private_path: Path) -> str | None:
    pub = private_path.parent / f"{private_path.name}.pub"
    if not pub.is_file():
        return None
    try:
        text = pub.read_text().strip()
    except OSError:
        return None
    return text if text.startswith(PUBLIC_KEY_PREFIXES) else None


def find_local_key(key_path: str | None = None) -> LocalKey:
    """The key to install: the server's configured key (if it has a .pub),
    else ~/.ssh/id_ed25519 / id_rsa, else a not-yet-generated
    ~/.ssh/id_ed25519."""
    candidates = []
    if key_path:
        path = Path(key_path).expanduser()
        candidates.append(path.with_suffix("") if path.suffix == ".pub" else path)
    default = settings.default_ssh_key_path()
    if default is not None:
        candidates.append(default)
    for candidate in candidates:
        public_key = _public_key_for(candidate)
        if public_key is not None:
            return LocalKey(candidate, public_key)
    return LocalKey(Path.home() / ".ssh" / "id_ed25519", None)


def _key_comment() -> str:
    try:
        user = getpass.getuser()
    except Exception:
        user = "user"
    return f"{user}@{platform.node() or socket.gethostname() or 'it-toolbox'}"


def generate_key(private_path: Path) -> LocalKey:
    """Writes a new passphrase-less ed25519 keypair in OpenSSH format,
    the same as `ssh-keygen -t ed25519 -N ''` would. Refuses to overwrite
    an existing file."""
    public_path = private_path.parent / f"{private_path.name}.pub"
    if private_path.exists() or public_path.exists():
        raise KeyInstallError(f"{private_path} already exists; not overwriting it.")
    key = Ed25519PrivateKey.generate()
    private_bytes = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.OpenSSH,
        serialization.NoEncryption(),
    )
    public_key = (
        key.public_key().public_bytes(serialization.Encoding.OpenSSH, serialization.PublicFormat.OpenSSH).decode()
        + f" {_key_comment()}"
    )
    try:
        private_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        # O_EXCL + 0600 from the start: the private key is never readable
        # by anyone else, even briefly.
        fd = os.open(private_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as handle:
            handle.write(private_bytes)
        public_path.write_text(public_key + "\n")
    except OSError as exc:
        raise KeyInstallError(f"Couldn't write {private_path}: {exc}") from exc
    return LocalKey(private_path, public_key)


def _client() -> paramiko.SSHClient:
    client = paramiko.SSHClient()
    client.load_system_host_keys()
    try:
        client.load_host_keys(str(Path.home() / ".ssh" / "known_hosts"))
    except OSError:
        pass
    # The password login that led here already confirmed the host key.
    client.set_missing_host_key_policy(_RaiseUnknownHostKey())
    return client


def install_public_key(host: str, port: int, username: str, password: str, public_key: str) -> None:
    """Logs in with the password and appends public_key to the user's
    ~/.ssh/authorized_keys, unless it's already there."""
    public_key = public_key.strip()
    if "\n" in public_key or not public_key.startswith(PUBLIC_KEY_PREFIXES):
        raise KeyInstallError("That doesn't look like an OpenSSH public key.")
    client = _client()
    try:
        client.connect(
            host, port=port, username=username, password=password,
            allow_agent=False, look_for_keys=False, timeout=15,
        )
        stdin, stdout, stderr = client.exec_command(INSTALL_SCRIPT, timeout=60)
        stdin.write(public_key.encode() + b"\n")
        stdin.channel.shutdown_write()
        err = stderr.read().decode(errors="replace").strip()
        status = stdout.channel.recv_exit_status()
    except UnknownHostKeyError as exc:
        raise KeyInstallError(f"{host}'s host key isn't trusted yet.") from exc
    except (paramiko.SSHException, OSError) as exc:
        raise KeyInstallError(f"Couldn't install the key on {host}: {exc}") from exc
    finally:
        client.close()
    if status != 0:
        raise KeyInstallError(f"Couldn't update ~/.ssh/authorized_keys on {host}: {err or f'exit status {status}'}")


def key_login_works(host: str, port: int, username: str, private_path: Path, passphrase: str | None = None) -> bool:
    """True when the key alone (no password, no agent) logs in."""
    client = _client()
    try:
        client.connect(
            host, port=port, username=username, key_filename=str(private_path), passphrase=passphrase,
            allow_agent=False, look_for_keys=False, timeout=15,
        )
        return True
    except (paramiko.SSHException, OSError):
        return False
    finally:
        client.close()
