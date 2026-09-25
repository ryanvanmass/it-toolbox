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

import os
import re
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET

from it_toolbox.modules.connection_manager.models import (
    QemuHost,
    StoragePool,
    StorageVolume,
    VirtualNetwork,
    VmCreateSpec,
    VmDisk,
    VmNetworkInterface,
)
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
# `domblklist --details` -- Type/Device/Target/Source, confirmed live;
# Source is "-" for an empty cdrom slot, a real path otherwise (tolerant
# of spaces in the path, same reasoning as _VOL_LINE_RE above).
_BLK_DETAILS_LINE_RE = re.compile(r"^\s*(\S+)\s+(\S+)\s+(\S+)\s+(.+?)\s*$")
# `domiflist` -- Interface/Type/Source/Model/MAC, all single tokens.
_IFACE_LINE_RE = re.compile(r"^\s*(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s*$")


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


def list_os_variants() -> list[str]:
    """Every --os-variant/--osinfo short ID virt-install actually
    accepts (confirmed live: ~940 entries, "generic" included). This is
    a purely local osinfo-db lookup -- unlike everything else in this
    module, it takes no QemuHost/--connect at all, since it doesn't
    vary per libvirt host.
    """
    output = _run_virt_install("--osinfo", "list")
    return [line.strip() for line in output.splitlines() if line.strip()]


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


def _next_virtio_disk_target(host: QemuHost, vm_name: str) -> str:
    """Like _next_disk_target, but always finds the next free "vd*"
    target specifically, regardless of what bus the VM's *other* disks
    use -- for add_disk's live=True path, where the new disk's target
    must actually be virtio for hot-attach to succeed at all (see that
    docstring), independent of whatever the boot disk happens to be.
    """
    virtio_targets = sorted(t for t in _list_disk_targets(host, vm_name) if t.startswith("vd"))
    if not virtio_targets:
        return "vda"
    letter = virtio_targets[-1][-1]
    if letter == "z":
        raise QemuApiError(f"{vm_name} already has the maximum number of virtio disk targets.")
    return f"vd{chr(ord(letter) + 1)}"


def get_vm_resources(host: QemuHost, vm_name: str) -> tuple[int, int]:
    """Current (vcpus, memory_mib) read from the VM's persistent
    definition (dumpxml) -- matches what resize_vm's --config-only
    changes actually affect, so ConfigureVmDialog can pre-fill its
    fields with the values a save will actually be relative to.
    Confirmed live: libvirt's dumpxml always normalizes <currentMemory>
    to KiB regardless of what unit a VM was originally defined with.
    """
    xml_text = run_virsh(host, "dumpxml", vm_name)
    root = ET.fromstring(xml_text)  # noqa: S314 - our own libvirt's own trusted output
    vcpu_el = root.find("vcpu")
    memory_el = root.find("currentMemory")
    vcpus = int(vcpu_el.text) if vcpu_el is not None and vcpu_el.text else 1
    memory_kib = int(memory_el.text) if memory_el is not None and memory_el.text else 0
    return vcpus, memory_kib // 1024


