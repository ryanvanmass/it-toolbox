import pytest

from it_toolbox.core.qemu_tunnel import QemuTunnel, QemuTunnelError, _parse_ssh_target, is_local_uri


@pytest.mark.parametrize(
    ("uri", "expected"),
    [
        ("qemu:///system", True),
        ("qemu:///session", True),
        ("qemu+ssh://alice@lab-host/system", False),
        ("qemu+ssh://lab-host/system", False),
    ],
)
def test_is_local_uri(uri, expected):
    assert is_local_uri(uri) is expected


@pytest.mark.parametrize(
    ("uri", "expected_target", "expected_port"),
    [
        ("qemu+ssh://alice@lab-host/system", "alice@lab-host", None),
        ("qemu+ssh://alice@lab-host:2222/system", "alice@lab-host", 2222),
        ("qemu+ssh://lab-host/system", "lab-host", None),
    ],
)
def test_parse_ssh_target(uri, expected_target, expected_port):
    target, port = _parse_ssh_target(uri)
    assert target == expected_target
    assert port == expected_port


def test_parse_ssh_target_rejects_non_ssh_scheme():
    with pytest.raises(QemuTunnelError, match="not an SSH-transport"):
        _parse_ssh_target("qemu:///system")


def test_parse_ssh_target_rejects_missing_host():
    with pytest.raises(QemuTunnelError, match="no host"):
        _parse_ssh_target("qemu+ssh:///system")


# QemuTunnel's own start()/stop() mechanics are SshTunnel's (see
# test_ssh_tunnel.py, which covers them directly) -- these just confirm
# QemuTunnel wires the parsed URI and the SPICE-specific "always
# 127.0.0.1 on the target" destination into the base class correctly.


def test_qemu_tunnel_wires_parsed_target_and_local_spice_destination():
    tunnel = QemuTunnel("qemu+ssh://alice@lab-host:2222/system", remote_port=5900)

    assert tunnel._target == "alice@lab-host"
    assert tunnel._ssh_port == 2222
    assert tunnel._dest_host == "127.0.0.1"
    assert tunnel._dest_port == 5900


def test_qemu_tunnel_rejects_non_ssh_uri_at_construction():
    with pytest.raises(QemuTunnelError, match="not an SSH-transport"):
        QemuTunnel("qemu:///system", remote_port=5900)
