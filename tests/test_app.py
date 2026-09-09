import subprocess
import sys

from PySide6.QtWidgets import QMenu, QWidget

from it_toolbox.app import MainWindow
from it_toolbox.core.shell_discovery import Shell


def _disable_external_tools(monkeypatch):
    # Keep tests hermetic — they're exercising sidebar/tab wiring, not auth
    # or rclone discovery, so they shouldn't depend on (or spawn a
    # background check against) whatever gcloud/rclone state exists on the
    # machine running the test.
    monkeypatch.setattr(
        "it_toolbox.modules.connection_manager.ui.main_view.gcp_auth.is_available",
        lambda: False,
    )
    monkeypatch.setattr(
        "it_toolbox.modules.cloud_storage.ui.main_view.rclone_client.is_available",
        lambda: False,
    )
    monkeypatch.setattr(
        "it_toolbox.modules.identity_management.ui.main_view.settings.load_jumpcloud_api_key",
        lambda: None,
    )


def test_main_window_loads_connection_manager_by_default(qtbot, monkeypatch):
    _disable_external_tools(monkeypatch)

    window = MainWindow()
    qtbot.addWidget(window)

    assert window._module_list.count() == 5
    assert window._module_list.item(0).text() == "Connection Manager"
    assert window._module_list.item(1).text() == "Shell Launcher"
    assert window._module_list.item(2).text() == "Cloud Storage"
    assert window._module_list.item(3).text() == "Identity Management"
    assert window._module_list.item(4).text() == "Settings"
    assert window._module_list.currentRow() == 0

    # The GCP browser tree is nested under the module in the sidebar now,
    # not tab content in the main view.
    assert window._sidebar_extras.currentWidget() is window._stack.widget(0).sidebar_tree


def test_module_list_height_is_capped_to_fit_its_rows(qtbot, monkeypatch):
    # Regression test: QListWidget.sizeHint() is a fixed Qt default
    # (256x192) that ignores actual row count, which left a large dead
    # gap between the module list and self._sidebar_extras below it.
    _disable_external_tools(monkeypatch)

    window = MainWindow()
    qtbot.addWidget(window)

    row_height = window._module_list.sizeHintForRow(0)
    frame = 2 * window._module_list.frameWidth()
    expected = row_height * window._module_list.count() + frame

    assert window._module_list.maximumHeight() == expected
    assert window._module_list.maximumHeight() < window._module_list.sizeHint().height()


def test_session_tabs_hidden_and_stack_stretched_for_a_module_without_tabs(qtbot, monkeypatch):
    # Regression test: self._session_tabs stayed visible (and kept its
    # layout stretch) even for Settings, which never puts anything into
    # it -- leaving a large empty pane instead of giving that space to
    # the module's own view.
    _disable_external_tools(monkeypatch)

    window = MainWindow()
    qtbot.addWidget(window)

    settings_row = window._module_list.count() - 1
    assert window._modules[settings_row].display_name == "Settings"
    window._module_list.setCurrentRow(settings_row)

    assert window._session_tabs.isHidden() is True
    assert window._content_layout.stretch(0) == 1  # self._stack
    assert window._content_layout.stretch(1) == 0  # self._session_tabs


def test_session_tabs_stays_visible_and_stretched_for_a_module_with_tabs(qtbot, monkeypatch):
    _disable_external_tools(monkeypatch)

    window = MainWindow()
    qtbot.addWidget(window)

    # Switch away and back, so this doesn't just pass by never having
    # left the default state.
    window._module_list.setCurrentRow(window._module_list.count() - 1)
    window._module_list.setCurrentRow(0)

    assert window._session_tabs.isHidden() is False
    assert window._content_layout.stretch(0) == 0  # self._stack
    assert window._content_layout.stretch(1) == 1  # self._session_tabs


def test_stack_size_hint_reflects_only_the_current_page(qtbot, monkeypatch):
    # Regression test: QStackedWidget.sizeHint() defaults to the *largest*
    # size among all its pages (via its internal QStackedLayout), not just
    # the current one. self._stack holds every module's view, and
    # Settings' is by far the tallest -- so every other module's thin
    # toolbar-sized page was still allocated Settings-sized space in the
    # layout, starving self._session_tabs below it even though the fixes
    # above already made self._session_tabs visible/stretched correctly.
    _disable_external_tools(monkeypatch)

    window = MainWindow()
    qtbot.addWidget(window)

    settings_row = window._module_list.count() - 1
    assert window._modules[settings_row].display_name == "Settings"
    settings_page_height = window._stack.widget(settings_row).sizeHint().height()

    window._module_list.setCurrentRow(0)  # Connection Manager

    connection_manager_page_height = window._stack.currentWidget().sizeHint().height()
    assert window._stack.sizeHint().height() == connection_manager_page_height
    # The actual bug: without the fix, this was Settings' height instead.
    assert window._stack.sizeHint().height() != settings_page_height
    assert connection_manager_page_height < settings_page_height


