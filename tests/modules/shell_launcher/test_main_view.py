from it_toolbox.core.shell_discovery import Shell
from it_toolbox.modules.shell_launcher.ui.main_view import SHELL_ROLE, ShellLauncherView


def _make_view(qtbot, monkeypatch, shells=()):
    monkeypatch.setattr(
        "it_toolbox.modules.shell_launcher.ui.main_view.discover_shells",
        lambda: list(shells),
    )
    view = ShellLauncherView()
    qtbot.addWidget(view)
    return view


def test_discovered_shells_populate_the_list(qtbot, monkeypatch):
    shell = Shell(name="bash", argv=("/bin/sh",))
    view = _make_view(qtbot, monkeypatch, shells=[shell])

    assert view._list.count() == 1
    item = view._list.item(0)
    assert item.text() == "bash"
    assert item.data(SHELL_ROLE) == shell


def test_double_clicking_a_shell_launches_a_real_terminal_tab(qtbot, monkeypatch):
    # A bare local shell is safe and fast to actually spawn in a test —
    # same convention tests/widgets/test_terminal_widget.py already uses.
    shell = Shell(name="test-shell", argv=("/bin/sh",))
    view = _make_view(qtbot, monkeypatch, shells=[shell])

    view._on_item_double_clicked(view._list.item(0))

    assert view._tabs.count() == 1
    assert view._tabs.tabText(0) == "test-shell"
    terminal = view._tabs.widget(0)
    qtbot.waitUntil(lambda: bool(terminal.toPlainText().strip()), timeout=3000)
    terminal.close_session()


def test_launching_the_same_shell_twice_opens_two_tabs(qtbot, monkeypatch):
    shell = Shell(name="test-shell", argv=("/bin/sh",))
    view = _make_view(qtbot, monkeypatch, shells=[shell])

    view._on_item_double_clicked(view._list.item(0))
    view._on_item_double_clicked(view._list.item(0))

    assert view._tabs.count() == 2
    for i in range(view._tabs.count()):
        view._tabs.widget(i).close_session()


def test_closing_a_tab_ends_the_session(qtbot, monkeypatch):
    shell = Shell(name="test-shell", argv=("/bin/sh",))
    view = _make_view(qtbot, monkeypatch, shells=[shell])
    view._on_item_double_clicked(view._list.item(0))

    view._on_tab_close_requested(0)

    assert view._tabs.count() == 0


def test_refresh_repopulates_the_list(qtbot, monkeypatch):
    shells = [Shell(name="bash", argv=("/bin/sh",))]
    view = _make_view(qtbot, monkeypatch, shells=shells)
    assert view._list.count() == 1

    shells.append(Shell(name="zsh", argv=("/bin/zsh",)))
    view.refresh_shells()

    assert view._list.count() == 2
    assert {view._list.item(i).text() for i in range(2)} == {"bash", "zsh"}


def test_context_menu_offers_refresh(qtbot, monkeypatch):
    view = _make_view(qtbot, monkeypatch)

    menu = view.build_context_menu(view)

    assert [action.text() for action in menu.actions()] == ["Refresh"]
