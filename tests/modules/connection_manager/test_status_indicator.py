import pytest
from PySide6.QtGui import QColor

from it_toolbox.modules.connection_manager.ui import status_indicator
from it_toolbox.modules.connection_manager.ui.status_indicator import (
    PAUSED,
    RUNNING,
    STOPPED,
    TRANSITIONAL,
    gcp_status_kind,
    qemu_state_kind,
    status_icon,
)


@pytest.mark.parametrize(
    ("status", "kind"),
    [
        ("RUNNING", RUNNING),
        ("TERMINATED", STOPPED),
        ("STOPPED", STOPPED),
        ("SUSPENDED", PAUSED),
        ("STAGING", TRANSITIONAL),
        ("PROVISIONING", TRANSITIONAL),
        ("STOPPING", TRANSITIONAL),
        ("SUSPENDING", TRANSITIONAL),
        ("REPAIRING", TRANSITIONAL),
        ("something-new", TRANSITIONAL),
        ("running", RUNNING),
    ],
)
def test_gcp_status_kind(status, kind):
    assert gcp_status_kind(status) == kind


@pytest.mark.parametrize(
    ("state", "kind"),
    [
        ("running", RUNNING),
        ("idle", RUNNING),
        ("blocked", RUNNING),
        ("shut off", STOPPED),
        ("crashed", STOPPED),
        ("paused", PAUSED),
        ("pmsuspended", PAUSED),
        ("in shutdown", TRANSITIONAL),
        ("", TRANSITIONAL),
        (" Running ", RUNNING),
    ],
)
def test_qemu_state_kind(state, kind):
    assert qemu_state_kind(state) == kind


def _centre_colour(kind: str) -> QColor:
    image = status_icon(kind).pixmap(12, 12).toImage()
    return image.pixelColor(image.width() // 2, image.height() // 2)


def test_status_icons_are_the_issue_colours(qtbot):
    # Issue #20: green = running, red = stopped, orange = paused.
    running, stopped, paused = (_centre_colour(k) for k in (RUNNING, STOPPED, PAUSED))

    assert running.green() > running.red() and running.green() > running.blue()
    assert stopped.red() > stopped.green() and stopped.red() > stopped.blue()
    assert paused.red() > paused.green() > paused.blue()
    assert _centre_colour(TRANSITIONAL).name() == "#9e9e9e"


def test_status_icon_is_cached_per_kind(qtbot):
    status_indicator._icon_cache.clear()

    assert status_icon(RUNNING).cacheKey() == status_icon(RUNNING).cacheKey()
    assert status_icon(RUNNING).cacheKey() != status_icon(STOPPED).cacheKey()
