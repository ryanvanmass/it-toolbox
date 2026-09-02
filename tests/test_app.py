from it_toolbox.app import MainWindow


def test_main_window_loads_connection_manager_by_default(qtbot, monkeypatch):
    # Keep this test hermetic — it's exercising sidebar wiring, not auth, so
    # it shouldn't depend on (or spawn a background check against) whatever
    # OAuth config happens to exist on the machine running the test.
    monkeypatch.setattr(
        "it_toolbox.modules.connection_manager.ui.main_view.gcp_oauth.is_configured",
        lambda: False,
    )

    window = MainWindow()
    qtbot.addWidget(window)

    assert window._sidebar.count() == 1
    assert window._sidebar.item(0).text() == "Connection Manager"
    assert window._sidebar.currentRow() == 0
