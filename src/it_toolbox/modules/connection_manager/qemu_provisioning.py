"""QEMU/libvirt VM deployment and configuration.

Sibling to qemu_client.py (discovery/power), not an addition to it --
this file owns everything needed to actually *create* a VM and change
an existing one's resources, while qemu_client.py keeps its original
scope. Shares qemu_client.run_virsh as the one subprocess chokepoint
for virsh itself; VM creation additionally shells out to virt-install
(a separate CLI from the same libvirt/virt-manager toolchain, not a
new kind of dependency) via _run_virt_install below, for the same
reason qemu_client.py shells out to virsh rather than binding to
libvirt's C API: it already solves this exact problem correctly, so
this project doesn't have to own the domain-XML-generation correctness
itself.

Every output-parsing regex and virt-install/virsh flag here was
confirmed against a real, disposable local libvirt/QEMU host (nested
KVM), not assumed from documentation -- see docs/qemu-vm-provisioning-status.md
for what was actually verified. Two real findings from that verification
worth knowing before touching this file:

1. virt-install refuses to create a domain at all without an install
   method ("An install method must be specified") -- a spec with no
   ISO chosen uses --import (boot the fresh disk directly) rather than
   simply omitting --cdrom; there is no "just create a blank VM with no
   boot argument at all" option.
2. Disk target naming (hda/hdb/... vs vda/vdb/...) is whatever
   virt-install/the guest OS defaults chose for the existing disk(s),
   not something this project picks -- add_disk reads the VM's current
   targets via `domblklist` and increments the existing scheme's
   trailing letter, rather than assuming a fixed prefix.
"""

import re
import shutil
import subprocess

from it_toolbox.modules.connection_manager.models import QemuHost, StoragePool, StorageVolume, VirtualNetwork, VmCreateSpec
from it_toolbox.modules.connection_manager.qemu_client import QemuApiError, run_virsh

VIRT_INSTALL_CMD = "virt-install"
VIRT_INSTALL_TIMEOUT_SEC = 30

_POOL_LINE_RE = re.compile(r"^\s*(\S+)\s+(\S+)\s+(\S+)\s*$")
_NET_LINE_RE = re.compile(r"^\s*(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s*$")
# Name is always a single token; Path/Source may contain spaces (an
# unusual but real possibility for a custom pool location) -- same
# "last field is the tolerant one" approach qemu_client.list_vms
# already uses for its own multi-word STATE field.
_VOL_LINE_RE = re.compile(r"^\s*(\S+)\s+(.+?)\s*$")
_BLK_LINE_RE = re.compile(r"^\s*(\S+)\s+(.+?)\s*$")


def is_available() -> bool:
    """Whether VM *creation* is available. Resize/add-disk only need
    virsh, already covered by qemu_client.is_available() -- this is
    the separate, additional check the "Deploy VM…" UI gates on.
    """
    return shutil.which(VIRT_INSTALL_CMD) is not None


def _run_virt_install(*args: str) -> str:
    try:
        result = subprocess.run(
            [VIRT_INSTALL_CMD, *args],
            capture_output=True,
            text=True,
            timeout=VIRT_INSTALL_TIMEOUT_SEC,
        )
    except FileNotFoundError as e:
        raise QemuApiError("virt-install not found — install the virt-install/virtinst package") from e
    except subprocess.TimeoutExpired as e:
        raise QemuApiError("virt-install timed out") from e

    if result.returncode != 0:
        raise QemuApiError(result.stderr.strip() or result.stdout.strip() or "virt-install failed")
    return result.stdout


def list_storage_pools(host: QemuHost) -> list[StoragePool]:
    output = run_virsh(host, "pool-list", "--all")
    pools: list[StoragePool] = []
    for line in output.splitlines()[2:]:
        if not line.strip():
            continue
        match = _POOL_LINE_RE.match(line)
        if not match:
            continue
        name, state, _autostart = match.groups()
        pools.append(StoragePool(name=name, state=state))
    return sorted(pools, key=lambda pool: pool.name.lower())


def list_networks(host: QemuHost) -> list[VirtualNetwork]:
    output = run_virsh(host, "net-list", "--all")
    networks: list[VirtualNetwork] = []
    for line in output.splitlines()[2:]:
        if not line.strip():
            continue
        match = _NET_LINE_RE.match(line)
        if not match:
            continue
        name, state, _autostart, _persistent = match.groups()
        networks.append(VirtualNetwork(name=name, state=state))
    return sorted(networks, key=lambda net: net.name.lower())


