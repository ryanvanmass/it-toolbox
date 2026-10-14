import asyncio
import websockets

from it_toolbox.core import iap_tunnel as iap


def test_tunnel_manager_start_binds_an_ephemeral_local_port():
    target = iap.IapTunnelTarget(project="p", zone="z", instance="i", port=22)
    manager = iap.TunnelManager(target, get_access_token=lambda: "fake-token")

    async def check():
        port = await manager.start(local_port=0)
        assert port > 0
        manager._server.close()
        await manager._server.wait_closed()

    asyncio.run(check())


def _refusing_relay(code, reason):
    """A local stand-in for the IAP relay that accepts the websocket and
    then closes it with `code`, the way the real relay refuses a tunnel."""

    async def handler(ws):
        await ws.close(code, reason)

    return websockets.serve(handler, "127.0.0.1", 0, subprotocols=[iap.SUBPROTOCOL_NAME])


def test_a_relay_refusal_fails_the_tunnel_at_once_with_its_reason(monkeypatch):
    target = iap.IapTunnelTarget(project="p", zone="z", instance="i", port=3389)
    manager = iap.TunnelManager(target, get_access_token=lambda: "fake-token")

    async def check():
        async with _refusing_relay(4003, "failed to connect to backend") as relay:
            relay_port = relay.sockets[0].getsockname()[1]
            monkeypatch.setattr(iap, "_connect_url", lambda t: f"ws://127.0.0.1:{relay_port}")
            port = await manager.start(local_port=0)
            reader, writer = await asyncio.open_connection("127.0.0.1", port)
            # The local client sees the connection end instead of hanging
            # while the tunnel retries for minutes.
            assert await asyncio.wait_for(reader.read(), timeout=5) == b""
            writer.close()
            manager._server.close()
            await manager._server.wait_closed()

    asyncio.run(check())

    assert isinstance(manager.last_error, iap.IapTunnelError)
    assert manager.last_error.code == 4003
    assert "failed to connect to backend" in str(manager.last_error)
    assert "35.235.240.0/20 to that port" in str(manager.last_error)
