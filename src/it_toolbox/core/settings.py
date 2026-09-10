import json
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from platformdirs import user_data_dir
from pyrage import IdentityError, decrypt, encrypt, ssh

APP_NAME = "it-toolbox"


class SecretDecryptionError(Exception):
    """Raised when an encrypted-to-SSH-key secret (currently just the
    JumpCloud API key) can't be decrypted — missing/wrong SSH key, or a
    passphrase-protected key with no passphrase supplied.
    """


def data_dir() -> Path:
    """Cross-platform app-data directory for local storage (DB, cached state)."""
    path = Path(user_data_dir(APP_NAME))
    path.mkdir(parents=True, exist_ok=True)
    return path


def selected_projects_path() -> Path:
    return data_dir() / "selected_projects.json"


def load_selected_project_ids() -> set[str] | None:
    """Which GCP project IDs the user has chosen to show in the tree.

    Returns None if never configured (the caller should prompt the user to
    pick), as distinct from an empty set (explicitly chose to show none).
    """
    path = selected_projects_path()
    if not path.is_file():
        return None
    try:
        return set(json.loads(path.read_text()))
    except (json.JSONDecodeError, OSError):
        return None


def save_selected_project_ids(project_ids: set[str]) -> None:
    selected_projects_path().write_text(json.dumps(sorted(project_ids)))


def qemu_hosts_path() -> Path:
    return data_dir() / "qemu_hosts.json"


def load_qemu_hosts() -> list[dict[str, str]]:
    """Registered QEMU/libvirt hosts, as raw {"name": ..., "uri": ...}
    dicts — kept free of any dependency on
    modules/connection_manager.models.QemuHost (core/ doesn't import from
    modules/ anywhere else); the caller wraps these into QemuHost objects.
    """
    path = qemu_hosts_path()
    if not path.is_file():
        return []
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return []


def save_qemu_hosts(hosts: list[dict[str, str]]) -> None:
    qemu_hosts_path().write_text(json.dumps(hosts))


def manual_connections_path() -> Path:
    return data_dir() / "manual_connections.json"


def load_manual_connections() -> list[dict]:
    """Manually-configured RDP/SSH connections, as raw dicts — kept free
    of any dependency on modules/connection_manager.models.ManualConnection
    (core/ doesn't import from modules/ anywhere else); the caller wraps
    these into ManualConnection objects.
    """
    path = manual_connections_path()
    if not path.is_file():
        return []
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return []


def save_manual_connections(connections: list[dict]) -> None:
    manual_connections_path().write_text(json.dumps(connections))


def default_username_path() -> Path:
    return data_dir() / "default_username.txt"


def load_default_username() -> str | None:
    """The username to connect with when a connection doesn't specify its
    own — the common case being the same account name everywhere.
    """
    path = default_username_path()
    if not path.is_file():
        return None
    return path.read_text().strip() or None


def save_default_username(username: str | None) -> None:
    path = default_username_path()
    if username and username.strip():
        path.write_text(username.strip())
    else:
        path.unlink(missing_ok=True)


def default_rdp_resolution_path() -> Path:
    return data_dir() / "default_rdp_resolution.txt"


def load_default_rdp_resolution() -> tuple[int, int] | None:
    """A fixed resolution to request for embedded RDP sessions instead of
    matching the window size. None means "match window size" (the
    default): every resize sends a matching resolution request to the
    server. A fixed value is requested once at connect and never again —
    RdpWidget stretches the received image to fill the widget regardless
    (see its paintEvent), so a window resize doesn't need a server round
    trip to look right. This exists because that round trip is measurably
    slow over a GCP/IAP-tunneled connection specifically (see
    docs/embedded-rdp-status.md's "Post-resize lag is specific to the
    GCP/IAP-tunnel path" section) — picking a fixed resolution sidesteps
    the round trip entirely rather than trying to make it faster.
    """
    path = default_rdp_resolution_path()
    if not path.is_file():
        return None
    text = path.read_text().strip()
    if not text:
        return None
    try:
        width_str, height_str = text.split("x")
        return int(width_str), int(height_str)
    except ValueError:
        return None