def list_volumes(host: QemuHost, pool_name: str) -> list[StorageVolume]:
    output = run_virsh(host, "vol-list", pool_name)
    volumes: list[StorageVolume] = []
    for line in output.splitlines()[2:]:
        if not line.strip():
            continue
        match = _VOL_LINE_RE.match(line)
        if not match:
            continue
        name, path = match.groups()
        volumes.append(StorageVolume(name=name, path=path))
    return sorted(volumes, key=lambda vol: vol.name.lower())


def create_vm(host: QemuHost, spec: VmCreateSpec) -> None:
    argv = [
        "--connect", host.uri,
        "--name", spec.name,
        "--memory", str(spec.memory_mib),
        "--vcpus", str(spec.vcpus),
        "--disk", f"pool={spec.pool},size={spec.disk_gib},format=qcow2",
        "--network", f"network={spec.network}",
        "--os-variant", spec.os_variant or "generic",
        "--graphics", "spice",
        "--noautoconsole",
    ]
    # Confirmed live: virt-install requires an explicit install method
    # no matter what -- there's no "just create it with no boot source"
    # option. --import means "boot the disk we just created directly"
    # (a real, if empty, disk -- the closest equivalent to a blank VM).
    if spec.iso_path:
        argv += ["--cdrom", spec.iso_path]
    else:
        argv += ["--import"]
    _run_virt_install(*argv)


def _list_disk_targets(host: QemuHost, vm_name: str) -> list[str]:
    output = run_virsh(host, "domblklist", vm_name)
    targets = []
    for line in output.splitlines()[2:]:
        if not line.strip():
            continue
        match = _BLK_LINE_RE.match(line)
        if match:
            targets.append(match.group(1))
    return targets


def _next_disk_target(host: QemuHost, vm_name: str) -> str:
    """The next free disk device name, continuing whatever naming
    scheme (hda/hdb/…, vda/vdb/…) the VM's existing disk(s) already
    use -- confirmed live that virt-install's own default (not
    something this project chooses) can be either, so this reads it
    back rather than assuming.
    """
    targets = _list_disk_targets(host, vm_name)
    if not targets:
        raise QemuApiError(f"{vm_name} has no existing disks to determine the next device name from.")
    last = sorted(targets)[-1]
    prefix, letter = last[:-1], last[-1]
    if letter == "z":
        raise QemuApiError(f"{vm_name} already has the maximum number of single-letter disk targets.")
    return f"{prefix}{chr(ord(letter) + 1)}"


def resize_vm(host: QemuHost, vm_name: str, *, vcpus: int | None = None, memory_mib: int | None = None) -> None:
    """--config only, deliberately -- this is for a *stopped* VM's
    persistent configuration, never a running VM's live resources.
    The caller (ConfigureVmDialog) only ever offers this for a
    non-running VM in the first place; this is defense in depth, not
    the only place that's enforced.
    """
    if vcpus is not None:
        # --maximum alone doesn't change the *current* allocation --
        # confirmed live both calls are needed to actually take effect.
        run_virsh(host, "setvcpus", vm_name, str(vcpus), "--config", "--maximum")
        run_virsh(host, "setvcpus", vm_name, str(vcpus), "--config")
    if memory_mib is not None:
        memory_kib = str(memory_mib * 1024)
        run_virsh(host, "setmaxmem", vm_name, memory_kib, "--config")
        run_virsh(host, "setmem", vm_name, memory_kib, "--config")


def add_disk(host: QemuHost, vm_name: str, *, pool: str, size_gib: int) -> None:
    existing = len(_list_disk_targets(host, vm_name))
    volume_name = f"{vm_name}-disk-{existing + 1}.qcow2"
    run_virsh(host, "vol-create-as", pool, volume_name, f"{size_gib}G", "--format", "qcow2")
    volume_path = next((v.path for v in list_volumes(host, pool) if v.name == volume_name), None)
    if volume_path is None:
        raise QemuApiError(f"Created volume {volume_name!r} but couldn't find its path afterward.")
    target = _next_disk_target(host, vm_name)
    run_virsh(host, "attach-disk", vm_name, volume_path, target, "--config", "--persistent")
