"""SSH local-port-forward tunnel to reach a libvirt-managed VM's SPICE port.

libvirt-managed VMs conventionally bind their SPICE server to 127.0.0.1 on
the host — a secure default. `virsh`/`virt-viewer` reach it because *they*
set up an SSH tunnel transparently as part of the `qemu+ssh://` connection
dance. Since this app's embedded SPICE client connects to the SPICE port
directly (bypassing virt-viewer entirely, see docs/qemu-spice-status.md),
it has to open that tunnel itself.

This is libvirt-specific URI parsing on top of the generic spawn/wait/
teardown mechanics in core/ssh_tunnel.py — see that module's own
docstring for why the split happened (a second caller needed the same
mechanics but a configurable destination host, not always 127.0.0.1).
"""

from urllib.parse import urlsplit

from it_toolbox.core.ssh_tunnel import SshTunnel, SshTunnelError

# Kept as an alias, not a fresh subclass -- existing callers/tests
# (including this module's own) import QemuTunnelError specifically, and
# every failure this module can actually raise originates from
# SshTunnel.start() itself.
QemuTunnelError = SshTunnelError


def is_local_uri(uri: str) -> bool:
    """True for a bare local libvirt connection -- "qemu:///system" or
    "qemu:///session", no host component at all -- meaning the libvirt
    daemon (and so the VM/its SPICE server) already runs on this same
    machine. SPICE's 127.0.0.1 bind is then already directly reachable
    with no tunnel at all -- QemuTunnel exists specifically for the
    qemu+ssh:// case, where the SPICE port lives on a genuinely different
    machine and needs an SSH-forwarded local port to reach it from here.
    Confirmed live: a QemuHost pointed at the *same* machine running
    it-toolbox (a real, valid libvirt setup, not just a remote lab host)
    previously always failed to connect, since the caller unconditionally
    tried to build an SSH tunnel for every QEMU host regardless of URI.
    """
    return urlsplit(uri).scheme == "qemu"


def _parse_ssh_target(uri: str) -> tuple[str, int | None]:
    """Extract an ssh(1) "[user@]host" target and optional port from a
    qemu+ssh:// libvirt connection URI, e.g. "qemu+ssh://alice@lab-host:2222/system".
    """
    parsed = urlsplit(uri)
    if parsed.scheme != "qemu+ssh":
        raise QemuTunnelError(f"not an SSH-transport libvirt URI: {uri!r}")
    if not parsed.hostname:
        raise QemuTunnelError(f"no host in libvirt URI: {uri!r}")

    target = f"{parsed.username}@{parsed.hostname}" if parsed.username else parsed.hostname
    return target, parsed.port


class QemuTunnel(SshTunnel):
    """SshTunnel specialized for qemu+ssh:// libvirt URIs -- always
    forwards to 127.0.0.1 on the SSH target, since libvirt-managed VMs
    conventionally bind SPICE to localhost on the same host virsh
    connects to (unlike a general SSH gateway, which just as often
    forwards to some *other* host on its own network -- see
    core/ssh_tunnel.py's docstring).
    """

    def __init__(self, uri: str, remote_port: int) -> None:
        target, ssh_port = _parse_ssh_target(uri)
        super().__init__(target, "127.0.0.1", remote_port, ssh_port=ssh_port)