def save_default_rdp_resolution(resolution: tuple[int, int] | None) -> None:
    path = default_rdp_resolution_path()
    if resolution is None:
        path.unlink(missing_ok=True)
    else:
        width, height = resolution
        path.write_text(f"{width}x{height}")


def rclone_path_path() -> Path:
    return data_dir() / "rclone_path.txt"


def load_rclone_path() -> str | None:
    """An explicit path to the rclone executable, for machines where it
    isn't on PATH (e.g. a portable rclone.exe on Windows). None means
    fall back to looking it up on PATH.
    """
    path = rclone_path_path()
    if not path.is_file():
        return None
    return path.read_text().strip() or None


def save_rclone_path(rclone_path: str | None) -> None:
    path = rclone_path_path()
    if rclone_path and rclone_path.strip():
        path.write_text(rclone_path.strip())
    else:
        path.unlink(missing_ok=True)


def jumpcloud_ssh_key_path_path() -> Path:
    return data_dir() / "jumpcloud_ssh_key_path.txt"


def load_jumpcloud_ssh_key_path() -> Path | None:
    """An explicit SSH private key to use for the JumpCloud API key's
    encryption, for users who don't keep one at the default locations
    default_ssh_key_path() checks. None means fall back to that default.
    """
    path = jumpcloud_ssh_key_path_path()
    if not path.is_file():
        return None
    text = path.read_text().strip()
    return Path(text) if text else None


def save_jumpcloud_ssh_key_path(ssh_key_path: str | None) -> None:
    path = jumpcloud_ssh_key_path_path()
    if ssh_key_path and ssh_key_path.strip():
        path.write_text(ssh_key_path.strip())
    else:
        path.unlink(missing_ok=True)


def default_ssh_key_path() -> Path | None:
    """Where ssh/git tooling itself looks first — ed25519 preferred, RSA
    as a fallback for older keypairs.
    """
    for name in ("id_ed25519", "id_rsa"):
        candidate = Path.home() / ".ssh" / name
        if candidate.is_file():
            return candidate
    return None


def resolve_jumpcloud_ssh_key_path() -> Path | None:
    return load_jumpcloud_ssh_key_path() or default_ssh_key_path()


def jumpcloud_api_key_path() -> Path:
    return data_dir() / "jumpcloud_api_key.age"


def _encrypt_secret(secret: str, key_path: Path) -> bytes:
    """age-encrypts `secret` to key_path's matching *public* key
    (<key_path>.pub). Shared by JumpCloud's single global API key and
    GL.iNet's per-host passwords — the encryption itself doesn't care what
    it's protecting or how many of them there are.
    """
    public_key_path = key_path.parent / f"{key_path.name}.pub"
    if not public_key_path.is_file():
        raise SecretDecryptionError(f"No matching public key found at {public_key_path}.")
    recipient = ssh.Recipient.from_str(public_key_path.read_text().strip())
    return encrypt(secret.encode(), [recipient])


def _decrypt_secret(ciphertext: bytes, key_path: Path, passphrase: str | None) -> str:
    identity = _load_ssh_identity(key_path, passphrase)
    try:
        return decrypt(ciphertext, [identity]).decode()
    except Exception as exc:  # noqa: BLE001 - age's own DecryptError, wrong-key case
        raise SecretDecryptionError(
            f"Couldn't decrypt the stored secret with {key_path} — it may have been "
            "encrypted with a different SSH key."
        ) from exc


def _load_ssh_identity(key_path: Path, passphrase: str | None) -> ssh.Identity:
    raw = key_path.read_bytes()
    try:
        return ssh.Identity.from_buffer(raw)
    except IdentityError as exc:
        if passphrase is None:
            raise SecretDecryptionError(
                f"{key_path} appears to be passphrase-protected — pass its passphrase to decrypt "
                "the stored JumpCloud API key."
            ) from exc
        # age itself has no notion of an SSH key's own passphrase — decrypt
        # the OpenSSH private key ourselves first, then hand age the
        # decrypted-in-memory buffer (never written back to disk).
        private_key = serialization.load_ssh_private_key(raw, password=passphrase.encode())
        decrypted = private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.OpenSSH,
            encryption_algorithm=serialization.NoEncryption(),
        )
        return ssh.Identity.from_buffer(decrypted)


