"""Colour-coded VM status dots for the Connection Manager tree (issue #20):
green = running, red = stopped, orange = paused/suspended, grey = in
between (starting, stopping, ...) or unrecognised.

GCP and libvirt describe the same few situations with different words, so
each source's raw status is first reduced to one of these kinds; the tree
item's tooltip keeps the exact raw status for anyone who needs it. Manual
connections and GL.iNet hosts get no dot: there's no status to report for
them without actively probing the host.
"""

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap

RUNNING = "running"
STOPPED = "stopped"
PAUSED = "paused"
TRANSITIONAL = "transitional"

# Mid-saturation colours that read on both light and dark tree backgrounds.
_COLOURS = {
    RUNNING: "#34a853",
    STOPPED: "#ea4335",
    PAUSED: "#fb8c00",
    TRANSITIONAL: "#9e9e9e",
}

# Compute Engine instance.status values.
_GCP_KINDS = {
    "RUNNING": RUNNING,
    "TERMINATED": STOPPED,
    "STOPPED": STOPPED,
    "SUSPENDED": PAUSED,
    # PROVISIONING, STAGING, STOPPING, SUSPENDING, REPAIRING, PENDING_STOP
    # all fall through to TRANSITIONAL.
}

# `virsh list --all` state strings.
_QEMU_KINDS = {
    "running": RUNNING,
    # A running guest that's idle/waiting on a resource -- still up.
    "idle": RUNNING,
    "blocked": RUNNING,
    "shut off": STOPPED,
    "crashed": STOPPED,
    "paused": PAUSED,
    "pmsuspended": PAUSED,
    # "in shutdown" falls through to TRANSITIONAL.
}

_DOT_SIZE = 12
_icon_cache: dict[str, QIcon] = {}


def gcp_status_kind(status: str) -> str:
    return _GCP_KINDS.get(status.upper(), TRANSITIONAL)


def qemu_state_kind(state: str) -> str:
    return _QEMU_KINDS.get(state.strip().lower(), TRANSITIONAL)


def status_icon(kind: str) -> QIcon:
    """A filled circle in `kind`'s colour. Cached, so every item of the
    same kind shares one QIcon (and one cacheKey)."""
    icon = _icon_cache.get(kind)
    if icon is None:
        pixmap = QPixmap(_DOT_SIZE, _DOT_SIZE)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(_COLOURS[kind]))
        painter.drawEllipse(1, 1, _DOT_SIZE - 2, _DOT_SIZE - 2)
        painter.end()
        icon = QIcon(pixmap)
        _icon_cache[kind] = icon
    return icon
