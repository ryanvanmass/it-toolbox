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
import subprocess
import xml.etree.ElementTree as ET

from it_toolbox.modules.connection_manager.models import QemuHost, QemuVm

VIRSH_TIMEOUT_SEC = 8

_LIST_LINE_RE = re.compile(r"^\s*(\S+)\s+(\S+)\s+(.+?)\s*$")

_POWER_ACTIONS = {
    "start": "start",
    "shutdown": "shutdown",
    "pause": "suspend",
    "resume": "resume",
}


class QemuApiError(Exception):
    pass


def _run_virsh(host: QemuHost, *args: str) -> str:
    try:
        result = subprocess.run(
            ["virsh", "-c", host.uri, *args],
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
    output = _run_virsh(host, "list", "--all")
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
    xml_text = _run_virsh(host, "dumpxml", vm_name)
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
    _run_virsh(host, virsh_command, vm_name)
