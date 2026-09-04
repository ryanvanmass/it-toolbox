from it_toolbox.core import settings


def _use_tmp_data_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", lambda: tmp_path)


def test_default_username_is_none_when_never_set(monkeypatch, tmp_path):
    _use_tmp_data_dir(monkeypatch, tmp_path)
    assert settings.load_default_username() is None


def test_save_and_load_default_username(monkeypatch, tmp_path):
    _use_tmp_data_dir(monkeypatch, tmp_path)
    settings.save_default_username("alice")
    assert settings.load_default_username() == "alice"


def test_save_default_username_strips_whitespace(monkeypatch, tmp_path):
    _use_tmp_data_dir(monkeypatch, tmp_path)
    settings.save_default_username("  bob  ")
    assert settings.load_default_username() == "bob"


def test_save_default_username_none_clears_it(monkeypatch, tmp_path):
    _use_tmp_data_dir(monkeypatch, tmp_path)
    settings.save_default_username("alice")
    settings.save_default_username(None)
    assert settings.load_default_username() is None


def test_save_default_username_blank_string_clears_it(monkeypatch, tmp_path):
    _use_tmp_data_dir(monkeypatch, tmp_path)
    settings.save_default_username("alice")
    settings.save_default_username("   ")
    assert settings.load_default_username() is None


def test_rclone_path_is_none_when_never_set(monkeypatch, tmp_path):
    _use_tmp_data_dir(monkeypatch, tmp_path)
    assert settings.load_rclone_path() is None


def test_save_and_load_rclone_path(monkeypatch, tmp_path):
    _use_tmp_data_dir(monkeypatch, tmp_path)
    settings.save_rclone_path(r"C:\tools\rclone\rclone.exe")
    assert settings.load_rclone_path() == r"C:\tools\rclone\rclone.exe"


def test_save_rclone_path_strips_whitespace(monkeypatch, tmp_path):
    _use_tmp_data_dir(monkeypatch, tmp_path)
    settings.save_rclone_path("  /opt/rclone/rclone  ")
    assert settings.load_rclone_path() == "/opt/rclone/rclone"


def test_save_rclone_path_none_clears_it(monkeypatch, tmp_path):
    _use_tmp_data_dir(monkeypatch, tmp_path)
    settings.save_rclone_path("/opt/rclone/rclone")
    settings.save_rclone_path(None)
    assert settings.load_rclone_path() is None


def test_save_rclone_path_blank_string_clears_it(monkeypatch, tmp_path):
    _use_tmp_data_dir(monkeypatch, tmp_path)
    settings.save_rclone_path("/opt/rclone/rclone")
    settings.save_rclone_path("   ")
    assert settings.load_rclone_path() is None
