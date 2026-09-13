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
_REAL_VOL_LIST_AFTER_ADD_DISK = (
    " Name                Path\n"
    "----------------------------------------------------------\n"
    " myvm-disk-2.qcow2   /var/lib/libvirt/images/myvm-disk-2.qcow2\n"
)
# The exact error virt-install gives for a disk-only spec with no boot
# source -- confirmed live this is a real, hard requirement, not
# something specific to this project's own argv construction.
_REAL_NO_INSTALL_METHOD_ERROR = (
    "ERROR    \nAn install method must be specified\n"
    "(--location URL, --cdrom CD/ISO, --pxe, --import, --boot hd|cdrom|...)\n"
)


def _completed(stdout="", stderr="", returncode=0):
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


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


def test_is_available_true_when_virt_install_on_path(monkeypatch):
    monkeypatch.setattr(qemu_provisioning.shutil, "which", lambda name: "/usr/bin/virt-install")
    assert qemu_provisioning.is_available() is True


def test_is_available_false_when_virt_install_missing(monkeypatch):
    monkeypatch.setattr(qemu_provisioning.shutil, "which", lambda name: None)
    assert qemu_provisioning.is_available() is False
