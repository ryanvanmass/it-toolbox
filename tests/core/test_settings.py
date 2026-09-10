import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from it_toolbox.core import settings


def _use_tmp_data_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", lambda: tmp_path)


def _write_ssh_keypair(tmp_path, name="id_ed25519", passphrase: bytes | None = None):
    """A throwaway ed25519 keypair generated purely via `cryptography` —
    no ssh-keygen binary needed, keeping this hermetic like the rest of
    the suite.
    """
    key = Ed25519PrivateKey.generate()
    encryption = (
        serialization.BestAvailableEncryption(passphrase)
        if passphrase
        else serialization.NoEncryption()
    )
    private_path = tmp_path / name
    private_path.write_bytes(
        key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.OpenSSH,
            encryption_algorithm=encryption,
        )
    )
    public_path = tmp_path / f"{name}.pub"
    public_path.write_bytes(
        key.public_key().public_bytes(
            encoding=serialization.Encoding.OpenSSH,
            format=serialization.PublicFormat.OpenSSH,
        )
    )
    return private_path


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


def test_jumpcloud_api_key_is_none_when_never_set(monkeypatch, tmp_path):
    _use_tmp_data_dir(monkeypatch, tmp_path)
    key_path = _write_ssh_keypair(tmp_path)
    monkeypatch.setattr(settings, "resolve_jumpcloud_ssh_key_path", lambda: key_path)

    assert settings.load_jumpcloud_api_key() is None


def test_save_and_load_jumpcloud_api_key_round_trips_through_real_encryption(monkeypatch, tmp_path):
    _use_tmp_data_dir(monkeypatch, tmp_path)
    key_path = _write_ssh_keypair(tmp_path)
    monkeypatch.setattr(settings, "resolve_jumpcloud_ssh_key_path", lambda: key_path)

    settings.save_jumpcloud_api_key("jca_supersecret")

    # Stored ciphertext must not contain the plaintext key anywhere.
    assert b"jca_supersecret" not in settings.jumpcloud_api_key_path().read_bytes()
    assert settings.load_jumpcloud_api_key() == "jca_supersecret"


def test_save_jumpcloud_api_key_none_clears_it(monkeypatch, tmp_path):
    _use_tmp_data_dir(monkeypatch, tmp_path)
    key_path = _write_ssh_keypair(tmp_path)
    monkeypatch.setattr(settings, "resolve_jumpcloud_ssh_key_path", lambda: key_path)

    settings.save_jumpcloud_api_key("jca_supersecret")
    settings.save_jumpcloud_api_key(None)

    assert settings.load_jumpcloud_api_key() is None
    assert not settings.jumpcloud_api_key_path().is_file()


def test_load_jumpcloud_api_key_with_passphrase_protected_ssh_key(monkeypatch, tmp_path):
    _use_tmp_data_dir(monkeypatch, tmp_path)
    key_path = _write_ssh_keypair(tmp_path, passphrase=b"hunter2")
    monkeypatch.setattr(settings, "resolve_jumpcloud_ssh_key_path", lambda: key_path)

    settings.save_jumpcloud_api_key("jca_supersecret")

    assert settings.load_jumpcloud_api_key(passphrase="hunter2") == "jca_supersecret"


def test_load_jumpcloud_api_key_passphrase_protected_without_passphrase_raises(monkeypatch, tmp_path):
    _use_tmp_data_dir(monkeypatch, tmp_path)
    key_path = _write_ssh_keypair(tmp_path, passphrase=b"hunter2")
    monkeypatch.setattr(settings, "resolve_jumpcloud_ssh_key_path", lambda: key_path)

    settings.save_jumpcloud_api_key("jca_supersecret")

    with pytest.raises(settings.SecretDecryptionError):
        settings.load_jumpcloud_api_key()


def test_load_jumpcloud_api_key_wrong_key_raises(monkeypatch, tmp_path):
    _use_tmp_data_dir(monkeypatch, tmp_path)
    key_path = _write_ssh_keypair(tmp_path, name="id_ed25519_a")
    monkeypatch.setattr(settings, "resolve_jumpcloud_ssh_key_path", lambda: key_path)
    settings.save_jumpcloud_api_key("jca_supersecret")

    other_key_path = _write_ssh_keypair(tmp_path, name="id_ed25519_b")
    monkeypatch.setattr(settings, "resolve_jumpcloud_ssh_key_path", lambda: other_key_path)

    with pytest.raises(settings.SecretDecryptionError):
        settings.load_jumpcloud_api_key()


def test_save_jumpcloud_api_key_no_ssh_key_found_raises(monkeypatch, tmp_path):
    _use_tmp_data_dir(monkeypatch, tmp_path)
    monkeypatch.setattr(settings, "resolve_jumpcloud_ssh_key_path", lambda: None)

    with pytest.raises(settings.SecretDecryptionError):
        settings.save_jumpcloud_api_key("jca_supersecret")


def test_jumpcloud_ssh_key_path_override_round_trips(monkeypatch, tmp_path):
    _use_tmp_data_dir(monkeypatch, tmp_path)
    assert settings.load_jumpcloud_ssh_key_path() is None

    settings.save_jumpcloud_ssh_key_path(str(tmp_path / "custom_key"))
    assert settings.load_jumpcloud_ssh_key_path() == tmp_path / "custom_key"

    settings.save_jumpcloud_ssh_key_path(None)
    assert settings.load_jumpcloud_ssh_key_path() is None


