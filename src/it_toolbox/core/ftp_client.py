"""FTP/SFTP protocol clients for the embedded FileZilla-style file
browser (widgets/ftp_browser_widget.py) — one persistent connection per
browser tab, reused across every list/upload/download/... call rather
than reconnecting each time (unlike core/rclone_client.py, which shells
out to a fresh `rclone` invocation per call because the CLI itself is
stateless).

Every method below is a plain blocking call, meant to be invoked from a
background thread via core.async_utils.run_in_background — same
convention as every other network call in this app.

SftpSession wraps paramiko (SFTP-over-SSH2); FtpSession wraps the stdlib
ftplib (plain FTP, or FTPS via FTP_TLS). Both expose the same duck-typed
interface (connect/home_dir/list_dir/download/upload/mkdir/rmdir/remove/
rename/close, plus a `kind` class attribute) so ftp_browser_widget.py can
treat either uniformly without a shared base class — matching how
TerminalWidget/RdpWidget/SpiceWidget already coexist in this codebase
without one.
"""

from __future__ import annotations

import base64
import ftplib
import hashlib
import os
import posixpath
import stat as stat_module
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import paramiko

ProgressCallback = Callable[[int, int], None]  # (bytes_transferred, total_bytes)


class FtpClientError(Exception):
    """Raised for any connection/auth/protocol failure from either
    SftpSession or FtpSession — the browser widget shows str(exc) in a
    single QMessageBox regardless of which backend raised it."""


def _sha256_fingerprint(key: paramiko.PKey) -> str:
    digest = hashlib.sha256(key.asbytes()).digest()
    return "SHA256:" + base64.b64encode(digest).decode().rstrip("=")


class UnknownHostKeyError(FtpClientError):
    """Raised by SftpSession.connect() instead of a generic failure when
    the host key isn't yet trusted (no known_hosts entry for this host at
    all -- a genuine mismatch instead raises paramiko.BadHostKeyException,
    handled separately and never offered a one-click "trust it" path).
    Carries enough to show a real ssh-style fingerprint confirmation
    prompt; if the user accepts, the caller persists it via
    SftpSession.trust_host_key() and retries connect().
    """

    def __init__(self, hostname: str, key: paramiko.PKey) -> None:
        self.hostname = hostname
        self.key = key
        self.fingerprint = _sha256_fingerprint(key)
        super().__init__(
            f"{hostname}'s host key ({key.get_name()} {self.fingerprint}) is not yet trusted."
        )


class _RaiseUnknownHostKey(paramiko.MissingHostKeyPolicy):
    """Turns paramiko's "no known_hosts entry for this host" case into
    UnknownHostKeyError instead of RejectPolicy's plain SSHException, so
    the caller can distinguish "never seen before, ask the user" from
    every other connection failure.
    """

    def missing_host_key(self, client, hostname, key):
        raise UnknownHostKeyError(hostname, key)


@dataclass(frozen=True)
class FileEntry:
    """One row in a directory listing — used for both local (os.scandir)
    and remote (SFTP/FTP) listings so the browser widget can treat both
    panes identically.
    """

    name: str
    is_dir: bool
    size: int = 0
    modified: float = 0.0  # epoch seconds, 0 if unknown
    permissions: str = ""  # e.g. "drwxr-xr-x" — SFTP (and local) only


def _sort_entries(entries: list[FileEntry]) -> list[FileEntry]:
    return sorted(entries, key=lambda e: (not e.is_dir, e.name.lower()))


def list_local_dir(path: str) -> list[FileEntry]:
    entries = []
    with os.scandir(path) as it:
        for de in it:
            try:
                is_dir = de.is_dir(follow_symlinks=True)
                st = de.stat(follow_symlinks=True)
            except OSError:
                continue
            entries.append(
                FileEntry(
                    name=de.name,
                    is_dir=is_dir,
                    size=0 if is_dir else st.st_size,
                    modified=st.st_mtime,
                    permissions=stat_module.filemode(st.st_mode),
                )
            )
    return _sort_entries(entries)


