from pathlib import Path

import pytest
from PySide6.QtWidgets import QMessageBox, QWidget

from it_toolbox.core import remote_helper as rh
from it_toolbox.core import ssh_key_install as ski
from it_toolbox.widgets import remote_helper_widget as w

SERVER = rh.RemoteServer(name="nas", host="NAS.lan", username="admin", port=2222)
KEY = "ssh-ed25519 AAAA me@laptop"


@pytest.fixture
def parent(qtbot):
    widget = QWidget()
    qtbot.addWidget(widget)
    return widget


@pytest.fixture
def calls(monkeypatch):
    """Records the key install steps instead of touching SSH or ~/.ssh."""
    log = {"questions": [], "installed": [], "generated": [], "messages": [], "works": True}
    local = ski.LocalKey(Path("/home/me/.ssh/id_ed25519"), KEY)
    monkeypatch.setattr(w.ssh_key_install, "find_local_key", lambda key_path: log.get("local", local))
    monkeypatch.setattr(
        w.ssh_key_install, "generate_key",
        lambda path: log["generated"].append(path) or ski.LocalKey(path, "ssh-ed25519 NEW"),
    )
    monkeypatch.setattr(
        w.ssh_key_install, "install_public_key",
        lambda host, port, user, password, key: log["installed"].append((host, port, user, password, key)),
    )
    monkeypatch.setattr(w.ssh_key_install, "key_login_works", lambda *a: log["works"])

    def question(parent, title, text, *a):
        log["questions"].append(text)
        return log.get("answer", QMessageBox.StandardButton.Yes)

    monkeypatch.setattr(QMessageBox, "question", question)
    monkeypatch.setattr(QMessageBox, "information", lambda p, title, text, *a: log["messages"].append(title))
    monkeypatch.setattr(QMessageBox, "warning", lambda p, title, text, *a: log["messages"].append(text))
    return log


def test_no_offer_without_a_password(parent, calls):
    w.offer_key_install(parent, SERVER, {"sudo_password": "s"})
    assert calls["questions"] == []


def test_accepting_installs_the_key_and_drops_the_password(qtbot, parent, calls):
    credentials = {"password": "pw", "sudo_password": "pw"}
    w.offer_key_install(parent, SERVER, credentials)

    qtbot.waitUntil(lambda: calls["messages"] == ["SSH Key Installed"])
    assert "/home/me/.ssh/id_ed25519.pub" in calls["questions"][0]
    assert calls["installed"] == [("NAS.lan", 2222, "admin", "pw", KEY)]
    assert calls["generated"] == []
    # The next connect uses the key; sudo still has its password.
    assert credentials == {"sudo_password": "pw"}


def test_a_missing_key_is_generated_first(qtbot, parent, calls):
    calls["local"] = ski.LocalKey(Path("/home/me/.ssh/id_ed25519"), None)
    w.offer_key_install(parent, SERVER, {"password": "pw"})

    qtbot.waitUntil(lambda: calls["installed"] != [])
    assert "don't have an SSH key yet" in calls["questions"][0]
    assert calls["generated"] == [Path("/home/me/.ssh/id_ed25519")]
    assert calls["installed"][0][4] == "ssh-ed25519 NEW"


def test_key_still_refused_keeps_the_password(qtbot, parent, calls):
    calls["works"] = False
    credentials = {"password": "pw"}
    w.offer_key_install(parent, SERVER, credentials)

    qtbot.waitUntil(lambda: calls["messages"] != [])
    assert "still failed" in calls["messages"][0]
    assert credentials == {"password": "pw"}


def test_declining_asks_only_once_per_machine(parent, calls):
    calls["answer"] = QMessageBox.StandardButton.No
    w.offer_key_install(parent, SERVER, {"password": "pw"})
    same = rh.RemoteServer(name="other name", host="nas.LAN", username="admin", port=2222)
    w.offer_key_install(parent, same, {"password": "pw"})
    assert len(calls["questions"]) == 1 and calls["installed"] == []

    w.offer_key_install(parent, rh.RemoteServer(name="x", host="nas.lan", username="root", port=2222), {"password": "p"})
    assert len(calls["questions"]) == 2