def resize_vm(host: QemuHost, vm_name: str, *, vcpus: int | None = None, memory_mib: int | None = None) -> None:
    """--config only, deliberately, regardless of whether the VM happens
    to be running -- confirmed live that a real vCPU *reduction* is
    flatly rejected as `--live` ("failed to find appropriate
    hotpluggable vcpus") for a normally-provisioned VM, and that
    `--config` alone on a running VM succeeds but has zero effect on its
    current live allocation (confirmed via `vcpucount`) -- i.e. this
    always just stages the change for the VM's next boot. `ConfigureVmDialog`
    now allows opening this for a running VM too (per explicit product
    decision -- vCPU/memory just isn't a *live* operation here), labeling
    the change accordingly rather than pretending it applies immediately.
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


def add_disk(host: QemuHost, vm_name: str, *, pool: str, size_gib: int, live: bool = False) -> None:
    """`--config --persistent` (no explicit `--live` flag) already
    hot-attaches immediately on a running VM in addition to persisting,
    *when the target ends up virtio* -- but confirmed live this is NOT
    reliable in general: continuing whatever scheme the VM's existing
    disks already use (_next_disk_target, the non-live default below)
    produces another IDE target for a VM whose boot disk is IDE --
    virt-install's own default for a plain "generic" os-variant, i.e.
    this app's own common case -- and IDE disks flatly refuse to
    hotplug at all ("disk bus 'ide' cannot be hotplugged"). Worse, the
    *entire* attach-disk call then fails outright, not just its live
    half -- nothing gets persisted either.

    `live=True` avoids this by forcing the new disk onto an explicit
    virtio target/bus (`_next_virtio_disk_target`, `--targetbus
    virtio`) regardless of what bus the VM's *other* disks use --
    confirmed live this succeeds even when the boot disk itself is IDE
    (mixing an IDE boot disk with virtio data disks is a normal, valid,
    confirmed-working QEMU/libvirt configuration). When not live, the
    original scheme-continuing behavior is unchanged.
    """
    existing = len(_list_disk_targets(host, vm_name))
    volume_name = f"{vm_name}-disk-{existing + 1}.qcow2"
    run_virsh(host, "vol-create-as", pool, volume_name, f"{size_gib}G", "--format", "qcow2")
    volume_path = next((v.path for v in list_volumes(host, pool) if v.name == volume_name), None)
    if volume_path is None:
        raise QemuApiError(f"Created volume {volume_name!r} but couldn't find its path afterward.")
    if live:
        target = _next_virtio_disk_target(host, vm_name)
        run_virsh(
            host, "attach-disk", vm_name, volume_path, target,
            "--targetbus", "virtio", "--config", "--persistent",
        )
    else:
        target = _next_disk_target(host, vm_name)
        run_virsh(host, "attach-disk", vm_name, volume_path, target, "--config", "--persistent")


def list_disks(host: QemuHost, vm_name: str) -> list[VmDisk]:
    """Every block device (real disks *and* any cdrom slot) -- confirmed
    live that `--details` is what actually distinguishes device kind
    ("disk" vs "cdrom"), and that a VM created without an ISO chosen at
    deploy time (create_vm's --import path) has no cdrom device at all,
    while one created with an ISO does -- ConfigureVmDialog only offers
    CD-ROM media management when a cdrom entry is actually present here.
    """
    output = run_virsh(host, "domblklist", vm_name, "--details")
    disks: list[VmDisk] = []
    for line in output.splitlines()[2:]:
        if not line.strip():
            continue
        match = _BLK_DETAILS_LINE_RE.match(line)
        if not match:
            continue
        _type, device, target, source = match.groups()
        disks.append(VmDisk(target=target, device=device, source=None if source == "-" else source))
    return disks


def remove_disk(host: QemuHost, vm_name: str, target: str, *, live: bool = False) -> None:
    """Detaches the disk from the VM's config -- deliberately does NOT
    delete the underlying volume file (confirmed live: `detach-disk`
    alone leaves it completely untouched), the same "never destroy real
    data as a side effect" principle as everywhere else in this module.
    An admin who actually wants the file gone can do that separately
    (outside this module, for now -- see docs/qemu-vm-provisioning-status.md's
    Deferred section).

    `live=True` uses `--live --config` instead of the stopped-VM case's
    `--config --persistent` -- confirmed live that combining all three
    (`--config --persistent --live`) is untested and `--persistent`'s
    exact interaction with an explicit `--live` is unclear, whereas
    `--live --config` together is the same, directly-confirmed-working
    combination change_cdrom_media uses. Even so, this is genuinely
    unreliable: `virsh` reported "Disk detached successfully"
    immediately in a real test, yet the disk was still fully attached
    and visible 5+ seconds later, since disk hot-*removal* (unlike
    hot-*add*, see add_disk) needs the guest OS to actually acknowledge
    releasing the device, which doesn't happen at all without a real,
    cooperating guest driver. The caller (ConfigureVmDialog) surfaces
    this as a warning rather than a guarantee -- there's no reliable way
    to force it from here.
    """
    flags = ["--live", "--config"] if live else ["--config", "--persistent"]
    run_virsh(host, "detach-disk", vm_name, target, *flags)


def list_network_interfaces(host: QemuHost, vm_name: str) -> list[VmNetworkInterface]:
    output = run_virsh(host, "domiflist", vm_name)
    interfaces: list[VmNetworkInterface] = []
    for line in output.splitlines()[2:]:
        if not line.strip():
            continue
        match = _IFACE_LINE_RE.match(line)
        if not match:
            continue
        _interface, _type, source, model, mac = match.groups()
        interfaces.append(VmNetworkInterface(mac=mac, network=source, model=model))
    return interfaces


def change_network(host: QemuHost, vm_name: str, *, old_mac: str, new_network: str, live: bool = False) -> None:
    """Confirmed live: there's no "just change the source" virsh call --
    changing a NIC's network is detach-then-attach (a new MAC gets
    assigned to the new interface; nothing preserves the old one).

    `live=True` additionally passes `--live` to both calls for a running
    VM -- but the detach half has the same real reliability caveat as
    remove_disk's own: confirmed live that `detach-interface --live`
    reports success immediately while the interface was still fully
    present 2+ seconds later, since NIC hot-*removal* also needs the
    guest OS to actually release it. The caller (ConfigureVmDialog)
    surfaces this as a warning, not a guarantee.
    """
    detach_flags = ["--config", "--live"] if live else ["--config"]
    attach_flags = ["--model", "virtio", "--config", "--live"] if live else ["--model", "virtio", "--config"]
    run_virsh(host, "detach-interface", vm_name, "network", "--mac", old_mac, *detach_flags)
    run_virsh(host, "attach-interface", vm_name, "network", new_network, *attach_flags)


_DISPLAY_DEVICES = ("spice", "vnc")


def get_vm_display_device(host: QemuHost, vm_name: str) -> str | None:
    """The VM's currently configured display/graphics device type
    ("spice", "vnc", ...), or None if it has no graphics device at all.
    Feeds ConfigureVmDialog's Display section, so a VM that ended up with
    VNC graphics instead of SPICE (see qemu_client.diagnose_missing_spice_port,
    which is exactly the "no SPICE port" symptom that causes) can be
    switched back without hand-editing XML.
    """
    xml_text = run_virsh(host, "dumpxml", vm_name)
    root = ET.fromstring(xml_text)  # noqa: S314 - our own libvirt's own trusted output
    graphics = root.find(".//graphics")
    return graphics.get("type") if graphics is not None else None


def set_display_device(host: QemuHost, vm_name: str, graphics_type: str) -> None:
    """Changes the VM's display device type -- e.g. recovering a VM that
    ended up with VNC graphics instead of SPICE. Not a live/hot-pluggable
    change -- there's no attach-graphics/detach-graphics the way there is
    for disks and interfaces, and libvirt doesn't support changing a
    graphics device's type on a running domain at all -- like resize_vm,
    this only rewrites the VM's persistent definition; it takes effect
    the next time the VM (re)starts, regardless of whether it's running
    right now.

    The only way to change a device's *type* (as opposed to a property of
    the same device) is to redefine the whole domain: read the current
    XML, replace the <graphics> element outright (dropping whatever
    port/tlsPort/passwd attributes the old type had -- they don't apply
    to the new one; autoport="yes" lets libvirt assign a fresh port), and
    `virsh define` the result back.
    """
    if graphics_type not in _DISPLAY_DEVICES:
        raise QemuApiError(f"Unsupported display device: {graphics_type!r}")

    xml_text = run_virsh(host, "dumpxml", vm_name)
    root = ET.fromstring(xml_text)  # noqa: S314 - our own libvirt's own trusted output
    devices = root.find("devices")
    if devices is None:
        raise QemuApiError(f"{vm_name} has no <devices> section to configure a display device on.")

    graphics = devices.find("graphics")
    if graphics is None:
        graphics = ET.SubElement(devices, "graphics")
    else:
        # Drop any nested <listen> child along with the old type's
        # attributes -- it may disagree with the listen="..." attribute
        # set below, which modern libvirt treats as an error rather than
        # silently preferring one over the other.
        for listen_el in list(graphics):
            if listen_el.tag == "listen":
                graphics.remove(listen_el)
        graphics.attrib.clear()
    graphics.set("type", graphics_type)
    graphics.set("autoport", "yes")
    # This app's whole QEMU/SPICE connection model (see qemu_tunnel.py)
    # assumes every graphics server is bound to localhost only, reached
    # through an SSH tunnel rather than exposed on the network -- keep
    # that restriction explicitly rather than letting a freshly-redefined
    # device fall back to libvirt's own (public) default listen address.
    graphics.set("listen", "127.0.0.1")

    _redefine(host, root)


def _redefine(host: QemuHost, root: ET.Element) -> None:
    """Writes `root` to a temp file and `virsh define`s it back -- the
    only way to change something (like a device's type, or the OS boot
    order) that virsh has no dedicated attach/detach/set convenience call
    for. Shared by set_display_device and set_boot_order.
    """
    with tempfile.NamedTemporaryFile("w", suffix=".xml", delete=False) as f:
        f.write(ET.tostring(root, encoding="unicode"))
        temp_path = f.name
    try:
        run_virsh(host, "define", temp_path)
    finally:
        os.unlink(temp_path)


_BOOT_DEVICES = ("hd", "cdrom", "network", "fd")
# <os>'s own child elements that must precede any <boot dev='...'/>
# entries -- confirmed against libvirt's domain XML schema/docs, not
# assumed: <type> is required and always first; <loader>/<nvram> (UEFI
# firmware) and <bootloader>/<bootloader_args> (paravirt-only, not used
# by this app) come next when present. Inserting new <boot> elements
# right after whichever of these actually exist -- rather than just
# appending them at the very end of <os> -- keeps them ahead of
# <bootmenu>/<bios>/<smbios>, which must come after.
_OS_ELEMENTS_BEFORE_BOOT = ("type", "loader", "nvram", "bootloader", "bootloader_args")


def get_boot_order(host: QemuHost, vm_name: str) -> list[str]:
    """The VM's current boot device order, as libvirt boot device names
    ("hd", "cdrom", "network", "fd"), read from the OS-level
    <os><boot dev='...'/></os> list -- the simpler of libvirt's two boot-
    order schemes (the other being a per-device <boot order='N'/> on
    individual disks/interfaces) and what virt-install itself uses for
    VMs this app creates. Empty if none are set (the VM boots whatever
    its firmware's own natural device order picks, unmanaged by this
    app).
    """
    xml_text = run_virsh(host, "dumpxml", vm_name)
    root = ET.fromstring(xml_text)  # noqa: S314 - our own libvirt's own trusted output
    os_el = root.find("os")
    if os_el is None:
        return []
    return [dev for boot_el in os_el.findall("boot") if (dev := boot_el.get("dev")) is not None]


def set_boot_order(host: QemuHost, vm_name: str, order: list[str]) -> None:
    """Rewrites the VM's OS-level boot device order. Not a live change --
    like set_display_device, this only rewrites the persistent
    definition (there's no meaningful "change what the running guest
    boots from next" short of a reboot, which makes this moot anyway);
    it takes effect the VM's next (re)start.

    libvirt refuses to mix the OS-level <os><boot dev='...'/></os> scheme
    with a per-device <boot order='N'/> on individual disks/interfaces --
    since this app only ever manages the OS-level scheme, any leftover
    per-device order (e.g. set outside this app, by virt-manager or a
    hand edit) is stripped from every device first so the two can't
    conflict.
    """
    invalid = [d for d in order if d not in _BOOT_DEVICES]
    if invalid:
        raise QemuApiError(f"Unsupported boot device(s): {invalid!r}")

    xml_text = run_virsh(host, "dumpxml", vm_name)
    root = ET.fromstring(xml_text)  # noqa: S314 - our own libvirt's own trusted output
    os_el = root.find("os")
    if os_el is None:
        raise QemuApiError(f"{vm_name} has no <os> section to set a boot order on.")

    for boot_el in os_el.findall("boot"):
        os_el.remove(boot_el)
    insert_at = 0
    for i, child in enumerate(os_el):
        if child.tag in _OS_ELEMENTS_BEFORE_BOOT:
            insert_at = i + 1
    for offset, dev in enumerate(order):
        os_el.insert(insert_at + offset, ET.Element("boot", {"dev": dev}))

    devices = root.find("devices")
    if devices is not None:
        for device_el in devices:
            for boot_el in device_el.findall("boot"):
                device_el.remove(boot_el)

    _redefine(host, root)


def change_cdrom_media(host: QemuHost, vm_name: str, target: str, iso_path: str | None, *, live: bool = False) -> None:
    """iso_path=None leaves the drive ejected/empty; otherwise inserts
    the given ISO, swapping out whatever (if anything) was already
    there. Confirmed live: `change-media --insert` flatly refuses if
    the drive already has media ("already has media"), and `--eject`
    flatly refuses if it's already empty ("doesn't have media") -- so a
    real swap always ejects first, tolerating that specific "already
    empty" failure as a no-op (a drive with nothing in it is exactly
    the state an eject is trying to reach anyway), then inserts only if
    new media was actually requested.

    `live=True` additionally passes `--live` to both calls for a running
    VM -- confirmed live, unlike disk/network hot-*removal*, media
    change is genuinely reliable this way: eject and insert both took
    effect immediately and were reflected in `domblklist` right away,
    no guest cooperation needed (it's a much simpler operation than a
    full PCI device hot-unplug).
    """
    flags = ["--config", "--live"] if live else ["--config"]
    try:
        run_virsh(host, "change-media", vm_name, target, "--eject", *flags)
    except QemuApiError as e:
        if "doesn't have media" not in str(e):
            raise
    if iso_path is not None:
        run_virsh(host, "change-media", vm_name, target, "--insert", iso_path, *flags)
