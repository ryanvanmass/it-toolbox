import datetime
import hashlib
import http.server
import ssl
import threading

import pytest
import requests
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from it_toolbox.core import pinned_tls


def _self_signed(tmp_path, name):
    key = ec.generate_private_key(ec.SECP256R1())
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, name)])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=1))
        .sign(key, hashes.SHA256())
    )
    cert_path = tmp_path / f"{name}.crt"
    key_path = tmp_path / f"{name}.key"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    der = cert.public_bytes(serialization.Encoding.DER)
    return cert_path, key_path, pinned_tls.format_fingerprint(hashlib.sha256(der).digest())


class _Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802 - http.server's naming
        body = b'{"ok": true}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


@pytest.fixture
def tls_server(tmp_path):
    cert_path, key_path, fingerprint = _self_signed(tmp_path, "localhost")
    server = http.server.HTTPServer(("127.0.0.1", 0), _Handler)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert_path, key_path)
    server.socket = context.wrap_socket(server.socket, server_side=True)
    server.handle_error = lambda *args: None  # rejected handshakes are the point of some tests
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"https://127.0.0.1:{server.server_address[1]}", fingerprint
    server.shutdown()
    server.server_close()


def test_fetch_fingerprint_matches_the_served_certificate(tls_server):
    url, fingerprint = tls_server
    assert pinned_tls.fetch_fingerprint(url) == fingerprint


def test_pinned_session_accepts_the_pinned_certificate(tls_server):
    url, fingerprint = tls_server
    session = pinned_tls.make_session(url, verify_ssl=False, fingerprint=fingerprint)
    assert session.get(f"{url}/x", timeout=5).json() == {"ok": True}


def test_pinned_session_rejects_a_different_certificate(tls_server, tmp_path):
    url, _ = tls_server
    _, _, other = _self_signed(tmp_path, "other")
    session = pinned_tls.make_session(url, verify_ssl=False, fingerprint=other)
    with pytest.raises(requests.exceptions.SSLError):
        session.get(f"{url}/x", timeout=5)


def test_verifying_session_rejects_a_self_signed_certificate(tls_server):
    url, _ = tls_server
    session = pinned_tls.make_session(url, verify_ssl=True, fingerprint=None)
    with pytest.raises(requests.exceptions.SSLError):
        session.get(f"{url}/x", timeout=5)


def test_unverified_session_requires_a_fingerprint():
    with pytest.raises(ValueError):
        pinned_tls.make_session("https://pve.lan:8006", verify_ssl=False, fingerprint=None)


def test_check_pinned_reports_a_changed_certificate(tls_server, tmp_path):
    url, fingerprint = tls_server
    pinned_tls.check_pinned(url, fingerprint.lower())  # case/colons don't matter
    _, _, other = _self_signed(tmp_path, "other")
    with pytest.raises(pinned_tls.CertificateMismatchError) as error:
        pinned_tls.check_pinned(url, other)
    assert error.value.actual == fingerprint
