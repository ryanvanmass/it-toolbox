"""Native IAP TCP forwarding tunnel client.

Reimplements the wire protocol used by `gcloud compute start-iap-tunnel`
(Apache-2.0, googlecloudsdk.api_lib.compute.iap_tunnel_websocket*) so this
app has no runtime dependency on the gcloud CLI for tunneling itself.
Protocol constants below were verified against that source directly, not
guessed — see the frame tag values, sizes, and reconnect query params.
"""

import asyncio
import logging
import struct
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from urllib.parse import urlencode

import websockets

logger = logging.getLogger(__name__)

# -- Protocol constants (verified against the Cloud SDK source) -------------

WS_URL_HOST = "tunnel.cloudproxy.app"
WS_URL_PATH_ROOT = "/v4"
CONNECT_ENDPOINT = "connect"
RECONNECT_ENDPOINT = "reconnect"
SUBPROTOCOL_NAME = "relay.tunnel.cloudproxy.app"

MAX_DATA_FRAME_SIZE = 16384

TAG_CONNECT_SUCCESS_SID = 0x0001
TAG_RECONNECT_SUCCESS_ACK = 0x0002
TAG_DATA = 0x0004
TAG_ACK = 0x0007

# Send an ACK once received-but-unacked bytes exceed this, rather than on a
# timer — matches the Cloud SDK's "delayed ack" policy (2x max frame size).
ACK_THRESHOLD_BYTES = 2 * MAX_DATA_FRAME_SIZE

RECONNECT_INITIAL_SLEEP_SEC = 1.5
RECONNECT_BACKOFF_MULTIPLIER = 1.1
RECONNECT_MAX_SLEEP_SEC = 20
RECONNECT_MAX_TOTAL_WAIT_SEC = 15 * 60

CONNECT_OPEN_TIMEOUT_SEC = 60


class IncompleteFrame(Exception):
    """Not enough bytes buffered yet to decode a full frame."""


class ProtocolError(Exception):
    """The server sent something that violates the expected protocol."""


# -- Frame codec --------------------------------------------------------
#
# Pure encode/decode, no I/O — this is the highest-risk, hardest-to-debug
# piece if wrong, so it's kept small and separately unit-testable.


def encode_data_frame(payload: bytes) -> bytes:
    if len(payload) > MAX_DATA_FRAME_SIZE:
        raise ValueError(
            f"payload of {len(payload)} bytes exceeds MAX_DATA_FRAME_SIZE={MAX_DATA_FRAME_SIZE}"
        )
    return struct.pack(">HI", TAG_DATA, len(payload)) + payload


def encode_ack_frame(bytes_received: int) -> bytes:
    return struct.pack(">HQ", TAG_ACK, bytes_received)


@dataclass(frozen=True)
class DecodedFrame:
    tag: int
    # DATA: raw payload bytes. ACK / RECONNECT_SUCCESS_ACK: bytes-confirmed
    # count. CONNECT_SUCCESS_SID: the opaque session id bytes.
    value: bytes | int


def decode_frame(buf: bytes) -> tuple[DecodedFrame, bytes]:
    """Decode one frame from the front of `buf`.

    Returns (frame, remaining_bytes). Raises IncompleteFrame if `buf`
    doesn't yet contain a full frame — caller should buffer more and retry.
    """
    if len(buf) < 2:
        raise IncompleteFrame
    (tag,) = struct.unpack(">H", buf[:2])
    rest = buf[2:]

    if tag == TAG_DATA:
        if len(rest) < 4:
            raise IncompleteFrame
        (length,) = struct.unpack(">I", rest[:4])
        if len(rest) < 4 + length:
            raise IncompleteFrame
        payload = rest[4 : 4 + length]
        return DecodedFrame(tag, payload), rest[4 + length :]

    if tag == TAG_ACK or tag == TAG_RECONNECT_SUCCESS_ACK:
        if len(rest) < 8:
            raise IncompleteFrame
        (count,) = struct.unpack(">Q", rest[:8])
        return DecodedFrame(tag, count), rest[8:]

    if tag == TAG_CONNECT_SUCCESS_SID:
        if len(rest) < 4:
            raise IncompleteFrame
        (length,) = struct.unpack(">I", rest[:4])
        if len(rest) < 4 + length:
            raise IncompleteFrame
        sid = rest[4 : 4 + length]
        return DecodedFrame(tag, sid), rest[4 + length :]

    raise ProtocolError(f"unknown frame tag {tag!r}")


# -- Tunnel target / URLs ------------------------------------------------


@dataclass(frozen=True)
class IapTunnelTarget:
    project: str
    zone: str
    instance: str
    port: int
    interface: str = "nic0"


