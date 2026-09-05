import subprocess
import sys

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
