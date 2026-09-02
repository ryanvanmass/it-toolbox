from it_toolbox.app import MainWindow


def test_main_window_loads_connection_manager_by_default(qtbot, monkeypatch):
    # Keep this test hermetic — it's exercising sidebar wiring, not auth, so
    # it shouldn't depend on (or spawn a background check against) whatever
    # gcloud state exists on the machine running the test.
    monkeypatch.setattr(
        "it_toolbox.modules.connection_manager.ui.main_view.gcp_auth.is_available",
        lambda: False,
    )

    window = MainWindow()
    qtbot.addWidget(window)

    assert window._module_list.count() == 1
    assert window._module_list.item(0).text() == "Connection Manager"
    assert window._module_list.currentRow() == 0

    # The GCP browser tree is nested under the module in the sidebar now,
    # not tab content in the main view.
    assert window._sidebar_extras.currentWidget() is window._stack.widget(0).sidebar_tree


def test_module_context_menu_has_default_username_and_active_sessions(qtbot, monkeypatch):
    monkeypatch.setattr(
        "it_toolbox.modules.connection_manager.ui.main_view.gcp_auth.is_available",
        lambda: False,
    )

    window = MainWindow()
    qtbot.addWidget(window)

    menu = window._modules[0].build_context_menu(window)

    assert [action.text() for action in menu.actions()] == [
        "Set Default Username…",
        "View Active Sessions…",
    ]
