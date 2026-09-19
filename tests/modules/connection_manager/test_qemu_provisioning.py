import subprocess

import pytest

from it_toolbox.modules.connection_manager import qemu_provisioning
from it_toolbox.modules.connection_manager.models import QemuHost, VmCreateSpec

HOST = QemuHost(name="lab", uri="qemu+ssh://user@lab-host/system")

# Real output captured live from a disposable local libvirt/QEMU host
# (nested KVM), not hand-typed from memory or docs -- see
# docs/qemu-vm-provisioning-status.md.
_REAL_POOL_LIST = " Name      State    Autostart\n-------------------------------\n default   active   yes\n"
_REAL_NET_LIST = (
    " Name      State    Autostart   Persistent\n"
    "--------------------------------------------\n"
    " default   active   yes         yes\n"
)
_REAL_VOL_LIST = (
    " Name             Path\n"
    "----------------------------------------------------------\n"
    " test.iso         /var/lib/libvirt/images/test.iso\n"
    " testdisk.qcow2   /var/lib/libvirt/images/testdisk.qcow2\n"
)
_REAL_BLK_LIST_ONE_DISK = (
    " Target   Source\n"
    "-------------------------------------------\n"
    " hda      /var/lib/libvirt/images/testvm1.qcow2\n"
)
_REAL_BLK_LIST_TWO_DISKS = (
    " Target   Source\n"
    "-------------------------------------------\n"
    " hda      /var/lib/libvirt/images/testvm1.qcow2\n"
    " hdb      /var/lib/libvirt/images/testvm1-disk-2.qcow2\n"
)
# An IDE boot disk plus a virtio data disk -- a normal, valid mix
# (confirmed live: mixing buses on one VM works fine), and the shape
# add_disk(live=True) needs to handle correctly when picking the next
# free *virtio* target specifically, ignoring the unrelated IDE one.
_REAL_BLK_LIST_IDE_BOOT_PLUS_VIRTIO_DATA = (
    " Target   Source\n"
    "-------------------------------------------\n"
    " hda      /var/lib/libvirt/images/testvm1.qcow2\n"
    " vdb      /var/lib/libvirt/images/testvm1-disk-2.qcow2\n"
)
_REAL_VOL_LIST_AFTER_ADD_DISK = (
    " Name                Path\n"
    "----------------------------------------------------------\n"
    " myvm-disk-2.qcow2   /var/lib/libvirt/images/myvm-disk-2.qcow2\n"
)
_REAL_DUMPXML_RESOURCES = """<domain type='kvm'>
  <name>testvm1</name>
  <memory unit='KiB'>1048576</memory>
  <currentMemory unit='KiB'>1048576</currentMemory>
  <vcpu placement='static'>2</vcpu>
</domain>"""
# The exact error virt-install gives for a disk-only spec with no boot
# source -- confirmed live this is a real, hard requirement, not
# something specific to this project's own argv construction.
_REAL_NO_INSTALL_METHOD_ERROR = (
    "ERROR    \nAn install method must be specified\n"
    "(--location URL, --cdrom CD/ISO, --pxe, --import, --boot hd|cdrom|...)\n"
)


def _completed(stdout="", stderr="", returncode=0):
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


def test_list_os_variants_parses_real_output(monkeypatch):
    real_output = "almalinux10\nalmalinux9\ngeneric\nwin11\n"
    calls = []
    monkeypatch.setattr(
        qemu_provisioning.subprocess, "run",
        lambda cmd, capture_output, text, timeout: calls.append(cmd) or _completed(stdout=real_output),
    )
    assert qemu_provisioning.list_os_variants() == ["almalinux10", "almalinux9", "generic", "win11"]
    assert calls == [["virt-install", "--osinfo", "list"]]


def test_list_storage_pools_parses_real_output(monkeypatch):
    monkeypatch.setattr(
        qemu_provisioning.subprocess, "run", lambda *a, **k: _completed(stdout=_REAL_POOL_LIST)
    )
    pools = qemu_provisioning.list_storage_pools(HOST)
    assert [(p.name, p.state) for p in pools] == [("default", "active")]


