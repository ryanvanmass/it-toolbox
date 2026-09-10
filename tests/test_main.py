"""Tests for it_toolbox.__main__ -- kept fully mocked (no real QApplication)
since Qt only allows one QApplication instance per process, and pytest-qt
already owns one for the rest of the suite.
"""

import it_toolbox.__main__ as main_module


class _FakeApp:
    def __init__(self, argv):
        pass

    def setApplicationName(self, name):
        pass

    def setOrganizationName(self, name):
        pass

    def exec(self):
        return 0


class _FakeWindow:
    def show(self):
        pass


def _patch_qt(monkeypatch):
    monkeypatch.setattr(main_module, "QApplication", _FakeApp)
    monkeypatch.setattr(main_module, "MainWindow", lambda: _FakeWindow())


def test_main_does_not_configure_logging_by_default(monkeypatch):
    monkeypatch.delenv("IT_TOOLBOX_LOG_LEVEL", raising=False)
    _patch_qt(monkeypatch)
    calls = []
    monkeypatch.setattr(main_module.logging, "basicConfig", lambda **kwargs: calls.append(kwargs))

    exit_code = main_module.main()

    assert exit_code == 0
    assert calls == []


def test_main_configures_logging_when_env_var_set(monkeypatch):
    monkeypatch.setenv("IT_TOOLBOX_LOG_LEVEL", "DEBUG")
    _patch_qt(monkeypatch)
    calls = []
    monkeypatch.setattr(main_module.logging, "basicConfig", lambda **kwargs: calls.append(kwargs))

    main_module.main()

    assert len(calls) == 1
    assert calls[0]["level"] == "DEBUG"


def test_main_uppercases_the_log_level(monkeypatch):
    monkeypatch.setenv("IT_TOOLBOX_LOG_LEVEL", "debug")
    _patch_qt(monkeypatch)
    calls = []
    monkeypatch.setattr(main_module.logging, "basicConfig", lambda **kwargs: calls.append(kwargs))

    main_module.main()

    assert calls[0]["level"] == "DEBUG"
