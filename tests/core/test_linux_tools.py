import subprocess
import sys
from pathlib import Path

from it_toolbox.core import linux_tools

_REPO_ROOT = Path(__file__).resolve().parents[2]


def test_ids_are_unique():
    ids = [t.id for t in linux_tools.TOOLS]
    assert len(ids) == len(set(ids))


def test_qemu_and_spice_tools_are_registered():
    for tool_id in ("virsh", "virt-install", "spice", "ssh"):
        assert linux_tools.get(tool_id).packages


def test_all_packages_dedupes_in_registry_order():
    packages = linux_tools.all_packages()
    assert len(packages) == len(set(packages))
    assert packages[0] == linux_tools.TOOLS[0].packages[0]


def test_module_runs_standalone_for_the_rootfs_build():
    """packaging/wsl/build.sh runs this file as a plain script, outside
    any venv -- it must work with nothing but the standard library."""
    result = subprocess.run(
        [sys.executable, "-I", str(_REPO_ROOT / "src/it_toolbox/core/linux_tools.py")],
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.split() == linux_tools.all_packages()