def test_list_networks_parses_real_output(monkeypatch):
    monkeypatch.setattr(
        qemu_provisioning.subprocess, "run", lambda *a, **k: _completed(stdout=_REAL_NET_LIST)
    )
    networks = qemu_provisioning.list_networks(HOST)
    assert [(n.name, n.state) for n in networks] == [("default", "active")]


def test_list_volumes_parses_real_output_and_sorts_by_name(monkeypatch):
    monkeypatch.setattr(
        qemu_provisioning.subprocess, "run", lambda *a, **k: _completed(stdout=_REAL_VOL_LIST)
    )
    volumes = qemu_provisioning.list_volumes(HOST, "default")
    assert [(v.name, v.path) for v in volumes] == [
        ("test.iso", "/var/lib/libvirt/images/test.iso"),
        ("testdisk.qcow2", "/var/lib/libvirt/images/testdisk.qcow2"),
    ]


def test_create_vm_with_iso_uses_cdrom_not_import(monkeypatch):
    calls = []

    def fake_run(cmd, capture_output, text, timeout):
        calls.append(cmd)
        return _completed()

    monkeypatch.setattr(qemu_provisioning.subprocess, "run", fake_run)

    spec = VmCreateSpec(
        name="myvm", memory_mib=2048, vcpus=2, disk_gib=20, pool="default", network="default",
        os_variant="generic", iso_path="/var/lib/libvirt/images/install.iso",
    )
    qemu_provisioning.create_vm(HOST, spec)

    (argv,) = calls
    assert argv[0] == "virt-install"
    assert "--connect" in argv and argv[argv.index("--connect") + 1] == HOST.uri
    assert "--cdrom" in argv and argv[argv.index("--cdrom") + 1] == "/var/lib/libvirt/images/install.iso"
    assert "--import" not in argv
    assert "--disk" in argv and argv[argv.index("--disk") + 1] == "pool=default,size=20,format=qcow2"
    assert "--noautoconsole" in argv


def test_create_vm_without_iso_uses_import(monkeypatch):
    calls = []
    monkeypatch.setattr(
        qemu_provisioning.subprocess, "run",
        lambda cmd, capture_output, text, timeout: calls.append(cmd) or _completed(),
    )

    spec = VmCreateSpec(
        name="myvm", memory_mib=1024, vcpus=1, disk_gib=10, pool="default", network="default",
        os_variant="generic",
    )
    qemu_provisioning.create_vm(HOST, spec)

    (argv,) = calls
    assert "--import" in argv
    assert "--cdrom" not in argv


def test_create_vm_raises_helpful_error_on_virt_install_failure(monkeypatch):
    monkeypatch.setattr(
        qemu_provisioning.subprocess, "run",
        lambda *a, **k: _completed(returncode=1, stderr=_REAL_NO_INSTALL_METHOD_ERROR),
    )
    spec = VmCreateSpec(
        name="myvm", memory_mib=1024, vcpus=1, disk_gib=10, pool="default", network="default",
        os_variant="generic",
    )
    with pytest.raises(qemu_provisioning.QemuApiError, match="install method must be specified"):
        qemu_provisioning.create_vm(HOST, spec)


def test_create_vm_raises_when_virt_install_not_installed(monkeypatch):
    def fake_run(*args, **kwargs):
        raise FileNotFoundError()

    monkeypatch.setattr(qemu_provisioning.subprocess, "run", fake_run)
    spec = VmCreateSpec(
        name="myvm", memory_mib=1024, vcpus=1, disk_gib=10, pool="default", network="default",
        os_variant="generic",
    )
    with pytest.raises(qemu_provisioning.QemuApiError, match="virt-install not found"):
        qemu_provisioning.create_vm(HOST, spec)


def test_create_vm_raises_on_timeout(monkeypatch):
    def fake_run(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="virt-install", timeout=30)

    monkeypatch.setattr(qemu_provisioning.subprocess, "run", fake_run)
    spec = VmCreateSpec(
        name="myvm", memory_mib=1024, vcpus=1, disk_gib=10, pool="default", network="default",
        os_variant="generic",
    )
    with pytest.raises(qemu_provisioning.QemuApiError, match="timed out"):
        qemu_provisioning.create_vm(HOST, spec)


