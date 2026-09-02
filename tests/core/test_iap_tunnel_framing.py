import struct

import pytest

from it_toolbox.core import iap_tunnel as iap


def test_encode_data_frame_matches_protocol_layout():
    frame = iap.encode_data_frame(b"hello")
    tag, length = struct.unpack(">HI", frame[:6])
    assert tag == iap.TAG_DATA
    assert length == 5
    assert frame[6:] == b"hello"


def test_encode_data_frame_rejects_oversized_payload():
    with pytest.raises(ValueError):
        iap.encode_data_frame(b"x" * (iap.MAX_DATA_FRAME_SIZE + 1))


def test_encode_ack_frame_matches_protocol_layout():
    frame = iap.encode_ack_frame(123456)
    tag, count = struct.unpack(">HQ", frame)
    assert tag == iap.TAG_ACK
    assert count == 123456


def test_decode_data_frame_round_trip():
    frame = iap.encode_data_frame(b"payload bytes")
    decoded, remaining = iap.decode_frame(frame)
    assert decoded.tag == iap.TAG_DATA
    assert decoded.value == b"payload bytes"
    assert remaining == b""


def test_decode_ack_frame_round_trip():
    frame = iap.encode_ack_frame(42)
    decoded, remaining = iap.decode_frame(frame)
    assert decoded.tag == iap.TAG_ACK
    assert decoded.value == 42
    assert remaining == b""


def test_decode_connect_success_sid_frame():
    sid = b"opaque-session-id"
    frame = struct.pack(">HI", iap.TAG_CONNECT_SUCCESS_SID, len(sid)) + sid
    decoded, remaining = iap.decode_frame(frame)
    assert decoded.tag == iap.TAG_CONNECT_SUCCESS_SID
    assert decoded.value == sid
    assert remaining == b""


def test_decode_reconnect_success_ack_frame():
    frame = struct.pack(">HQ", iap.TAG_RECONNECT_SUCCESS_ACK, 999)
    decoded, remaining = iap.decode_frame(frame)
    assert decoded.tag == iap.TAG_RECONNECT_SUCCESS_ACK
    assert decoded.value == 999


def test_decode_frame_leaves_trailing_bytes_for_next_frame():
    combined = iap.encode_data_frame(b"first") + iap.encode_ack_frame(7)
    first, remaining = iap.decode_frame(combined)
    assert first.value == b"first"
    second, remaining = iap.decode_frame(remaining)
    assert second.tag == iap.TAG_ACK
    assert second.value == 7
    assert remaining == b""


@pytest.mark.parametrize(
    "partial",
    [
        b"",
        b"\x00",  # only 1 of 2 tag bytes
        struct.pack(">H", iap.TAG_DATA),  # tag only, no length
        struct.pack(">H", iap.TAG_DATA) + struct.pack(">I", 10),  # length but no payload
        struct.pack(">H", iap.TAG_ACK) + b"\x00\x00\x00",  # tag + partial ack count
    ],
)
def test_decode_frame_raises_incomplete_for_partial_buffers(partial):
    with pytest.raises(iap.IncompleteFrame):
        iap.decode_frame(partial)


def test_decode_frame_raises_protocol_error_for_unknown_tag():
    frame = struct.pack(">H", 0xFFFF)
    with pytest.raises(iap.ProtocolError):
        iap.decode_frame(frame)


def test_connect_url_contains_expected_query_params():
    target = iap.IapTunnelTarget(
        project="my-project", zone="us-central1-a", instance="my-vm", port=22
    )
    url = iap._connect_url(target)
    assert url.startswith(f"wss://{iap.WS_URL_HOST}{iap.WS_URL_PATH_ROOT}/connect?")
    assert "project=my-project" in url
    assert "zone=us-central1-a" in url
    assert "instance=my-vm" in url
    assert "interface=nic0" in url
    assert "port=22" in url
    assert "newWebsocket=True" in url


def test_reconnect_url_contains_sid_and_ack_offset():
    target = iap.IapTunnelTarget(
        project="my-project", zone="us-central1-a", instance="my-vm", port=22
    )
    url = iap._reconnect_url(target, sid=b"abc123", ack_bytes=4096)
    assert url.startswith(f"wss://{iap.WS_URL_HOST}{iap.WS_URL_PATH_ROOT}/reconnect?")
    assert "sid=abc123" in url
    assert "ack=4096" in url
    assert "zone=us-central1-a" in url


class _FakeConnection(iap.IapTunnelConnection):
    """Bypasses real websocket I/O to unit-test the ack/confirm bookkeeping."""

    def __init__(self):
        target = iap.IapTunnelTarget(project="p", zone="z", instance="i", port=22)
        super().__init__(target, get_access_token=lambda: "fake-token")


def test_confirm_bytes_discards_fully_confirmed_chunks():
    conn = _FakeConnection()
    conn._unconfirmed = [b"aaaa", b"bbbb"]
    conn._confirm_bytes(4)
    assert conn._unconfirmed == [b"bbbb"]
    assert conn._total_bytes_confirmed == 4


def test_confirm_bytes_partially_confirms_a_chunk():
    conn = _FakeConnection()
    conn._unconfirmed = [b"aaaaaaaa"]
    conn._confirm_bytes(3)
    assert conn._unconfirmed == [b"aaaaa"]
    assert conn._total_bytes_confirmed == 3


def test_confirm_bytes_rejects_out_of_order_ack():
    conn = _FakeConnection()
    conn._total_bytes_confirmed = 100
    with pytest.raises(iap.ProtocolError):
        conn._confirm_bytes(50)


def test_confirm_bytes_rejects_confirming_more_than_was_ever_sent():
    conn = _FakeConnection()
    conn._unconfirmed = [b"aaaa"]
    with pytest.raises(iap.ProtocolError):
        conn._confirm_bytes(999)
