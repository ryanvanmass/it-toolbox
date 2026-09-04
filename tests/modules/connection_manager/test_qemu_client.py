import subprocess

import pytest

from it_toolbox.modules.connection_manager import qemu_client
from it_toolbox.modules.connection_manager.models import QemuHost

HOST = QemuHost(name="lab", uri="qemu+ssh://user@lab-host/system")


def _completed(stdout="", stderr="", returncode=0):
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


def test_list_vms_parses_output_including_multi_word_state(monkeypatch):
    output = (
        " Id   Name      State\n"
        "----------------------------\n"
        " 4    running1  running\n"
        " -    stopped1  shut off\n"
    )

    def fake_run(cmd, capture_output, text, timeout):
        assert cmd[:3] == ["virsh", "-c", HOST.uri]
        assert cmd[3:] == ["list", "--all"]
        return _completed(stdout=output)

    monkeypatch.setattr(qemu_client.subprocess, "run", fake_run)

    vms = qemu_client.list_vms(HOST)

    assert [(vm.id, vm.name, vm.state) for vm in vms] == [
        ("4", "running1", "running"),
        ("-", "stopped1", "shut off"),
    ]


def test_list_vms_sorts_by_name(monkeypatch):
    output = (
        " Id   Name   State\n"
        "----------------------\n"
        " -    zeta   shut off\n"
        " -    alpha  shut off\n"
    )
    monkeypatch.setattr(qemu_client.subprocess, "run", lambda *a, **k: _completed(stdout=output))

    vms = qemu_client.list_vms(HOST)

    assert [vm.name for vm in vms] == ["alpha", "zeta"]


def test_list_vms_raises_on_virsh_failure(monkeypatch):
    monkeypatch.setattr(
        qemu_client.subprocess,
        "run",
        lambda *a, **k: _completed(returncode=1, stderr="error: failed to connect"),
    )

    with pytest.raises(qemu_client.QemuApiError, match="failed to connect"):
        qemu_client.list_vms(HOST)


def test_list_vms_raises_on_timeout(monkeypatch):
    def fake_run(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="virsh", timeout=8)

    monkeypatch.setattr(qemu_client.subprocess, "run", fake_run)

    with pytest.raises(qemu_client.QemuApiError, match="timed out"):
        qemu_client.list_vms(HOST)


def test_list_vms_raises_when_virsh_not_installed(monkeypatch):
    def fake_run(*args, **kwargs):
        raise FileNotFoundError()

    monkeypatch.setattr(qemu_client.subprocess, "run", fake_run)

    with pytest.raises(qemu_client.QemuApiError, match="virsh not found"):
        qemu_client.list_vms(HOST)


def test_get_vm_spice_port_parses_port_from_dumpxml(monkeypatch):
    xml = """<domain>
      <devices>
        <graphics type='spice' port='5900' autoport='yes' listen='127.0.0.1'/>
      </devices>
    </domain>"""
    monkeypatch.setattr(qemu_client.subprocess, "run", lambda *a, **k: _completed(stdout=xml))

    assert qemu_client.get_vm_spice_port(HOST, "myvm") == 5900


def test_get_vm_spice_port_returns_none_without_spice_graphics(monkeypatch):
    xml = "<domain><devices></devices></domain>"
    monkeypatch.setattr(qemu_client.subprocess, "run", lambda *a, **k: _completed(stdout=xml))

    assert qemu_client.get_vm_spice_port(HOST, "myvm") is None


def test_get_vm_spice_port_returns_none_when_port_unassigned(monkeypatch):
    xml = "<domain><devices><graphics type='spice' port='-1' autoport='yes'/></devices></domain>"
    monkeypatch.setattr(qemu_client.subprocess, "run", lambda *a, **k: _completed(stdout=xml))

    assert qemu_client.get_vm_spice_port(HOST, "myvm") is None


@pytest.mark.parametrize(
    ("action", "expected_virsh_command"),
    [
        ("start", "start"),
        ("shutdown", "shutdown"),
        ("pause", "suspend"),
        ("resume", "resume"),
    ],
)
def test_power_action_maps_to_virsh_command(monkeypatch, action, expected_virsh_command):
    calls = []

    def fake_run(cmd, capture_output, text, timeout):
        calls.append(cmd)
        return _completed()

    monkeypatch.setattr(qemu_client.subprocess, "run", fake_run)

    qemu_client.power_action(HOST, "myvm", action)

    assert calls == [["virsh", "-c", HOST.uri, expected_virsh_command, "myvm"]]


def test_power_action_rejects_unknown_action():
    with pytest.raises(qemu_client.QemuApiError, match="Unknown power action"):
        qemu_client.power_action(HOST, "myvm", "reboot-and-eat-cookies")