def test_get_vm_resources_parses_real_dumpxml(monkeypatch):
    monkeypatch.setattr(
        qemu_provisioning.subprocess, "run", lambda *a, **k: _completed(stdout=_REAL_DUMPXML_RESOURCES)
    )
    assert qemu_provisioning.get_vm_resources(HOST, "testvm1") == (2, 1024)


def test_resize_vm_sets_both_vcpu_calls(monkeypatch):
    calls = []
    monkeypatch.setattr(
        qemu_provisioning.subprocess, "run",
        lambda cmd, capture_output, text, timeout: calls.append(cmd) or _completed(),
    )
    qemu_provisioning.resize_vm(HOST, "myvm", vcpus=4)
    assert calls == [
        ["virsh", "-c", HOST.uri, "setvcpus", "myvm", "4", "--config", "--maximum"],
        ["virsh", "-c", HOST.uri, "setvcpus", "myvm", "4", "--config"],
    ]


def test_resize_vm_sets_both_memory_calls_converting_mib_to_kib(monkeypatch):
    calls = []
    monkeypatch.setattr(
        qemu_provisioning.subprocess, "run",
        lambda cmd, capture_output, text, timeout: calls.append(cmd) or _completed(),
    )
    qemu_provisioning.resize_vm(HOST, "myvm", memory_mib=2048)
    assert calls == [
        ["virsh", "-c", HOST.uri, "setmaxmem", "myvm", "2097152", "--config"],
        ["virsh", "-c", HOST.uri, "setmem", "myvm", "2097152", "--config"],
    ]


def test_resize_vm_only_touches_what_was_passed(monkeypatch):
    calls = []
    monkeypatch.setattr(
        qemu_provisioning.subprocess, "run",
        lambda cmd, capture_output, text, timeout: calls.append(cmd) or _completed(),
    )
    qemu_provisioning.resize_vm(HOST, "myvm", vcpus=None, memory_mib=None)
    assert calls == []


def test_add_disk_creates_volume_and_attaches_at_next_target(monkeypatch):
    calls = []

    def fake_run(cmd, capture_output, text, timeout):
        calls.append(cmd)
        if cmd[3:5] == ["domblklist", "myvm"]:
            return _completed(stdout=_REAL_BLK_LIST_ONE_DISK)
        if cmd[3] == "vol-list":
            return _completed(stdout=_REAL_VOL_LIST_AFTER_ADD_DISK)
        return _completed()

    monkeypatch.setattr(qemu_provisioning.subprocess, "run", fake_run)

    qemu_provisioning.add_disk(HOST, "myvm", pool="default", size_gib=5)

    create_call = next(c for c in calls if c[3] == "vol-create-as")
    assert create_call == ["virsh", "-c", HOST.uri, "vol-create-as", "default", "myvm-disk-2.qcow2", "5G", "--format", "qcow2"]
    attach_call = next(c for c in calls if c[3] == "attach-disk")
    assert attach_call == [
        "virsh", "-c", HOST.uri, "attach-disk", "myvm",
        "/var/lib/libvirt/images/myvm-disk-2.qcow2", "hdb", "--config", "--persistent",
    ]


def test_next_disk_target_increments_trailing_letter(monkeypatch):
    monkeypatch.setattr(
        qemu_provisioning.subprocess, "run",
        lambda *a, **k: _completed(stdout=_REAL_BLK_LIST_TWO_DISKS),
    )
    assert qemu_provisioning._next_disk_target(HOST, "myvm") == "hdc"


def test_next_disk_target_raises_when_no_existing_disks(monkeypatch):
    empty = " Target   Source\n-------------------------------------------\n"
    monkeypatch.setattr(qemu_provisioning.subprocess, "run", lambda *a, **k: _completed(stdout=empty))
    with pytest.raises(qemu_provisioning.QemuApiError, match="no existing disks"):
        qemu_provisioning._next_disk_target(HOST, "myvm")


def test_next_virtio_disk_target_returns_vda_when_none_exist(monkeypatch):
    # Only an IDE boot disk -- no virtio disk to continue from at all.
    monkeypatch.setattr(
        qemu_provisioning.subprocess, "run",
        lambda *a, **k: _completed(stdout=_REAL_BLK_LIST_ONE_DISK),
    )
    assert qemu_provisioning._next_virtio_disk_target(HOST, "myvm") == "vda"


