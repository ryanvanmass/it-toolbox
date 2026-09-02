import asyncio

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
