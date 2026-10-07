from PySide6.QtCore import QObject, Signal


class _LinuxToolsEvents(QObject):
    #: Emitted (on the main thread) after the Linux tools backend changes --
    #: the managed WSL distro was installed, updated or removed in Settings
    #: (see core/wsl_distro.py). Lets Connection Manager re-check whether
    #: its QEMU tree should be shown, without Settings importing it.
    changed = Signal()


linux_tools_events = _LinuxToolsEvents()