def test_next_virtio_disk_target_increments_existing_virtio_ignoring_ide(monkeypatch):
    monkeypatch.setattr(
        qemu_provisioning.subprocess, "run",
        lambda *a, **k: _completed(stdout=_REAL_BLK_LIST_IDE_BOOT_PLUS_VIRTIO_DATA),
    )
    assert qemu_provisioning._next_virtio_disk_target(HOST, "myvm") == "vdc"


def test_add_disk_live_forces_virtio_target_and_bus(monkeypatch):
    # Regression test: confirmed live that add_disk's normal
    # scheme-continuing target (_next_disk_target) produces another IDE
    # target for a VM whose boot disk is IDE (this app's own common
    # case for a plain "generic" os-variant), and IDE disks flatly
    # refuse to hotplug at all -- the *entire* attach-disk call then
    # fails outright, not just its live half. live=True must pick an
    # explicit virtio target/bus instead, regardless of the boot disk's
    # own bus.
    calls = []

    def fake_run(cmd, capture_output, text, timeout):
        calls.append(cmd)
        if cmd[3:5] == ["domblklist", "myvm"]:
            return _completed(stdout=_REAL_BLK_LIST_ONE_DISK)  # IDE boot disk only
        if cmd[3] == "vol-list":
            return _completed(stdout=_REAL_VOL_LIST_AFTER_ADD_DISK)
        return _completed()

    monkeypatch.setattr(qemu_provisioning.subprocess, "run", fake_run)

    qemu_provisioning.add_disk(HOST, "myvm", pool="default", size_gib=5, live=True)

    attach_call = next(c for c in calls if c[3] == "attach-disk")
    assert attach_call == [
        "virsh", "-c", HOST.uri, "attach-disk", "myvm",
        "/var/lib/libvirt/images/myvm-disk-2.qcow2", "vda", "--targetbus", "virtio", "--config", "--persistent",
    ]


def test_is_available_true_when_virt_install_on_path(monkeypatch):
    monkeypatch.setattr(qemu_provisioning.shutil, "which", lambda name: "/usr/bin/virt-install")
    assert qemu_provisioning.is_available() is True


def test_is_available_false_when_virt_install_missing(monkeypatch):
    monkeypatch.setattr(qemu_provisioning.shutil, "which", lambda name: None)
    assert qemu_provisioning.is_available() is False


# Real output captured live -- a VM deployed with an ISO attached (so it
# has both a real disk and a cdrom device with a source), used for the
# list_disks/network/change-media tests below.
_REAL_BLK_DETAILS_WITH_CDROM = (
    " Type   Device   Target   Source\n"
    "------------------------------------------------------------------\n"
    " file   disk     hda      /var/lib/libvirt/images/edittest.qcow2\n"
    " file   cdrom    hdb      -\n"
)
_REAL_DOMIFLIST = (
    " Interface   Type      Source    Model   MAC\n"
    "------------------------------------------------------------\n"
    " -           network   default   e1000   52:54:00:57:37:5c\n"
)


def test_list_disks_distinguishes_disk_from_cdrom(monkeypatch):
    monkeypatch.setattr(
        qemu_provisioning.subprocess, "run",
        lambda *a, **k: _completed(stdout=_REAL_BLK_DETAILS_WITH_CDROM),
    )
    disks = qemu_provisioning.list_disks(HOST, "edittest")
    assert disks == [
        qemu_provisioning.VmDisk(target="hda", device="disk", source="/var/lib/libvirt/images/edittest.qcow2"),
        qemu_provisioning.VmDisk(target="hdb", device="cdrom", source=None),
    ]


def test_remove_disk_calls_detach_disk(monkeypatch):
    calls = []
    monkeypatch.setattr(
        qemu_provisioning.subprocess, "run",
        lambda cmd, capture_output, text, timeout: calls.append(cmd) or _completed(),
    )
    qemu_provisioning.remove_disk(HOST, "edittest", "hda")
    assert calls == [["virsh", "-c", HOST.uri, "detach-disk", "edittest", "hda", "--config", "--persistent"]]


def test_list_network_interfaces_parses_real_output(monkeypatch):
    monkeypatch.setattr(
        qemu_provisioning.subprocess, "run", lambda *a, **k: _completed(stdout=_REAL_DOMIFLIST)
    )
    interfaces = qemu_provisioning.list_network_interfaces(HOST, "edittest")
    assert interfaces == [
        qemu_provisioning.VmNetworkInterface(mac="52:54:00:57:37:5c", network="default", model="e1000"),
    ]


