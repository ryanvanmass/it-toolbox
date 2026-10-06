import subprocess

import pytest

from it_toolbox.core import rclone_client, shell_discovery, subprocess_utils
from it_toolbox.core.auth import gcp_auth
from it_toolbox.modules.connection_manager import qemu_client, qemu_provisioning
from it_toolbox.modules.connection_manager.models import QemuHost

_SENTINEL = {"creationflags": 0x08000000}


def test_no_window_kwargs_empty_on_non_windows(monkeypatch):
    monkeypatch.setattr(subprocess_utils.sys, "platform", "linux")
    assert subprocess_utils.no_window_kwargs() == {}


def test_no_window_kwargs_sets_creationflags_on_windows(monkeypatch):
    # Only the key is checkable here: subprocess.CREATE_NO_WINDOW itself
    # only exists on a real Windows Python.
    monkeypatch.setattr(subprocess_utils.sys, "platform", "win32")
    assert "creationflags" in subprocess_utils.no_window_kwargs()


def _call_rclone(monkeypatch):
    monkeypatch.setattr(rclone_client, "is_available", lambda: True)
    rclone_client._run("version")


def _call_gcloud(monkeypatch):
    monkeypatch.setattr(gcp_auth, "is_available", lambda: True)
    gcp_auth._run("version")


def _call_virsh(monkeypatch):
    qemu_client.run_virsh(QemuHost(name="lab", uri="qemu:///system"), "list")


def _call_virt_install(monkeypatch):
    qemu_provisioning._run_virt_install("--version")


def _call_wsl(monkeypatch):
    monkeypatch.setattr(shell_discovery, "_wsl_has_registered_distros", lambda: True)
    monkeypatch.setattr(shell_discovery.shutil, "which", lambda name: "wsl.exe")
    shell_discovery._discover_wsl_distros()


# Regression test for a real report: a terminal window briefly flashed on
# Windows on every Cloud Storage interaction, one per background `rclone`
# call. Every captured-output CLI call must pass no_window_kwargs() through
# to the real subprocess.run call.
@pytest.mark.parametrize(
    "module, call",
    [
        (rclone_client, _call_rclone),
        (gcp_auth, _call_gcloud),
        (qemu_client, _call_virsh),
        (qemu_provisioning, _call_virt_install),
        (shell_discovery, _call_wsl),
    ],
)
def test_background_cli_calls_pass_no_window_kwargs(monkeypatch, module, call):
    monkeypatch.setattr(module, "no_window_kwargs", lambda: _SENTINEL)
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(kwargs)
        return subprocess.CompletedProcess(cmd, returncode=0, stdout=b"", stderr=b"")

    monkeypatch.setattr(subprocess, "run", fake_run)
    call(monkeypatch)

    assert calls
    assert all(kwargs.get("creationflags") == _SENTINEL["creationflags"] for kwargs in calls)