def _connect_url(target: IapTunnelTarget) -> str:
    query = urlencode(
        {
            "project": target.project,
            "zone": target.zone,
            "instance": target.instance,
            "interface": target.interface,
            "port": target.port,
            "newWebsocket": "True",
        }
    )
    return f"wss://{WS_URL_HOST}{WS_URL_PATH_ROOT}/{CONNECT_ENDPOINT}?{query}"


def _reconnect_url(target: IapTunnelTarget, sid: bytes, ack_bytes: int) -> str:
    query = urlencode(
        {
            "sid": sid.decode("utf-8"),
            "ack": ack_bytes,
            "zone": target.zone,
            "newWebsocket": "True",
        }
    )
    return f"wss://{WS_URL_HOST}{WS_URL_PATH_ROOT}/{RECONNECT_ENDPOINT}?{query}"


# -- Tunnel connection ----------------------------------------------------

GetAccessToken = Callable[[], str]


class IapTunnelConnection:
    """Owns one IAP websocket for the lifetime of one local TCP connection.

    Pumps bytes bidirectionally between a local (reader, writer) pair and
    the remote IAP relay, transparently reconnecting (with backoff) on
    websocket drops using the session-id/ack-offset resume protocol.
    """

    def __init__(
        self,
        target: IapTunnelTarget,
        get_access_token: GetAccessToken,
        on_status: Callable[[str], None] | None = None,
    ) -> None:
        self._target = target
        self._get_access_token = get_access_token
        self._on_status = on_status or (lambda status: None)

        self._sid: bytes | None = None
        self._total_bytes_received = 0
        self._total_bytes_received_and_acked = 0
        self._total_bytes_confirmed = 0
        # Data sent but not yet confirmed by an ACK from the server — must be
        # resent after a reconnect in case it never arrived.
        self._unconfirmed: list[bytes] = []

    async def pump(self, local_reader: asyncio.StreamReader, local_writer: asyncio.StreamWriter) -> None:
        ws = await self._connect()
        try:
            await asyncio.gather(
                self._pump_local_to_remote(local_reader, ws),
                self._pump_remote_to_local(ws, local_writer),
            )
        finally:
            await ws.close()
            local_writer.close()

    async def _connect(self):
        """Connect (or reconnect) with backoff, returning an open websocket."""
        deadline = asyncio.get_event_loop().time() + RECONNECT_MAX_TOTAL_WAIT_SEC
        sleep_sec = RECONNECT_INITIAL_SLEEP_SEC
        first_attempt = True

        while True:
            try:
                url = (
                    _connect_url(self._target)
                    if self._sid is None
                    else _reconnect_url(self._target, self._sid, self._total_bytes_received)
                )
                headers = {"Authorization": f"Bearer {self._get_access_token()}"}
                ws = await asyncio.wait_for(
                    websockets.connect(
                        url,
                        additional_headers=headers,
                        subprotocols=[SUBPROTOCOL_NAME],
                    ),
                    timeout=CONNECT_OPEN_TIMEOUT_SEC,
                )
                await self._await_connect_ack(ws, is_reconnect=not first_attempt)
                self._on_status("connected" if first_attempt else "reconnected")
                return ws
            except Exception as exc:  # noqa: BLE001 - retried below, or re-raised at deadline
                if asyncio.get_event_loop().time() >= deadline:
                    raise ConnectionError(
                        f"Failed to connect/reconnect within {RECONNECT_MAX_TOTAL_WAIT_SEC}s"
                    ) from exc
                first_attempt = False
                self._on_status(f"reconnecting ({exc})")
                await asyncio.sleep(sleep_sec)
                sleep_sec = min(sleep_sec * RECONNECT_BACKOFF_MULTIPLIER, RECONNECT_MAX_SLEEP_SEC)

    async def _await_connect_ack(self, ws, is_reconnect: bool) -> None:
        raw = await asyncio.wait_for(ws.recv(), timeout=CONNECT_OPEN_TIMEOUT_SEC)
        frame, _ = decode_frame(raw if isinstance(raw, bytes) else raw.encode())

        if not is_reconnect:
            if frame.tag != TAG_CONNECT_SUCCESS_SID:
                raise ProtocolError(f"expected CONNECT_SUCCESS_SID, got tag {frame.tag}")
            self._sid = frame.value  # type: ignore[assignment]
            return

        if frame.tag != TAG_RECONNECT_SUCCESS_ACK:
            raise ProtocolError(f"expected RECONNECT_SUCCESS_ACK, got tag {frame.tag}")
        self._confirm_bytes(frame.value)  # type: ignore[arg-type]
        # Resend anything the server hasn't confirmed yet.
        to_resend, self._unconfirmed = self._unconfirmed, []
        for chunk in to_resend:
            await ws.send(encode_data_frame(chunk))

    async def _pump_local_to_remote(self, local_reader: asyncio.StreamReader, ws) -> None:
        while True:
            chunk = await local_reader.read(MAX_DATA_FRAME_SIZE)
            if not chunk:
                return
            self._unconfirmed.append(chunk)
            await ws.send(encode_data_frame(chunk))

    async def _pump_remote_to_local(self, ws, local_writer: asyncio.StreamWriter) -> None:
        buf = b""
        async for message in ws:
            buf += message if isinstance(message, bytes) else message.encode()
            while True:
                try:
                    frame, buf = decode_frame(buf)
                except IncompleteFrame:
                    break

                if frame.tag == TAG_DATA:
                    data = frame.value
                    local_writer.write(data)  # type: ignore[arg-type]
                    await local_writer.drain()
                    self._total_bytes_received += len(data)  # type: ignore[arg-type]
                    if (
                        self._total_bytes_received - self._total_bytes_received_and_acked
                        > ACK_THRESHOLD_BYTES
                    ):
                        await ws.send(encode_ack_frame(self._total_bytes_received))
                        self._total_bytes_received_and_acked = self._total_bytes_received
                elif frame.tag == TAG_ACK:
                    self._confirm_bytes(frame.value)  # type: ignore[arg-type]
                else:
                    logger.debug("Unexpected frame tag %r after connect", frame.tag)

    def _confirm_bytes(self, bytes_confirmed: int) -> None:
        if bytes_confirmed < self._total_bytes_confirmed:
            raise ProtocolError(f"out-of-order ack for {bytes_confirmed} bytes")
        to_confirm = bytes_confirmed - self._total_bytes_confirmed
        while to_confirm and self._unconfirmed:
            chunk = self._unconfirmed[0]
            if len(chunk) > to_confirm:
                self._unconfirmed[0] = chunk[to_confirm:]
                self._total_bytes_confirmed += to_confirm
                to_confirm = 0
            else:
                self._unconfirmed.pop(0)
                self._total_bytes_confirmed += len(chunk)
                to_confirm -= len(chunk)
        if to_confirm:
            raise ProtocolError(
                f"server confirmed {bytes_confirmed} bytes but only "
                f"{self._total_bytes_confirmed} were ever sent"
            )