class SftpSession:
    """One SFTP connection (over its own dedicated SSH transport,
    independent of widgets/terminal_widget.py's plain `ssh` subprocess)
    to host:port. allow_agent/look_for_keys are always enabled, so
    leaving both password and key_path unset falls back to the user's
    SSH agent or default key (~/.ssh/id_ed25519, ~/.ssh/id_rsa) —
    paramiko itself tries key_path, then the agent, then password, in
    that order.
    """

    kind = "sftp"

    def __init__(
        self,
        host: str,
        port: int,
        username: str,
        password: str | None = None,
        key_path: str | None = None,
        key_passphrase: str | None = None,
        skip_host_key_check: bool = False,
    ) -> None:
        self._host = host
        self._port = port
        self._username = username
        self._password = password or None
        self._key_path = key_path or None
        self._key_passphrase = key_passphrase or None
        self._skip_host_key_check = skip_host_key_check
        self._client: paramiko.SSHClient | None = None
        self._sftp: paramiko.SFTPClient | None = None

    def connect(self) -> None:
        client = paramiko.SSHClient()
        if self._skip_host_key_check:
            # Same reasoning as main_view.py's _embed_ssh skip_host_key_check:
            # this is a GCP/IAP-tunneled connection to 127.0.0.1 on a fresh
            # ephemeral local port, so there's no meaningful host identity to
            # pin. Unlike the `ssh` CLI, paramiko never persists an
            # AutoAddPolicy-accepted key to disk on its own (nothing here
            # calls save_host_keys), so this can't accumulate junk
            # known_hosts entries the way a real ssh invocation would.
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        else:
            client.load_system_host_keys()
            known_hosts = Path.home() / ".ssh" / "known_hosts"
            try:
                client.load_host_keys(str(known_hosts))
            except OSError:
                pass
            client.set_missing_host_key_policy(_RaiseUnknownHostKey())
        try:
            client.connect(
                self._host,
                port=self._port,
                username=self._username,
                password=self._password,
                key_filename=self._key_path,
                passphrase=self._key_passphrase,
                allow_agent=True,
                look_for_keys=True,
                timeout=15,
            )
        except UnknownHostKeyError:
            raise  # not a generic failure -- let the caller offer to trust it and retry
        except paramiko.AuthenticationException as exc:
            raise FtpClientError(
                f"Authentication failed for {self._username}@{self._host}."
            ) from exc
        except paramiko.BadHostKeyException as exc:
            raise FtpClientError(
                f"{self._host}'s host key doesn't match the one in your known_hosts file — "
                "refusing to connect. This normally means the host was reinstalled -- if you "
                "expect that, remove its old entry from ~/.ssh/known_hosts and try again."
            ) from exc
        except paramiko.SSHException as exc:
            raise FtpClientError(f"Couldn't connect to {self._host}:{self._port} — {exc}") from exc
        except OSError as exc:
            raise FtpClientError(f"Couldn't connect to {self._host}:{self._port} — {exc}") from exc

        self._client = client
        self._sftp = client.open_sftp()

    def trust_host_key(self, hostname: str, key: paramiko.PKey) -> None:
        """Persists `key` as trusted for `hostname` by appending it to the
        user's real ~/.ssh/known_hosts -- the same file a real `ssh`
        client itself reads and writes, so accepting it here also
        satisfies a subsequent real `ssh` connection to the same host.
        Only meaningful when skip_host_key_check is False; the caller
        (FtpBrowserWidget) calls this after the user confirms the
        fingerprint from an UnknownHostKeyError, then retries connect().
        """
        known_hosts = Path.home() / ".ssh" / "known_hosts"
        host_keys = paramiko.HostKeys()
        try:
            host_keys.load(str(known_hosts))
        except OSError:
            pass
        host_keys.add(hostname, key.get_name(), key)
        known_hosts.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        host_keys.save(str(known_hosts))

    def home_dir(self) -> str:
        return self._sftp.normalize(".")

    def list_dir(self, path: str) -> list[FileEntry]:
        entries = []
        for attr in self._sftp.listdir_attr(path or "."):
            mode = attr.st_mode or 0
            entries.append(
                FileEntry(
                    name=attr.filename,
                    is_dir=stat_module.S_ISDIR(mode),
                    size=attr.st_size or 0,
                    modified=float(attr.st_mtime or 0),
                    permissions=stat_module.filemode(mode) if mode else "",
                )
            )
        return _sort_entries(entries)

    def download(self, remote_path: str, local_path: str, progress: ProgressCallback | None = None) -> None:
        self._sftp.get(remote_path, local_path, callback=progress)

    def upload(self, local_path: str, remote_path: str, progress: ProgressCallback | None = None) -> None:
        self._sftp.put(local_path, remote_path, callback=progress)

    def mkdir(self, path: str) -> None:
        self._sftp.mkdir(path)

    def rmdir(self, path: str) -> None:
        self._sftp.rmdir(path)

    def remove(self, path: str) -> None:
        self._sftp.remove(path)

    def rename(self, old_path: str, new_path: str) -> None:
        self._sftp.rename(old_path, new_path)

    def chmod(self, path: str, mode: int) -> None:
        self._sftp.chmod(path, mode)

    def join(self, base: str, name: str) -> str:
        return posixpath.join(base or "/", name)

    def parent(self, path: str) -> str:
        return posixpath.dirname(path.rstrip("/")) or "/"

    def close(self) -> None:
        if self._sftp is not None:
            self._sftp.close()
        if self._client is not None:
            self._client.close()


