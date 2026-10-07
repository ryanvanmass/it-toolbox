import json
import socket
import threading

import pytest

from it_toolbox.core.wsl import transport


def _accept_in_thread(listener):
    result = {}

    def target():
        try:
            result["value"] = listener.accept(timeout=5)
        except transport.TransportError as e:
            result["error"] = e

    thread = threading.Thread(target=target)
    thread.start()
    return thread, result


def test_handshake_and_round_trip():
    listener = transport.Listener()
    port, token = transport.parse_handshake_line(listener.handshake_line())
    thread, result = _accept_in_thread(listener)

    app = transport.connect(port, token, {"uri": "qemu:///system", "port": 5900})
    thread.join(5)
    helper, params = result["value"]

    assert params == {"uri": "qemu:///system", "port": 5900}
    big = bytes(range(256)) * 40_000  # ~10 MB, spans many recv() calls
    # Sent from another thread: a 10 MB sendall blocks until the other
    # side reads, exactly as it would between two real processes.
    sender = threading.Thread(target=helper.send, args=(transport.MSG_SERVICE_BASE, big))
    sender.start()
    assert app.recv() == (transport.MSG_SERVICE_BASE, big)
    sender.join(5)
    app.send(transport.MSG_STOP)
    assert helper.recv() == (transport.MSG_STOP, b"")

    app.close()
    with pytest.raises(EOFError):
        helper.recv()
    helper.close()


def test_wrong_token_is_dropped_and_listener_keeps_waiting():
    listener = transport.Listener()
    port, token = transport.parse_handshake_line(listener.handshake_line())
    thread, result = _accept_in_thread(listener)

    intruder = transport.connect(port, "0" * 32, {"evil": True})
    with pytest.raises(EOFError):
        intruder.recv()  # closed on us

    app = transport.connect(port, token, {"ok": True})
    thread.join(5)
    assert result["value"][1] == {"ok": True}
    app.close()
    result["value"][0].close()


def test_accept_times_out_without_a_client():
    listener = transport.Listener()
    with pytest.raises(transport.TransportError, match="never connected"):
        listener.accept(timeout=0.2)


def test_listener_binds_loopback_only():
    listener = transport.Listener()
    assert listener._server.getsockname()[0] == "127.0.0.1"
    listener._server.close()


def test_oversized_message_is_rejected():
    a, b = socket.socketpair()
    conn = transport.Connection.__new__(transport.Connection)
    conn._sock, conn._send_lock = b, threading.Lock()
    a.sendall(transport.HEADER.pack(transport.MAX_PAYLOAD + 1, 16))
    with pytest.raises(transport.TransportError, match="too large"):
        conn.recv()
    a.close()
    b.close()


@pytest.mark.parametrize("line", ["", "not json", json.dumps({"port": 1})])
def test_bad_handshake_line(line):
    with pytest.raises(transport.TransportError):
        transport.parse_handshake_line(line)
