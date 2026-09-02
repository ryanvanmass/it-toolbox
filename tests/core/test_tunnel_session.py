from it_toolbox.core.iap_tunnel import IapTunnelTarget
from it_toolbox.core.tunnel_session import BackgroundTunnel


def test_background_tunnel_start_and_stop_lifecycle():
    target = IapTunnelTarget(project="p", zone="z", instance="i", port=22)
    tunnel = BackgroundTunnel(target, get_access_token=lambda: "fake-token")

    port = tunnel.start(timeout=5)

    assert port > 0
    assert tunnel._thread.is_alive()

    tunnel.stop(timeout=5)

    assert not tunnel._thread.is_alive()