def _parse_mlsd_modify(raw: str) -> float:
    """Parses MLSD's "modify=YYYYMMDDHHMMSS[.sss]" fact into epoch seconds."""
    if not raw:
        return 0.0
    import calendar
    import time

    try:
        return float(calendar.timegm(time.strptime(raw[:14], "%Y%m%d%H%M%S")))
    except ValueError:
        return 0.0


class FtpSession:
    """One plain-FTP (or FTPS, if use_tls) connection via the stdlib
    ftplib. Directory listing uses MLSD (RFC 3659), which every FTP
    server built in the last ~20 years supports — no LIST-text-parsing
    fallback for the rare server that doesn't.
    """

    kind = "ftp"

    def __init__(
        self,
        host: str,
        port: int,
        username: str,
        password: str = "",
        use_tls: bool = False,
    ) -> None:
        self._host = host
        self._port = port
        self._username = username or "anonymous"
        self._password = password
        self._use_tls = use_tls
        self._ftp: ftplib.FTP | None = None

    def connect(self) -> None:
        ftp = ftplib.FTP_TLS() if self._use_tls else ftplib.FTP()
        try:
            ftp.connect(self._host, self._port, timeout=15)
            ftp.login(self._username, self._password)
            if self._use_tls:
                ftp.prot_p()
            ftp.set_pasv(True)
        except ftplib.all_errors as exc:
            raise FtpClientError(f"Couldn't connect to {self._host}:{self._port} — {exc}") from exc
        self._ftp = ftp

    def home_dir(self) -> str:
        return self._ftp.pwd()

    def list_dir(self, path: str) -> list[FileEntry]:
        entries = []
        try:
            listing = self._ftp.mlsd(path or ".")
            for name, facts in listing:
                if name in (".", ".."):
                    continue
                entries.append(
                    FileEntry(
                        name=name,
                        is_dir=facts.get("type") == "dir",
                        size=int(facts.get("size", 0) or 0),
                        modified=_parse_mlsd_modify(facts.get("modify", "")),
                    )
                )
        except ftplib.all_errors as exc:
            raise FtpClientError(str(exc)) from exc
        return _sort_entries(entries)

    def download(self, remote_path: str, local_path: str, progress: ProgressCallback | None = None) -> None:
        try:
            total = self._ftp.size(remote_path) or 0
        except ftplib.all_errors:
            total = 0
        transferred = 0
        try:
            with open(local_path, "wb") as f:

                def _write(chunk: bytes) -> None:
                    nonlocal transferred
                    f.write(chunk)
                    transferred += len(chunk)
                    if progress:
                        progress(transferred, total)

                self._ftp.retrbinary(f"RETR {remote_path}", _write)
        except ftplib.all_errors as exc:
            raise FtpClientError(str(exc)) from exc

    def upload(self, local_path: str, remote_path: str, progress: ProgressCallback | None = None) -> None:
        total = os.path.getsize(local_path)
        transferred = 0

        def _report(chunk: bytes) -> None:
            nonlocal transferred
            transferred += len(chunk)
            if progress:
                progress(transferred, total)

        try:
            with open(local_path, "rb") as f:
                self._ftp.storbinary(f"STOR {remote_path}", f, callback=_report)
        except ftplib.all_errors as exc:
            raise FtpClientError(str(exc)) from exc

    def mkdir(self, path: str) -> None:
        try:
            self._ftp.mkd(path)
        except ftplib.all_errors as exc:
            raise FtpClientError(str(exc)) from exc

    def rmdir(self, path: str) -> None:
        try:
            self._ftp.rmd(path)
        except ftplib.all_errors as exc:
            raise FtpClientError(str(exc)) from exc

    def remove(self, path: str) -> None:
        try:
            self._ftp.delete(path)
        except ftplib.all_errors as exc:
            raise FtpClientError(str(exc)) from exc

    def rename(self, old_path: str, new_path: str) -> None:
        try:
            self._ftp.rename(old_path, new_path)
        except ftplib.all_errors as exc:
            raise FtpClientError(str(exc)) from exc

    def join(self, base: str, name: str) -> str:
        return posixpath.join(base or "/", name)

    def parent(self, path: str) -> str:
        return posixpath.dirname(path.rstrip("/")) or "/"

    def close(self) -> None:
        if self._ftp is None:
            return
        try:
            self._ftp.quit()
        except ftplib.all_errors:
            try:
                self._ftp.close()
            except ftplib.all_errors:
                pass