def test_connection_manager_and_shell_launcher_share_one_tab_pane(qtbot, monkeypatch):
    _disable_external_tools(monkeypatch)

    window = MainWindow()
    qtbot.addWidget(window)

    connection_manager_view = window._stack.widget(0)
    shell_launcher_view = window._stack.widget(1)
    cloud_storage_view = window._stack.widget(2)

    assert connection_manager_view._tabs is window._session_tabs
    assert shell_launcher_view._tabs is window._session_tabs
    assert cloud_storage_view._tabs is window._session_tabs


def test_shell_tab_stays_open_after_switching_to_connection_manager(qtbot, monkeypatch):
    _disable_external_tools(monkeypatch)
    monkeypatch.setattr(
        "it_toolbox.modules.shell_launcher.ui.main_view.discover_shells",
        lambda: [Shell(name="test-shell", argv=("/bin/sh",))],
    )

    window = MainWindow()
    qtbot.addWidget(window)

    window._module_list.setCurrentRow(1)  # Shell Launcher
    shell_launcher_view = window._stack.widget(1)
    shell_launcher_view._on_item_double_clicked(shell_launcher_view._list.topLevelItem(0), 0)
    assert window._session_tabs.count() == 1

    window._module_list.setCurrentRow(0)  # Connection Manager

    # Switching the sidebar selection swaps _stack/_sidebar_extras only —
    # the shared tab pane itself is never part of that swap, so the shell
    # tab opened above must still be there.
    assert window._session_tabs.count() == 1
    terminal = window._session_tabs.widget(0)
    terminal.close_session()


def test_module_context_menu_has_default_username_and_active_sessions(qtbot, monkeypatch):
    _disable_external_tools(monkeypatch)

    window = MainWindow()
    qtbot.addWidget(window)

    menu = window._modules[0].build_context_menu(window)

    assert [action.text() for action in menu.actions()] == [
        "Set Default Username…",
        "View Active Sessions…",
    ]


class _FakeRdpWidget(QWidget):
    """Stands in for the real RdpWidget — the real one starts a background
    connection attempt in __init__, same reason connection_manager's own
    tests use an equivalent stand-in for it."""

    def __init__(self):
        super().__init__()
        self.refresh_calls = 0

    def refresh_resolution(self):
        self.refresh_calls += 1


def test_rdp_tab_menu_offers_refresh_resolution_and_triggers_it(qtbot, monkeypatch):
    import it_toolbox.app as app_module

    _disable_external_tools(monkeypatch)
    monkeypatch.setattr(app_module, "RdpWidget", _FakeRdpWidget)

    window = MainWindow()
    qtbot.addWidget(window)
    rdp_widget = _FakeRdpWidget()
    qtbot.addWidget(rdp_widget)
    index = window._session_tabs.addTab(rdp_widget, "myserver")

    # _build_session_tab_menu() is exercised directly, never
    # _on_session_tab_context_menu()/QMenu.exec() — exec() opens a real,
    # blocking popup with nothing to dismiss it in a headless test.
    menu = window._build_session_tab_menu(index)

    assert menu is not None
    assert [action.text() for action in menu.actions()] == ["Refresh Resolution"]
    menu.actions()[0].trigger()
    assert rdp_widget.refresh_calls == 1


def test_non_rdp_tab_menu_is_none(qtbot, monkeypatch):
    _disable_external_tools(monkeypatch)

    window = MainWindow()
    qtbot.addWidget(window)
    plain_widget = QWidget()
    qtbot.addWidget(plain_widget)
    index = window._session_tabs.addTab(plain_widget, "a terminal")

    assert window._build_session_tab_menu(index) is None


def test_no_tab_at_click_position_gives_no_menu(qtbot, monkeypatch):
    _disable_external_tools(monkeypatch)

    window = MainWindow()
    qtbot.addWidget(window)

    assert window._build_session_tab_menu(-1) is None


def test_app_imports_and_constructs_without_pygobject_installed():
    """Regression test for a real bug: main_view.py used to import
    SpiceWidget unconditionally at module load, which pulls in PyGObject
    (`gi`) — a dependency pyproject.toml only installs on
    sys_platform == "linux". That crashed the *entire app* at startup on
    Windows (confirmed there directly), not just the QEMU/SPICE feature.

    Runs in a real subprocess with `gi` import blocked, mirroring exactly
    what "gi isn't installed" looks like — isolated so the simulated
    missing-module state can't leak from/into other tests via Python's
    module cache.
    """
    script = """
import builtins
real_import = builtins.__import__
def fake_import(name, *args, **kwargs):
    if name == "gi" or name.startswith("gi."):
        raise ImportError(f"No module named {name!r}")
    return real_import(name, *args, **kwargs)
builtins.__import__ = fake_import

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication
app = QApplication([])

from it_toolbox.app import MainWindow
MainWindow()

import it_toolbox.modules.connection_manager.ui.main_view as mv
assert mv.SpiceWidget is None
print("OK")
"""
    result = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, timeout=15
    )
    assert result.returncode == 0, result.stderr
    assert "OK" in result.stdout
