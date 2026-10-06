"""Registry of the Linux-only tools this app depends on.

One declarative list, used in three places so they can't drift apart
(see docs/wsl-interconnect-plan.md):

- availability checks (core/linux_backend.is_tool_available), which
  gate features like the QEMU tree, "Deploy VM…" and "Connect via
  SPICE";
- the managed WSL distro's rootfs build (packaging/wsl/build.sh installs
  exactly the union of every entry's `packages`, read from this file);
- Settings' "Linux tools" status list and the native-Linux install hints.

Adding a new Linux tool is one entry here plus a rootfs rebuild (bump
core/wsl_distro.ROOTFS_VERSION); a tool that needs a live stream rather
than one-shot CLI calls also adds a service under it_toolbox/wsl_helper/.

Deliberately has no imports beyond the standard library -- packaging/wsl/
reads this file from a plain container build, and the WSL helper imports
it from inside the distro, where PySide6 isn't installed.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class LinuxTool:
    id: str
    display_name: str
    # The executable whose presence means "this tool is installed". On a
    # native Linux host that's a plain PATH lookup (no process spawned).
    binary: str
    # Debian package names baked into the managed WSL distro's rootfs.
    packages: tuple[str, ...]
    # Shown by Settings on native Linux when the binary is missing --
    # it's a system package, not something this app can download.
    native_hint: str
    # Optional stronger check, run inside the WSL distro (where spawning
    # a process is the only way to check anything). Must exit 0 when the
    # tool is usable. None means "binary on PATH" is enough.
    probe: tuple[str, ...] | None = None


TOOLS: tuple[LinuxTool, ...] = (
    LinuxTool(
        id="virsh",
        display_name="virsh (libvirt client)",
        binary="virsh",
        packages=("libvirt-clients",),
        native_hint=(
            "  Debian/Ubuntu: sudo apt install libvirt-clients\n"
            "  Fedora/RHEL:   sudo dnf install libvirt-client"
        ),
    ),
    LinuxTool(
        id="virt-install",
        display_name="virt-install",
        binary="virt-install",
        packages=("virtinst",),
        native_hint=(
            "  Debian/Ubuntu: sudo apt install virtinst\n"
            "  Fedora/RHEL:   sudo dnf install virt-install"
        ),
    ),
    LinuxTool(
        id="spice",
        display_name="SPICE client (spice-glib)",
        binary="python3",
        packages=("python3", "python3-gi", "gir1.2-spiceclientglib-2.0"),
        native_hint=(
            "  Debian/Ubuntu: sudo apt install python3-gi gir1.2-spiceclientglib-2.0\n"
            "  Fedora/RHEL:   sudo dnf install python3-gobject spice-glib"
        ),
        probe=(
            "python3",
            "-c",
            (
                "import gi; gi.require_version('SpiceClientGLib', '2.0'); "
                "from gi.repository import SpiceClientGLib"
            ),
        ),
    ),
    LinuxTool(
        id="ssh",
        display_name="OpenSSH client",
        binary="ssh",
        packages=("openssh-client",),
        native_hint=(
            "  Debian/Ubuntu: sudo apt install openssh-client\n"
            "  Fedora/RHEL:   sudo dnf install openssh-clients"
        ),
    ),
)

_TOOLS_BY_ID = {tool.id: tool for tool in TOOLS}


def get(tool_id: str) -> LinuxTool:
    return _TOOLS_BY_ID[tool_id]


def all_packages() -> list[str]:
    """Every package the managed rootfs needs, de-duplicated, in a stable
    order (registry order, first occurrence wins)."""
    seen: dict[str, None] = {}
    for tool in TOOLS:
        for package in tool.packages:
            seen.setdefault(package, None)
    return list(seen)


if __name__ == "__main__":
    # packaging/wsl/build.sh: `python3 src/it_toolbox/core/linux_tools.py`
    # prints the package list, one per line, for the rootfs build.
    print("\n".join(all_packages()))