def test_change_network_detaches_then_attaches(monkeypatch):
    calls = []
    monkeypatch.setattr(
        qemu_provisioning.subprocess, "run",
        lambda cmd, capture_output, text, timeout: calls.append(cmd) or _completed(),
    )
    qemu_provisioning.change_network(HOST, "edittest", old_mac="52:54:00:57:37:5c", new_network="isolated")
    assert calls == [
        ["virsh", "-c", HOST.uri, "detach-interface", "edittest", "network", "--mac", "52:54:00:57:37:5c", "--config"],
        ["virsh", "-c", HOST.uri, "attach-interface", "edittest", "network", "isolated", "--model", "virtio", "--config"],
    ]


def test_change_cdrom_media_insert_ejects_first_then_inserts(monkeypatch):
    # Confirmed live: change-media --insert flatly refuses if the drive
    # already has media -- a real swap always ejects first.
    calls = []
    monkeypatch.setattr(
        qemu_provisioning.subprocess, "run",
        lambda cmd, capture_output, text, timeout: calls.append(cmd) or _completed(),
    )
    qemu_provisioning.change_cdrom_media(HOST, "edittest", "hdb", "/var/lib/libvirt/images/new.iso")
    assert calls == [
        ["virsh", "-c", HOST.uri, "change-media", "edittest", "hdb", "--eject", "--config"],
        ["virsh", "-c", HOST.uri, "change-media", "edittest", "hdb", "--insert",
         "/var/lib/libvirt/images/new.iso", "--config"],
    ]


def test_change_cdrom_media_insert_tolerates_drive_already_being_empty(monkeypatch):
    calls = []

    def fake_run(cmd, capture_output, text, timeout):
        calls.append(cmd)
        if "--eject" in cmd:
            return _completed(returncode=1, stderr="error: The disk device 'hdb' doesn't have media")
        return _completed()

    monkeypatch.setattr(qemu_provisioning.subprocess, "run", fake_run)
    qemu_provisioning.change_cdrom_media(HOST, "edittest", "hdb", "/var/lib/libvirt/images/new.iso")

    assert len(calls) == 2
    assert "--insert" in calls[1]


_REAL_DUMPXML_SPICE_GRAPHICS = """<domain type='kvm'>
  <name>myvm</name>
  <devices>
    <graphics type='spice' port='5900' autoport='yes' listen='127.0.0.1'>
      <listen type='address' address='127.0.0.1'/>
    </graphics>
  </devices>
</domain>"""

_REAL_DUMPXML_VNC_GRAPHICS = """<domain type='kvm'>
  <name>myvm</name>
  <devices>
    <graphics type='vnc' port='5900' autoport='yes' listen='127.0.0.1'>
      <listen type='address' address='127.0.0.1'/>
    </graphics>
  </devices>
</domain>"""

_REAL_DUMPXML_NO_GRAPHICS = """<domain type='kvm'>
  <name>myvm</name>
  <devices></devices>
</domain>"""


def test_get_vm_display_device_parses_spice(monkeypatch):
    monkeypatch.setattr(
        qemu_provisioning.subprocess, "run", lambda *a, **k: _completed(stdout=_REAL_DUMPXML_SPICE_GRAPHICS)
    )
    assert qemu_provisioning.get_vm_display_device(HOST, "myvm") == "spice"


def test_get_vm_display_device_parses_vnc(monkeypatch):
    monkeypatch.setattr(
        qemu_provisioning.subprocess, "run", lambda *a, **k: _completed(stdout=_REAL_DUMPXML_VNC_GRAPHICS)
    )
    assert qemu_provisioning.get_vm_display_device(HOST, "myvm") == "vnc"


def test_get_vm_display_device_returns_none_without_graphics(monkeypatch):
    monkeypatch.setattr(
        qemu_provisioning.subprocess, "run", lambda *a, **k: _completed(stdout=_REAL_DUMPXML_NO_GRAPHICS)
    )
    assert qemu_provisioning.get_vm_display_device(HOST, "myvm") is None