# -- Local listener + manager ----------------------------------------------


class TunnelManager:
    """Runs a local TCP listener that forwards each accepted connection
    through its own IapTunnelConnection. Owns an asyncio event loop on a
    dedicated background thread so it can be driven from Qt (or a plain
    CLI) without blocking the caller.
    """

    def __init__(self, target: IapTunnelTarget, get_access_token: GetAccessToken) -> None:
        self._target = target
        self._get_access_token = get_access_token
        self._server: asyncio.AbstractServer | None = None

    async def _handle_client(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        conn = IapTunnelConnection(self._target, self._get_access_token)
        try:
            await conn.pump(reader, writer)
        except Exception:
            logger.exception("IAP tunnel connection ended with an error")

    async def start(self, local_host: str = "127.0.0.1", local_port: int = 0) -> int:
        """Start listening and return the bound local port."""
        self._server = await asyncio.start_server(self._handle_client, local_host, local_port)
        return self._server.sockets[0].getsockname()[1]

    async def serve_forever(self) -> None:
        """Accept and forward connections until cancelled. Call start() first."""
        assert self._server is not None, "start() must be called before serve_forever()"
        async with self._server:
            await self._server.serve_forever()


# -- CLI (smoke-test entry point, no Qt involved) --------------------------


def _cli_main() -> None:
    import argparse

    from it_toolbox.core.auth import gcp_auth

    parser = argparse.ArgumentParser(
        description="Open a native IAP TCP tunnel to a Compute Engine instance."
    )
    parser.add_argument("--project", required=True)
    parser.add_argument("--zone", required=True)
    parser.add_argument("--instance", required=True)
    parser.add_argument("--remote-port", type=int, required=True)
    parser.add_argument("--local-port", type=int, default=0)
    parser.add_argument("--interface", default="nic0")
    parser.add_argument(
        "--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"]
    )
    args = parser.parse_args()

    logging.basicConfig(level=args.log_level, format="%(asctime)s %(levelname)s %(message)s")

    target = IapTunnelTarget(
        project=args.project,
        zone=args.zone,
        instance=args.instance,
        port=args.remote_port,
        interface=args.interface,
    )

    async def run() -> None:
        # Mint a fresh token once for this whole CLI run; a long-lived GUI
        # session (M4+) should mint per-connection instead, since tokens
        # expire in ~1 hour.
        token = gcp_auth.get_credentials().token
        manager = TunnelManager(target, lambda: token)
        bound_port = await manager.start(local_port=args.local_port)
        print(f"Listening on 127.0.0.1:{bound_port} -> {args.instance}:{args.remote_port}")
        print(f"Try: ssh -p {bound_port} <user>@127.0.0.1  (or nc 127.0.0.1 {bound_port})")
        await manager.serve_forever()

    asyncio.run(run())


if __name__ == "__main__":
    _cli_main()