def test_default_ssh_key_path_prefers_ed25519_over_rsa(monkeypatch, tmp_path):
    monkeypatch.setattr(settings.Path, "home", staticmethod(lambda: tmp_path))
    ssh_dir = tmp_path / ".ssh"
    ssh_dir.mkdir()
    (ssh_dir / "id_rsa").write_text("rsa")
    (ssh_dir / "id_ed25519").write_text("ed25519")

    assert settings.default_ssh_key_path() == ssh_dir / "id_ed25519"


def test_default_ssh_key_path_none_when_neither_exists(monkeypatch, tmp_path):
    monkeypatch.setattr(settings.Path, "home", staticmethod(lambda: tmp_path))
    (tmp_path / ".ssh").mkdir()

    assert settings.default_ssh_key_path() is None


def test_gcp_ssh_key_path_override_round_trips(monkeypatch, tmp_path):
    _use_tmp_data_dir(monkeypatch, tmp_path)
    assert settings.load_gcp_ssh_key_path() is None

    settings.save_gcp_ssh_key_path(str(tmp_path / "custom_key"))
    assert settings.load_gcp_ssh_key_path() == tmp_path / "custom_key"

    settings.save_gcp_ssh_key_path(None)
    assert settings.load_gcp_ssh_key_path() is None


def test_resolve_gcp_ssh_public_key_uses_explicit_override(monkeypatch, tmp_path):
    _use_tmp_data_dir(monkeypatch, tmp_path)
    key_path = _write_ssh_keypair(tmp_path, name="custom_key")
    settings.save_gcp_ssh_key_path(str(key_path))

    public_key = settings.resolve_gcp_ssh_public_key()

    assert public_key == (tmp_path / "custom_key.pub").read_text().strip()


def test_resolve_gcp_ssh_public_key_accepts_a_pub_file_directly(monkeypatch, tmp_path):
    _use_tmp_data_dir(monkeypatch, tmp_path)
    _write_ssh_keypair(tmp_path, name="custom_key")
    settings.save_gcp_ssh_key_path(str(tmp_path / "custom_key.pub"))

    public_key = settings.resolve_gcp_ssh_public_key()

    assert public_key == (tmp_path / "custom_key.pub").read_text().strip()


def test_resolve_gcp_ssh_public_key_falls_back_to_default_ssh_key_path(monkeypatch, tmp_path):
    _use_tmp_data_dir(monkeypatch, tmp_path)
    key_path = _write_ssh_keypair(tmp_path, name="id_ed25519")
    monkeypatch.setattr(settings, "default_ssh_key_path", lambda: key_path)

    public_key = settings.resolve_gcp_ssh_public_key()

    assert public_key == (tmp_path / "id_ed25519.pub").read_text().strip()


def test_resolve_gcp_ssh_public_key_is_none_when_nothing_resolves(monkeypatch, tmp_path):
    _use_tmp_data_dir(monkeypatch, tmp_path)
    monkeypatch.setattr(settings, "default_ssh_key_path", lambda: None)

    assert settings.resolve_gcp_ssh_public_key() is None


def test_resolve_gcp_ssh_public_key_is_none_when_pub_file_missing(monkeypatch, tmp_path):
    _use_tmp_data_dir(monkeypatch, tmp_path)
    private_only = tmp_path / "no_pub_key"
    private_only.write_text("not a real key, just needs to exist")
    settings.save_gcp_ssh_key_path(str(private_only))

    assert settings.resolve_gcp_ssh_public_key() is None


def test_default_rdp_resolution_is_none_when_never_set(monkeypatch, tmp_path):
    _use_tmp_data_dir(monkeypatch, tmp_path)
    assert settings.load_default_rdp_resolution() is None


def test_save_and_load_default_rdp_resolution(monkeypatch, tmp_path):
    _use_tmp_data_dir(monkeypatch, tmp_path)
    settings.save_default_rdp_resolution((1920, 1080))
    assert settings.load_default_rdp_resolution() == (1920, 1080)


def test_save_default_rdp_resolution_none_clears_it(monkeypatch, tmp_path):
    _use_tmp_data_dir(monkeypatch, tmp_path)
    settings.save_default_rdp_resolution((1920, 1080))
    settings.save_default_rdp_resolution(None)
    assert settings.load_default_rdp_resolution() is None


def test_default_rdp_resolution_ignores_a_malformed_file(monkeypatch, tmp_path):
    # Defends against a corrupted/hand-edited settings file crashing the
    # app on startup — same "fail soft to the default" treatment as the
    # JSON settings files' except (json.JSONDecodeError, OSError) guards.
    _use_tmp_data_dir(monkeypatch, tmp_path)
    settings.default_rdp_resolution_path().write_text("not-a-resolution")
    assert settings.load_default_rdp_resolution() is None


def test_default_double_click_action_is_ask_when_never_set(monkeypatch, tmp_path):
    _use_tmp_data_dir(monkeypatch, tmp_path)
    assert settings.load_default_double_click_action() == "ask"


def test_save_and_load_default_double_click_action(monkeypatch, tmp_path):
    _use_tmp_data_dir(monkeypatch, tmp_path)
    settings.save_default_double_click_action("rdp")
    assert settings.load_default_double_click_action() == "rdp"
    settings.save_default_double_click_action("ssh")
    assert settings.load_default_double_click_action() == "ssh"


def test_default_double_click_action_ignores_a_malformed_file(monkeypatch, tmp_path):
    _use_tmp_data_dir(monkeypatch, tmp_path)
    settings.default_double_click_action_path().write_text("not-a-real-action")
    assert settings.load_default_double_click_action() == "ask"