def test_set_display_device_rejects_unsupported_type(monkeypatch):
    with pytest.raises(qemu_provisioning.QemuApiError, match="Unsupported display device"):
        qemu_provisioning.set_display_device(HOST, "myvm", "rdp")


def test_set_display_device_switches_vnc_to_spice(monkeypatch):
    import xml.etree.ElementTree as ET

    calls = []
    defined_xml = {}

    def fake_run(cmd, capture_output, text, timeout):
        calls.append(cmd)
        if cmd[3] == "dumpxml":
            return _completed(stdout=_REAL_DUMPXML_VNC_GRAPHICS)
        if cmd[3] == "define":
            with open(cmd[4]) as f:
                defined_xml["text"] = f.read()
            return _completed()
        return _completed()

    monkeypatch.setattr(qemu_provisioning.subprocess, "run", fake_run)

    qemu_provisioning.set_display_device(HOST, "myvm", "spice")

    assert [c[3] for c in calls] == ["dumpxml", "define"]
    root = ET.fromstring(defined_xml["text"])
    graphics = root.find(".//graphics")
    assert graphics.get("type") == "spice"
    assert graphics.get("port") is None  # old VNC port dropped, not carried over
    assert graphics.get("autoport") == "yes"
    assert graphics.get("listen") == "127.0.0.1"
    assert graphics.find("listen") is None  # stale nested <listen> child dropped too


def test_set_display_device_adds_graphics_when_vm_has_none(monkeypatch):
    import xml.etree.ElementTree as ET

    defined_xml = {}

    def fake_run(cmd, capture_output, text, timeout):
        if cmd[3] == "dumpxml":
            return _completed(stdout=_REAL_DUMPXML_NO_GRAPHICS)
        if cmd[3] == "define":
            with open(cmd[4]) as f:
                defined_xml["text"] = f.read()
        return _completed()

    monkeypatch.setattr(qemu_provisioning.subprocess, "run", fake_run)

    qemu_provisioning.set_display_device(HOST, "myvm", "spice")

    root = ET.fromstring(defined_xml["text"])
    graphics = root.find(".//graphics")
    assert graphics.get("type") == "spice"


_REAL_DUMPXML_BOOT_ORDER_CDROM_THEN_HD = """<domain type='kvm'>
  <name>myvm</name>
  <os>
    <type arch='x86_64' machine='pc-q35-9.1'>hvm</type>
    <boot dev='cdrom'/>
    <boot dev='hd'/>
  </os>
  <devices></devices>
</domain>"""

_REAL_DUMPXML_BOOT_ORDER_UEFI_NO_BOOT_LIST = """<domain type='kvm'>
  <name>myvm</name>
  <os>
    <type arch='x86_64' machine='q35'>hvm</type>
    <loader readonly='yes' type='pflash'>/usr/share/OVMF/OVMF_CODE.fd</loader>
    <nvram>/var/lib/libvirt/qemu/nvram/myvm_VARS.fd</nvram>
  </os>
  <devices></devices>
</domain>"""

_REAL_DUMPXML_BOOT_ORDER_WITH_PER_DEVICE_ORDER = """<domain type='kvm'>
  <name>myvm</name>
  <os>
    <type arch='x86_64' machine='pc-q35-9.1'>hvm</type>
  </os>
  <devices>
    <disk type='file' device='disk'>
      <target dev='vda' bus='virtio'/>
      <boot order='2'/>
    </disk>
    <interface type='network'>
      <target dev='vnet0'/>
      <boot order='1'/>
    </interface>
  </devices>
</domain>"""


def test_get_boot_order_parses_existing_order(monkeypatch):
    monkeypatch.setattr(
        qemu_provisioning.subprocess, "run",
        lambda *a, **k: _completed(stdout=_REAL_DUMPXML_BOOT_ORDER_CDROM_THEN_HD),
    )
    assert qemu_provisioning.get_boot_order(HOST, "myvm") == ["cdrom", "hd"]


def test_get_boot_order_returns_empty_when_unset(monkeypatch):
    monkeypatch.setattr(
        qemu_provisioning.subprocess, "run",
        lambda *a, **k: _completed(stdout=_REAL_DUMPXML_BOOT_ORDER_UEFI_NO_BOOT_LIST),
    )
    assert qemu_provisioning.get_boot_order(HOST, "myvm") == []


