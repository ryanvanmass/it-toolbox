"""QEMU/libvirt VM discovery and power control via the `virsh` CLI.

Shells out to `virsh` rather than binding to libvirt's C API (libvirt-python)
— `virsh -c {uri} ...` already transparently handles the `qemu+ssh://`
transport (spawning its own `ssh` under the hood), so there's no separate
tunnel/auth story to build for discovery and power actions, only for the
SPICE pixel/input stream itself (see core/spice/). Ported from
github.com/ryanvanmass/virt-connect's virsh_client.py, adapted to this
project's dataclass models and QemuApiError convention rather than
copy-pasted as-is.
"""

import re
import shutil
import subprocess
import xml.etree.ElementTree as ET

from it_toolbox.modules.connection_manager.models import QemuHost, QemuVm

VIRSH_CMD = "virsh"
VIRSH_TIMEOUT_SEC = 8


def is_available() -> bool:
    return shutil.which(VIRSH_CMD) is not None

_LIST_LINE_RE = re.compile(r"^\s*(\S+)\s+(\S+)\s+(.+?)\s*$")

_POWER_ACTIONS = {
    "start": "start",
    "shutdown": "shutdown",
    "pause": "suspend",
    "resume": "resume",
}


class QemuApiError(Exception):
    pass


def run_virsh(host: QemuHost, *args: str) -> str:
    try:
        result = subprocess.run(
            [VIRSH_CMD, "-c", host.uri, *args],
            capture_output=True,
            text=True,
            timeout=VIRSH_TIMEOUT_SEC,
        )
    except FileNotFoundError as e:
        raise QemuApiError("virsh not found — install libvirt-clients") from e
    except subprocess.TimeoutExpired as e:
        raise QemuApiError(f"virsh timed out connecting to {host.uri}") from e

    if result.returncode != 0:
        raise QemuApiError(result.stderr.strip() or f"virsh {' '.join(args)} failed")
    return result.stdout


def list_vms(host: QemuHost) -> list[QemuVm]:
    output = run_virsh(host, "list", "--all")
    lines = output.splitlines()

    vms: list[QemuVm] = []
    # First two lines are the header ("Id Name State") and a "---" separator.
    for line in lines[2:]:
        if not line.strip():
            continue
        match = _LIST_LINE_RE.match(line)
        if not match:
            continue
        vm_id, name, state = match.groups()
        vms.append(QemuVm(id=vm_id, name=name, state=state))

    return sorted(vms, key=lambda vm: vm.name.lower())


def get_vm_spice_port(host: QemuHost, vm_name: str) -> int | None:
    """The VM's SPICE port, or None if it has no SPICE graphics device, or
    its port hasn't been assigned yet (VM not currently running).
    """
    xml_text = run_virsh(host, "dumpxml", vm_name)
    root = ET.fromstring(xml_text)  # noqa: S314 - our own libvirt's own trusted output
    graphics = root.find(".//graphics[@type='spice']")
    if graphics is None:
        return None
    port = graphics.get("port")
    if port is None or port == "-1":
        return None
    return int(port)


def power_action(host: QemuHost, vm_name: str, action: str) -> None:
    virsh_command = _POWER_ACTIONS.get(action)
    if virsh_command is None:
        raise QemuApiError(f"Unknown power action: {action!r}")
    run_virsh(host, virsh_command, vm_name)


# Matches one data row of `virsh domifaddr` output, e.g.:
#   vnet0      52:54:00:36:2f:c1    ipv4         192.168.122.150/24
# The guest-agent source can also report rows with "-" in place of a
# name/MAC (loopback/link-local entries with no interface identity of
# their own), hence accepting "-" as well as a real MAC there.
_DOMIFADDR_LINE_RE = re.compile(
    r"^\s*(\S+)\s+([0-9a-fA-F:]{17}|-)\s+(ipv4|ipv6)\s+([0-9a-fA-F.:]+)/\d+\s*$"
)


def _parse_domifaddr_output(output: str) -> str | None:
    for line in output.splitlines():
        match = _DOMIFADDR_LINE_RE.match(line)
        if not match:
            continue
        _name, _mac, protocol, address = match.groups()
        if protocol != "ipv4" or address.startswith("127."):
            continue
        return address
    return None


def get_vm_ip_address(host: QemuHost, vm_name: str) -> str | None:
    """Best-effort guest IP discovery via `virsh domifaddr`, tried against
    each of libvirt's three sources in order of reliability: "agent" (an
    accurate, guest-reported address -- needs the QEMU guest agent
    installed and running in the guest), "lease" (libvirt's own DHCP
    lease record -- only populated for a NAT/isolated virtual network
    using libvirt's own dnsmasq, not a bridged one), then "arp" (the
    host's ARP cache -- ony has an entry if the host has actually talked
    to the guest recently, which needs them on the same bridged L2
    segment). Returns None if none of those sources have anything, in
    which case the caller should fall back to a manually-configured
    override (see settings.load_qemu_vm_ip_overrides) -- there's no
    guest IP tracked anywhere else in this app to fall back to.
    """
    for source in ("agent", "lease", "arp"):
        try:
            output = run_virsh(host, "domifaddr", vm_name, "--source", source)
        except QemuApiError:
            continue
        ip = _parse_domifaddr_output(output)
        if ip is not None:
            return ip
    return None
