"""HTTPS to appliances that ship self-signed certificates (Proxmox,
TrueNAS, Proxmox Backup Server), without ever turning verification off
outright.

Each host either verifies normally (`verify_ssl=True`, for hosts with a
real certificate) or is pinned to the SHA-256 fingerprint of the
certificate it presented the first time it was added -- the same
trust-on-first-use deal SSH's known_hosts makes. A pinned host whose
certificate later changes fails with CertificateMismatchError rather than
quietly connecting, so a re-issued certificate (or someone in the middle)
always reaches the user as a question.

urllib3 does the pinning itself (its `assert_fingerprint` pool option),
so every request made through a session from make_session() is checked,
not just the first.
"""

import hashlib
import socket
import ssl
from urllib.parse import urlsplit

import requests
from requests.adapters import HTTPAdapter


class CertificateMismatchError(Exception):
    """The host's certificate no longer matches its pinned fingerprint."""

    def __init__(self, url: str, expected: str, actual: str) -> None:
        super().__init__(
            f"The certificate for {url} has changed (pinned {expected}, now {actual}). "
            "If the certificate was renewed on purpose, edit the host and trust the new one."
        )
        self.url = url
        self.expected = expected
        self.actual = actual


def format_fingerprint(digest: bytes) -> str:
    """"AB:CD:..." -- the form Proxmox and TrueNAS show in their own UIs."""
    return ":".join(f"{b:02X}" for b in digest)


def normalize_fingerprint(fingerprint: str) -> str:
    return fingerprint.replace(":", "").strip().lower()


def host_port(url: str, default_port: int = 443) -> tuple[str, int]:
    parts = urlsplit(url)
    return parts.hostname or "", parts.port or default_port


def fetch_fingerprint(url: str, timeout: float = 10) -> str:
    """The SHA-256 fingerprint of the certificate `url`'s host presents,
    fetched without validating it -- this is what the user is asked to
    trust when adding a host."""
    host, port = host_port(url)
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    with socket.create_connection((host, port), timeout=timeout) as sock:
        with context.wrap_socket(sock, server_hostname=host) as tls:
            der = tls.getpeercert(binary_form=True)
    return format_fingerprint(hashlib.sha256(der).digest())


class _PinnedAdapter(HTTPAdapter):
    def __init__(self, fingerprint: str) -> None:
        self._fingerprint = normalize_fingerprint(fingerprint)
        super().__init__()

    def init_poolmanager(self, *args, **kwargs):
        kwargs["assert_fingerprint"] = self._fingerprint
        kwargs["cert_reqs"] = "CERT_NONE"
        return super().init_poolmanager(*args, **kwargs)


def make_session(url: str, verify_ssl: bool, fingerprint: str | None) -> requests.Session:
    """A requests session for `url`'s host. With verify_ssl off, a
    fingerprint is required -- there is deliberately no "trust anything"
    mode."""
    session = requests.Session()
    if verify_ssl:
        return session
    if not fingerprint:
        raise ValueError(f"No pinned certificate fingerprint for {url}.")
    session.verify = False
    session.mount(f"https://{urlsplit(url).netloc}", _PinnedAdapter(fingerprint))
    return session


def check_pinned(url: str, fingerprint: str) -> None:
    """Raises CertificateMismatchError if `url` no longer presents the
    pinned certificate. Used to turn urllib3's generic SSLError into a
    message that says what happened."""
    actual = fetch_fingerprint(url)
    if normalize_fingerprint(actual) != normalize_fingerprint(fingerprint):
        raise CertificateMismatchError(url, fingerprint, actual)


def ssl_context_for(verify_ssl: bool) -> ssl.SSLContext:
    """For websocket consoles: a context that verifies normally, or one
    that skips CA checks so the caller can compare the fingerprint itself
    (see fingerprint_of)."""
    context = ssl.create_default_context()
    if not verify_ssl:
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
    return context


def fingerprint_of(der: bytes) -> str:
    return format_fingerprint(hashlib.sha256(der).digest())