def test_set_boot_order_rejects_unsupported_device(monkeypatch):
    with pytest.raises(qemu_provisioning.QemuApiError, match="Unsupported boot device"):
        qemu_provisioning.set_boot_order(HOST, "myvm", ["hd", "usb"])


def test_set_boot_order_writes_new_order_after_type(monkeypatch):
    import xml.etree.ElementTree as ET

    defined_xml = {}

    def fake_run(cmd, capture_output, text, timeout):
        if cmd[3] == "dumpxml":
            return _completed(stdout=_REAL_DUMPXML_BOOT_ORDER_CDROM_THEN_HD)
        if cmd[3] == "define":
            with open(cmd[4]) as f:
                defined_xml["text"] = f.read()
        return _completed()

    monkeypatch.setattr(qemu_provisioning.subprocess, "run", fake_run)

    qemu_provisioning.set_boot_order(HOST, "myvm", ["hd", "network", "cdrom"])

    root = ET.fromstring(defined_xml["text"])
    os_el = root.find("os")
    assert [child.tag for child in os_el] == ["type", "boot", "boot", "boot"]
    assert [b.get("dev") for b in os_el.findall("boot")] == ["hd", "network", "cdrom"]


def test_set_boot_order_inserts_after_loader_and_nvram(monkeypatch):
    import xml.etree.ElementTree as ET

    defined_xml = {}

    def fake_run(cmd, capture_output, text, timeout):
        if cmd[3] == "dumpxml":
            return _completed(stdout=_REAL_DUMPXML_BOOT_ORDER_UEFI_NO_BOOT_LIST)
        if cmd[3] == "define":
            with open(cmd[4]) as f:
                defined_xml["text"] = f.read()
        return _completed()

    monkeypatch.setattr(qemu_provisioning.subprocess, "run", fake_run)

    qemu_provisioning.set_boot_order(HOST, "myvm", ["hd"])

    root = ET.fromstring(defined_xml["text"])
    os_el = root.find("os")
    assert [child.tag for child in os_el] == ["type", "loader", "nvram", "boot"]


def test_set_boot_order_strips_conflicting_per_device_order(monkeypatch):
    import xml.etree.ElementTree as ET

    defined_xml = {}

    def fake_run(cmd, capture_output, text, timeout):
        if cmd[3] == "dumpxml":
            return _completed(stdout=_REAL_DUMPXML_BOOT_ORDER_WITH_PER_DEVICE_ORDER)
        if cmd[3] == "define":
            with open(cmd[4]) as f:
                defined_xml["text"] = f.read()
        return _completed()

    monkeypatch.setattr(qemu_provisioning.subprocess, "run", fake_run)

    qemu_provisioning.set_boot_order(HOST, "myvm", ["hd"])

    root = ET.fromstring(defined_xml["text"])
    for device_el in root.find("devices"):
        assert device_el.find("boot") is None


def test_change_cdrom_media_eject_only(monkeypatch):
    calls = []
    monkeypatch.setattr(
        qemu_provisioning.subprocess, "run",
        lambda cmd, capture_output, text, timeout: calls.append(cmd) or _completed(),
    )
    qemu_provisioning.change_cdrom_media(HOST, "edittest", "hdb", None)
    assert calls == [["virsh", "-c", HOST.uri, "change-media", "edittest", "hdb", "--eject", "--config"]]


def test_change_cdrom_media_eject_only_tolerates_already_empty(monkeypatch):
    monkeypatch.setattr(
        qemu_provisioning.subprocess, "run",
        lambda *a, **k: _completed(returncode=1, stderr="error: The disk device 'hdb' doesn't have media"),
    )
    qemu_provisioning.change_cdrom_media(HOST, "edittest", "hdb", None)  # should not raise


def test_change_cdrom_media_reraises_unrelated_eject_errors(monkeypatch):
    monkeypatch.setattr(
        qemu_provisioning.subprocess, "run",
        lambda *a, **k: _completed(returncode=1, stderr="error: failed to connect to the hypervisor"),
    )
    with pytest.raises(qemu_provisioning.QemuApiError, match="failed to connect"):
        qemu_provisioning.change_cdrom_media(HOST, "edittest", "hdb", None)
