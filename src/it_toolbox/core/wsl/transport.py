"""Wire format between the app and it_toolbox.wsl_helper services.

Shared by both ends, so standard library only: the helper side imports
this inside the Linux tools WSL distro, where PySide6 isn't installed.
See docs/wsl-interconnect-plan.md ("Helper services").

Connection setup:

1. The app spawns `python3 -m it_toolbox.wsl_helper <service>` (through
   core/linux_backend, so inside the distro on Windows).
2. The helper listens on an ephemeral 127.0.0.1 port and prints one JSON
   line to stdout: {"port": N, "token": "<hex>"}. WSL2's localhost
   forwarding makes that listener reachable from Windows' own loopback.
3. The app connects and sends HELLO(token) then START(json params).
   The helper drops any connection whose first message isn't the right
   token, so another local process can't drive it.
4. From there each service defines its own message types (>= 16).

Messages are `!IB` (payload length, type) followed by the payload --
small enough to read with two recv calls, and frames (the big ones) go
out as one sendall of header + payload.
"""

import hmac
import json
import secrets
import socket
import struct
import threading

HEADER = struct.Struct("!IB")
MAX_PAYLOAD = 256 * 1024 * 1024  # a 4K BGRX frame is ~33 MB; anything far past that is garbage

# Transport-level message types. Services use 16 and up.
MSG_HELLO = 0
MSG_START = 1
MSG_STOP = 2
MSG_ERROR = 3
MSG_SERVICE_BASE = 16

ACCEPT_TIMEOUT_SEC = 30


class TransportError(Exception):
    pass


class Connection:
    """A socket with message framing. send() is safe from any thread;
    recv() must only be called from one."""

    def __init__(self, sock: socket.socket) -> None:
        self._sock = sock
        self._send_lock = threading.Lock()
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)

    def send(self, msg_type: int, payload: bytes = b"") -> None:
        data = HEADER.pack(len(payload), msg_type) + payload
        with self._send_lock:
            self._sock.sendall(data)

    def send_json(self, msg_type: int, obj) -> None:
        self.send(msg_type, json.dumps(obj).encode())

    def recv(self) -> tuple[int, bytes]:
        """Blocks for the next message. Raises EOFError on a clean close."""
        length, msg_type = HEADER.unpack(self._recv_exact(HEADER.size))
        if length > MAX_PAYLOAD:
            raise TransportError(f"message too large ({length} bytes)")
        return msg_type, self._recv_exact(length)

    def _recv_exact(self, n: int) -> bytes:
        buf = bytearray()
        while len(buf) < n:
            chunk = self._sock.recv(min(n - len(buf), 1024 * 1024))
            if not chunk:
                raise EOFError("connection closed")
            buf += chunk
        return bytes(buf)

    def close(self) -> None:
        try:
            self._sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self._sock.close()


# --- helper side -----------------------------------------------------------


class Listener:
    def __init__(self) -> None:
        self.token = secrets.token_hex(16)
        self._server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server.bind(("127.0.0.1", 0))
        self._server.listen(1)
        self.port = self._server.getsockname()[1]

    def handshake_line(self) -> str:
        return json.dumps({"port": self.port, "token": self.token})

    def accept(self, timeout: float = ACCEPT_TIMEOUT_SEC) -> tuple[Connection, dict]:
        """Waits for the app to connect and authenticate; returns the
        connection and its START params. Connections that fail the token
        check are dropped and the wait continues until `timeout`."""
        self._server.settimeout(timeout)
        try:
            while True:
                try:
                    sock, _addr = self._server.accept()
                except TimeoutError as e:
                    raise TransportError("the app never connected") from e
                sock.settimeout(None)
                conn = Connection(sock)
                try:
                    msg_type, payload = conn.recv()
                    if msg_type != MSG_HELLO or not hmac.compare_digest(payload, self.token.encode()):
                        conn.close()
                        continue
                    msg_type, payload = conn.recv()
                    if msg_type != MSG_START:
                        conn.close()
                        continue
                    return conn, json.loads(payload or b"{}")
                except (EOFError, OSError, TransportError, ValueError):
                    conn.close()
                    continue
        finally:
            self._server.close()


# --- app side --------------------------------------------------------------


def parse_handshake_line(line: str) -> tuple[int, str]:
    try:
        data = json.loads(line)
        return int(data["port"]), str(data["token"])
    except (ValueError, KeyError, TypeError) as e:
        raise TransportError(f"unexpected helper output: {line.strip()[:200]!r}") from e


def connect(port: int, token: str, params: dict, timeout: float = 10) -> Connection:
    sock = socket.create_connection(("127.0.0.1", port), timeout=timeout)
    sock.settimeout(None)
    conn = Connection(sock)
    conn.send(MSG_HELLO, token.encode())
    conn.send_json(MSG_START, params)
    return conn
