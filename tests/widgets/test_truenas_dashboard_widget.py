import pytest
from PySide6.QtWidgets import QInputDialog, QMessageBox
from truenas_fake import API_KEY, FakeTrueNas

from it_toolbox.core.truenas_client import TrueNasConnection
from it_toolbox.widgets import truenas_dashboard_widget as dash
from it_toolbox.widgets.truenas_dashboard_widget import AREAS, TrueNasDashboardWidget


@pytest.fixture
def nas(tmp_path):
    with FakeTrueNas(tmp_path) as server:
        yield server


@pytest.fixture
def widget(qtbot, nas):
    w = TrueNasDashboardWidget(
        "nas01",
        lambda: TrueNasConnection(nas.url, API_KEY, fingerprint=nas.fingerprint).open(),
        web_url="https://nas01.lan",
    )
    qtbot.addWidget(w)
    qtbot.waitUntil(lambda: w.vms_table.rowCount() == 1 and w.apps_table.rowCount() == 1, timeout=5000)
    yield w
    w.close_session()


def select(table, row=0):
    table.selectRow(row)


def test_loads_every_area(widget, qtbot):
    assert widget.tabs.isEnabled()
    assert [widget.tabs.tabText(i) for i in range(widget.tabs.count())] == list(AREAS)
    qtbot.waitUntil(lambda: widget.tasks_table.rowCount() == 5)
    assert widget.alerts_table.rowCount() == 3
    assert widget.pools_table.item(0, 0).text() == "tank"
    assert widget.disks_table.item(1, 6).text() == "37 °C"
    assert widget.topology_tree.topLevelItem(0).text(0) == "Data"
    assert widget.datasets_tree.topLevelItem(0).child(0).text(0) == "media"
    assert widget.shares_table.rowCount() == 2
    assert widget.credentials_table.item(0, 3).text() == "media to backup"
    assert "TrueCloud backup" in widget._missing_label.text()
    assert widget._info["hostname"].text() == "nas01"


def test_live_stats_arrive(widget, qtbot):
    qtbot.waitUntil(lambda: widget._live["cpu"].text() == "12%" or widget._live["cpu"].text() == "13%", timeout=5000)
    assert "16.0 GiB of 32.0 GiB" == widget._live["memory"].text()


def test_show_area(widget):
    widget.show_area("Apps")
    assert widget.tabs.tabText(widget.tabs.currentIndex()) == "Apps"


def test_snapshots_load_for_the_selected_dataset(widget, qtbot):
    media = widget.datasets_tree.topLevelItem(0).child(0)
    widget.datasets_tree.setCurrentItem(media)
    qtbot.waitUntil(lambda: widget.snapshots_table.rowCount() == 1)
    assert widget.snapshots_table.item(0, 0).text() == "auto-2025-10-29"


def test_take_snapshot(widget, qtbot, nas, monkeypatch):
    widget.datasets_tree.setCurrentItem(widget.datasets_tree.topLevelItem(0).child(0))
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: ("before-upgrade", True)))
    widget._take_snapshot()
    qtbot.waitUntil(lambda: "pool.snapshot.create" in nas.methods_called())
    assert ("pool.snapshot.create", [{"dataset": "tank/media", "name": "before-upgrade", "recursive": False}]) in nas.calls


def test_rollback_asks_first(widget, qtbot, nas, monkeypatch):
    widget.datasets_tree.setCurrentItem(widget.datasets_tree.topLevelItem(0).child(0))
    qtbot.waitUntil(lambda: widget.snapshots_table.rowCount() == 1)
    select(widget.snapshots_table)
    asked = []
    monkeypatch.setattr(
        QMessageBox, "question", staticmethod(lambda p, t, text: asked.append(text) or QMessageBox.StandardButton.No)
    )
    widget._rollback_snapshot()
    assert "Every change made to the dataset since that snapshot is lost" in asked[0]
    assert "pool.snapshot.rollback" not in nas.methods_called()


def test_vm_power_off_after_confirmation(widget, qtbot, nas, monkeypatch):
    select(widget.vms_table)
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a: QMessageBox.StandardButton.Yes))
    widget._vm_action("poweroff")
    qtbot.waitUntil(lambda: "vm.poweroff" in nas.methods_called())


def test_app_update(widget, qtbot, nas, monkeypatch):
    select(widget.apps_table)
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a: QMessageBox.StandardButton.Yes))
    widget._update_app()
    qtbot.waitUntil(lambda: "app.upgrade" in nas.methods_called())


def test_app_logs_stream_into_the_dialog(widget, qtbot, nas):
    select(widget.apps_table)
    widget._app_logs()
    dialog = widget._log_dialogs[0]
    qtbot.waitUntil(lambda: "line one" in dialog.text.toPlainText())
    dialog.reject()
    qtbot.waitUntil(lambda: "core.unsubscribe" in nas.methods_called())


def test_run_replication_now(widget, qtbot, nas, monkeypatch):
    qtbot.waitUntil(lambda: widget.tasks_table.rowCount() == 5)
    select(widget.tasks_table, 1)
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a: QMessageBox.StandardButton.Yes))
    widget._run_task()
    qtbot.waitUntil(lambda: ("replication.run", [3]) in nas.calls)


def test_permission_errors_name_the_missing_role(widget, qtbot, nas, monkeypatch):
    nas.errors["vm.start"] = {"code": -32001, "message": "x", "data": {"errname": "EACCES", "reason": "Not authorized"}}
    select(widget.vms_table)
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda p, t, text: warnings.append(text)))
    widget._vm_action("start")
    qtbot.waitUntil(lambda: bool(warnings))
    assert "role" in warnings[0]


def test_connection_failure_offers_retry(qtbot):
    def fail():
        raise dash.TrueNasApiError("system.info", "boom")

    w = TrueNasDashboardWidget("nas01", fail)
    qtbot.addWidget(w)
    qtbot.waitUntil(lambda: w._retry.isVisibleTo(w))
    assert "boom" in w._status.text()
    assert not w.tabs.isEnabled()
    w.close_session()
