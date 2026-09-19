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
    # Forcibly resets the guest -- the same as pressing a physical
    # machine's reset button; the guest OS gets no chance to shut down
    # cleanly first. Distinct from "shutdown" (a graceful ACPI request)
    # and from "start" (which does nothing to an already-running VM).
    "reset": "reset",
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
    return _parse_spice_port(xml_text)


def _parse_spice_port(xml_text: str) -> int | None:
    root = ET.fromstring(xml_text)  # noqa: S314 - our own libvirt's own trusted output
    graphics = root.find(".//graphics[@type='spice']")
    if graphics is None:
        return None
    port = graphics.get("port")
    if port is None or port == "-1":
        return None
    return int(port)


def diagnose_missing_spice_port(host: QemuHost, vm_name: str, vm_state: str) -> str:
    """Explains *why* get_vm_spice_port(host, vm_name) came back None, for
    a clearer error than a blanket "is it running?". That question is only
    actually right for one of several distinct cases this can mean:

    - The VM genuinely isn't running yet.
    - The VM has no SPICE graphics device at all -- e.g. it was created
      (outside this app) with VNC graphics instead, which looks identical
      from the tree/power-control side but was never going to get a SPICE
      port no matter how long it runs.
    - The VM's SPICE server is configured for TLS-only access (libvirt
      sets the plain `port` attribute to "-1" and puts the real,
      live-assigned port in `tlsPort` instead -- a default some admin
      tools, e.g. a remote-connection wizard, choose). This app's
      embedded SPICE client doesn't negotiate TLS, so this needs its own
      message rather than being reported as "not running" when it's
      actually up and reachable, just not via a plaintext port.
    """
    xml_text = run_virsh(host, "dumpxml", vm_name)
    root = ET.fromstring(xml_text)  # noqa: S314 - our own libvirt's own trusted output
    graphics = root.find(".//graphics[@type='spice']")

    if graphics is None:
        other = root.find(".//graphics")
        if other is not None:
            return (
                f"{vm_name} has no SPICE graphics device — its display is "
                f"configured for {other.get('type', 'a different protocol')!r} instead."
            )
        return f"{vm_name} has no graphics device configured at all."

    tls_port = graphics.get("tlsPort")
    if tls_port not in (None, "-1"):
        return (
            f"{vm_name}'s SPICE server is configured for TLS-only access "
            "(no plaintext port available), which this app doesn't support connecting to yet."
        )

    if vm_state != "running":
        return f"{vm_name} is not running (state: {vm_state})."

    return f"{vm_name} has no SPICE port available — is it running?"


def power_action(host: QemuHost, vm_name: str, action: str) -> None:
    virsh_command = _POWER_ACTIONS.get(action)
    if virsh_command is None:
        raise QemuApiError(f"Unknown power action: {action!r}")
    run_virsh(host, virsh_command, vm_name)
