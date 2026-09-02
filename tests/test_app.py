from it_toolbox.app import MainWindow


def test_main_window_loads_connection_manager_by_default(qtbot):
    window = MainWindow()
    qtbot.addWidget(window)

    assert window._sidebar.count() == 1
    assert window._sidebar.item(0).text() == "Connection Manager"
    assert window._sidebar.currentRow() == 0