def load_jumpcloud_api_key(passphrase: str | None = None) -> str | None:
    """The JumpCloud API key, decrypted with the resolved SSH private key.

    None means never configured. Raises SecretDecryptionError if a key is
    stored but can't be decrypted (missing SSH key, wrong key, or a
    passphrase-protected key with no/wrong passphrase supplied).
    """
    path = jumpcloud_api_key_path()
    if not path.is_file():
        return None
    key_path = resolve_jumpcloud_ssh_key_path()
    if key_path is None or not key_path.is_file():
        raise SecretDecryptionError(
            "No SSH private key found to decrypt the stored JumpCloud API key "
            "(checked ~/.ssh/id_ed25519, ~/.ssh/id_rsa, and any explicitly configured path)."
        )
    return _decrypt_secret(path.read_bytes(), key_path, passphrase)


def save_jumpcloud_api_key(api_key: str | None) -> None:
    """Encrypts api_key to the resolved SSH *public* key and stores it.
    Pass None (or an empty/whitespace string) to remove the stored key.
    """
    path = jumpcloud_api_key_path()
    if not api_key or not api_key.strip():
        path.unlink(missing_ok=True)
        return

    key_path = resolve_jumpcloud_ssh_key_path()
    if key_path is None:
        raise SecretDecryptionError(
            "No SSH key found to encrypt the JumpCloud API key with "
            "(checked ~/.ssh/id_ed25519, ~/.ssh/id_rsa, and any explicitly configured path)."
        )
    path.write_bytes(_encrypt_secret(api_key.strip(), key_path))


def resolve_glinet_ssh_key_path() -> Path | None:
    """GL.iNet host passwords always use the same default SSH key
    resolution as JumpCloud (no separate override setting for v1) — this
    thin wrapper exists purely as an independent monkeypatch seam in tests.
    """
    return default_ssh_key_path()


def encrypt_glinet_password(password: str) -> bytes:
    """Raises SecretDecryptionError if no SSH key (or matching .pub) is found."""
    key_path = resolve_glinet_ssh_key_path()
    if key_path is None:
        raise SecretDecryptionError(
            "No SSH key found to encrypt the GL.iNet host password with "
            "(checked ~/.ssh/id_ed25519, ~/.ssh/id_rsa)."
        )
    return _encrypt_secret(password, key_path)


def decrypt_glinet_password(encrypted: bytes, passphrase: str | None = None) -> str:
    key_path = resolve_glinet_ssh_key_path()
    if key_path is None or not key_path.is_file():
        raise SecretDecryptionError(
            "No SSH private key found to decrypt the stored GL.iNet host password "
            "(checked ~/.ssh/id_ed25519, ~/.ssh/id_rsa)."
        )
    return _decrypt_secret(encrypted, key_path, passphrase)


def glinet_hosts_path() -> Path:
    return data_dir() / "glinet_hosts.json"


def load_glinet_hosts() -> list[dict]:
    """Registered GL.iNet hosts, as raw dicts — kept free of any dependency
    on modules/connection_manager.models.GlinetHost, same reasoning as
    load_qemu_hosts. "password_encrypted" is a base64 str (or None) here,
    never decrypted — decryption only happens right before a dashboard is
    actually opened, so populating the tree never triggers a passphrase
    prompt.
    """
    path = glinet_hosts_path()
    if not path.is_file():
        return []
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return []


def save_glinet_hosts(hosts: list[dict]) -> None:
    """hosts' "password_encrypted" must already be a base64 str or None —
    callers encrypt via encrypt_glinet_password() before calling this."""
    glinet_hosts_path().write_text(json.dumps(hosts))
