"""The saved-host record every Infrastructure product shares.

Proxmox VE, TrueNAS and Proxmox Backup Server are all "an HTTPS API on
an appliance with a self-signed certificate, plus a token", so one record
covers all three: `token_id` is Proxmox/PBS's "user@realm!name" (TrueNAS
leaves it empty and uses `secret` alone as its API key).

`secret_encrypted` is always age ciphertext (see
settings.encrypt_infrastructure_secret), same as GlinetHost's password --
printing a host can't leak its token. None means nothing stored yet; the
token is then asked for once per session.
"""

import base64
import binascii
from dataclasses import dataclass, replace
from urllib.parse import urlsplit


@dataclass(frozen=True)
class InfrastructureHost:
    name: str
    url: str  # e.g. "https://pve1.lan:8006"
    token_id: str = ""
    secret_encrypted: bytes | None = None
    verify_ssl: bool = False
    # SHA-256 of the certificate trusted when the host was added; required
    # whenever verify_ssl is off (see core/pinned_tls.py).
    fingerprint: str | None = None
    ssh_username: str = "root"

    @property
    def key(self) -> tuple[str, str]:
        return (self.url.rstrip("/").lower(), self.token_id)

    @property
    def hostname(self) -> str:
        return urlsplit(self.url).hostname or self.url

    def with_changes(self, **changes) -> "InfrastructureHost":
        return replace(self, **changes)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "url": self.url,
            "token_id": self.token_id,
            "secret_encrypted": (
                base64.b64encode(self.secret_encrypted).decode() if self.secret_encrypted else None
            ),
            "verify_ssl": self.verify_ssl,
            "fingerprint": self.fingerprint,
            "ssh_username": self.ssh_username,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "InfrastructureHost | None":
        try:
            encrypted = data.get("secret_encrypted")
            return cls(
                name=str(data["name"]),
                url=str(data["url"]),
                token_id=str(data.get("token_id") or ""),
                secret_encrypted=base64.b64decode(encrypted) if encrypted else None,
                verify_ssl=bool(data.get("verify_ssl", False)),
                fingerprint=data.get("fingerprint") or None,
                ssh_username=str(data.get("ssh_username") or "root"),
            )
        except (KeyError, TypeError, ValueError, binascii.Error):
            return None


def normalize_url(text: str, default_port: int) -> str:
    """"pve1.lan" -> "https://pve1.lan:8006"; keeps an explicit scheme/port."""
    text = text.strip().rstrip("/")
    if not text:
        return ""
    if "://" not in text:
        text = f"https://{text}"
    parts = urlsplit(text)
    if parts.port is None and parts.hostname:
        text = f"{parts.scheme}://{parts.hostname}:{default_port}{parts.path}"
    return text
