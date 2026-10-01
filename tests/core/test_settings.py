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


def test_glinet_hosts_empty_when_never_set(monkeypatch, tmp_path):
    _use_tmp_data_dir(monkeypatch, tmp_path)
    assert settings.load_glinet_hosts() == []


def test_save_and_load_glinet_hosts_round_trips(monkeypatch, tmp_path):
    _use_tmp_data_dir(monkeypatch, tmp_path)
    hosts = [
        {"name": "Travel Router", "url": "https://192.168.8.1/rpc", "username": "root",
         "verify_ssl": False, "password_encrypted": "c29tZWJhc2U2NA=="},
        {"name": "Office Router", "url": "https://192.168.9.1/rpc", "username": "admin",
         "verify_ssl": True, "password_encrypted": None},
    ]
    settings.save_glinet_hosts(hosts)
    assert settings.load_glinet_hosts() == hosts


def test_save_and_load_glinet_password_round_trips_through_real_encryption(monkeypatch, tmp_path):
    _use_tmp_data_dir(monkeypatch, tmp_path)
    key_path = _write_ssh_keypair(tmp_path)
    monkeypatch.setattr(settings, "resolve_glinet_ssh_key_path", lambda: key_path)

    encrypted = settings.encrypt_glinet_password("routerpassword")

    # Ciphertext must not contain the plaintext password anywhere.
    assert b"routerpassword" not in encrypted
    assert settings.decrypt_glinet_password(encrypted) == "routerpassword"


def test_decrypt_glinet_password_with_passphrase_protected_ssh_key(monkeypatch, tmp_path):
    _use_tmp_data_dir(monkeypatch, tmp_path)
    key_path = _write_ssh_keypair(tmp_path, passphrase=b"hunter2")
    monkeypatch.setattr(settings, "resolve_glinet_ssh_key_path", lambda: key_path)

    encrypted = settings.encrypt_glinet_password("routerpassword")

    assert settings.decrypt_glinet_password(encrypted, passphrase="hunter2") == "routerpassword"


def test_decrypt_glinet_password_passphrase_protected_without_passphrase_raises(
    monkeypatch, tmp_path
):
    _use_tmp_data_dir(monkeypatch, tmp_path)
    key_path = _write_ssh_keypair(tmp_path, passphrase=b"hunter2")
    monkeypatch.setattr(settings, "resolve_glinet_ssh_key_path", lambda: key_path)

    encrypted = settings.encrypt_glinet_password("routerpassword")

    with pytest.raises(settings.SecretDecryptionError):
        settings.decrypt_glinet_password(encrypted)


def test_decrypt_glinet_password_wrong_key_raises(monkeypatch, tmp_path):
    _use_tmp_data_dir(monkeypatch, tmp_path)
    key_path = _write_ssh_keypair(tmp_path, name="id_ed25519_a")
    monkeypatch.setattr(settings, "resolve_glinet_ssh_key_path", lambda: key_path)
    encrypted = settings.encrypt_glinet_password("routerpassword")

    other_key_path = _write_ssh_keypair(tmp_path, name="id_ed25519_b")
    monkeypatch.setattr(settings, "resolve_glinet_ssh_key_path", lambda: other_key_path)

    with pytest.raises(settings.SecretDecryptionError):
        settings.decrypt_glinet_password(encrypted)


def test_encrypt_glinet_password_no_ssh_key_found_raises(monkeypatch, tmp_path):
    _use_tmp_data_dir(monkeypatch, tmp_path)
    monkeypatch.setattr(settings, "resolve_glinet_ssh_key_path", lambda: None)

    with pytest.raises(settings.SecretDecryptionError):
        settings.encrypt_glinet_password("routerpassword")


def test_rdp_keyboard_layout_defaults_to_english_us_when_never_set(monkeypatch, tmp_path):
    _use_tmp_data_dir(monkeypatch, tmp_path)
    assert settings.load_rdp_keyboard_layout() == 0x0409


def test_save_and_load_rdp_keyboard_layout(monkeypatch, tmp_path):
    _use_tmp_data_dir(monkeypatch, tmp_path)
    settings.save_rdp_keyboard_layout(0x040C)
    assert settings.load_rdp_keyboard_layout() == 0x040C


def test_rdp_keyboard_layout_ignores_a_malformed_file(monkeypatch, tmp_path):
    _use_tmp_data_dir(monkeypatch, tmp_path)
    settings.rdp_keyboard_layout_path().write_text("not-a-layout")
    assert settings.load_rdp_keyboard_layout() == 0x0409


def test_instance_ssh_username_overrides_is_empty_when_never_set(monkeypatch, tmp_path):
    _use_tmp_data_dir(monkeypatch, tmp_path)
    assert settings.load_instance_ssh_username_overrides() == {}


def test_save_and_load_instance_ssh_username_overrides(monkeypatch, tmp_path):
    _use_tmp_data_dir(monkeypatch, tmp_path)
    overrides = {("p1", "us-central1-a", "vm-1"): "alice", ("p2", "europe-west1-b", "vm-2"): "bob"}

    settings.save_instance_ssh_username_overrides(overrides)

    assert settings.load_instance_ssh_username_overrides() == overrides


def test_instance_ssh_username_overrides_ignores_a_malformed_file(monkeypatch, tmp_path):
    _use_tmp_data_dir(monkeypatch, tmp_path)
    settings.instance_ssh_username_overrides_path().write_text("not-json")
    assert settings.load_instance_ssh_username_overrides() == {}


def test_instance_ssh_username_overrides_skips_malformed_entries(monkeypatch, tmp_path):
    _use_tmp_data_dir(monkeypatch, tmp_path)
    settings.instance_ssh_username_overrides_path().write_text(
        '[{"project_id": "p1", "zone": "us-central1-a", "name": "vm-1", "username": "alice"}, '
        '{"project_id": "p2"}]'
    )

    overrides = settings.load_instance_ssh_username_overrides()

    assert overrides == {("p1", "us-central1-a", "vm-1"): "alice"}


def test_terminal_font_size_is_none_when_never_set(monkeypatch, tmp_path):
    _use_tmp_data_dir(monkeypatch, tmp_path)
    assert settings.load_terminal_font_size() is None


def test_save_and_load_terminal_font_size(monkeypatch, tmp_path):
    _use_tmp_data_dir(monkeypatch, tmp_path)
    settings.save_terminal_font_size(14)
    assert settings.load_terminal_font_size() == 14


def test_save_terminal_font_size_none_clears_it(monkeypatch, tmp_path):
    _use_tmp_data_dir(monkeypatch, tmp_path)
    settings.save_terminal_font_size(14)
    settings.save_terminal_font_size(None)
    assert settings.load_terminal_font_size() is None


def test_terminal_font_size_ignores_a_malformed_file(monkeypatch, tmp_path):
    _use_tmp_data_dir(monkeypatch, tmp_path)
    settings.terminal_font_size_path().write_text("not-a-number")
    assert settings.load_terminal_font_size() is None


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


def test_include_prerelease_updates_defaults_to_false(monkeypatch, tmp_path):
    _use_tmp_data_dir(monkeypatch, tmp_path)
    assert settings.load_include_prerelease_updates() is False


def test_save_and_load_include_prerelease_updates(monkeypatch, tmp_path):
    _use_tmp_data_dir(monkeypatch, tmp_path)
    settings.save_include_prerelease_updates(True)
    assert settings.load_include_prerelease_updates() is True
    settings.save_include_prerelease_updates(False)
    assert settings.load_include_prerelease_updates() is False


# -- Per-GCP-instance RDP credentials ------------------------------------------

_VM = ("proj", "us-central1-a", "vm-1")


def test_instance_rdp_credentials_empty_when_never_set(monkeypatch, tmp_path):
    _use_tmp_data_dir(monkeypatch, tmp_path)
    assert settings.load_instance_rdp_credentials() == {}


def test_save_and_load_instance_rdp_credentials_round_trips(monkeypatch, tmp_path):
    _use_tmp_data_dir(monkeypatch, tmp_path)
    credentials = {
        _VM: settings.InstanceRdpCredentials("alice", b"\x00\x01ciphertext\xff"),
        ("proj", "europe-west1-b", "vm-2"): settings.InstanceRdpCredentials("bob", None),
    }

    settings.save_instance_rdp_credentials(credentials)

    assert settings.load_instance_rdp_credentials() == credentials


def test_instance_rdp_credentials_are_keyed_by_project_zone_and_name(monkeypatch, tmp_path):
    # A VM name is only unique within its project and zone.
    _use_tmp_data_dir(monkeypatch, tmp_path)
    settings.save_instance_rdp_credentials(
        {
            ("proj-a", "z", "web"): settings.InstanceRdpCredentials("alice", None),
            ("proj-b", "z", "web"): settings.InstanceRdpCredentials("bob", None),
        }
    )

    loaded = settings.load_instance_rdp_credentials()

    assert loaded[("proj-a", "z", "web")].username == "alice"
    assert loaded[("proj-b", "z", "web")].username == "bob"


def test_instance_rdp_credentials_ignore_a_malformed_file(monkeypatch, tmp_path):
    # Same "fail soft" treatment as the other JSON settings files.
    _use_tmp_data_dir(monkeypatch, tmp_path)
    settings.instance_rdp_credentials_path().write_text("{not json")
    assert settings.load_instance_rdp_credentials() == {}


def test_instance_rdp_credentials_skip_a_malformed_entry_but_keep_the_rest(monkeypatch, tmp_path):
    _use_tmp_data_dir(monkeypatch, tmp_path)
    settings.instance_rdp_credentials_path().write_text(
        '[{"project_id": "proj"},'
        ' "not a dict",'
        ' {"project_id": "proj", "zone": "z", "name": "bad", "username": "x",'
        '  "password_encrypted": "!!!not base64!!!"},'
        ' {"project_id": "proj", "zone": "z", "name": "good", "username": "alice",'
        '  "password_encrypted": null}]'
    )

    assert settings.load_instance_rdp_credentials() == {
        ("proj", "z", "good"): settings.InstanceRdpCredentials("alice", None)
    }


def test_instance_rdp_password_round_trips_through_real_encryption(monkeypatch, tmp_path):
    _use_tmp_data_dir(monkeypatch, tmp_path)
    key_path = _write_ssh_keypair(tmp_path)
    monkeypatch.setattr(settings, "resolve_instance_rdp_ssh_key_path", lambda: key_path)

    encrypted = settings.encrypt_instance_rdp_password("Sup3r-s3cret!")

    assert b"Sup3r-s3cret!" not in encrypted
    assert settings.decrypt_instance_rdp_password(encrypted) == "Sup3r-s3cret!"


def test_saved_instance_rdp_password_is_never_written_to_disk_in_plaintext(monkeypatch, tmp_path):
    _use_tmp_data_dir(monkeypatch, tmp_path)
    key_path = _write_ssh_keypair(tmp_path)
    monkeypatch.setattr(settings, "resolve_instance_rdp_ssh_key_path", lambda: key_path)
    encrypted = settings.encrypt_instance_rdp_password("Sup3r-s3cret!")

    settings.save_instance_rdp_credentials({_VM: settings.InstanceRdpCredentials("alice", encrypted)})

    on_disk = settings.instance_rdp_credentials_path().read_text()
    assert "Sup3r-s3cret!" not in on_disk
    # ...and the saved blob still decrypts to it after the JSON round trip.
    reloaded = settings.load_instance_rdp_credentials()[_VM]
    assert settings.decrypt_instance_rdp_password(reloaded.password_encrypted) == "Sup3r-s3cret!"


def test_decrypt_instance_rdp_password_with_passphrase_protected_ssh_key(monkeypatch, tmp_path):
    _use_tmp_data_dir(monkeypatch, tmp_path)
    key_path = _write_ssh_keypair(tmp_path, passphrase=b"hunter2")
    monkeypatch.setattr(settings, "resolve_instance_rdp_ssh_key_path", lambda: key_path)
    encrypted = settings.encrypt_instance_rdp_password("Sup3r-s3cret!")

    assert settings.decrypt_instance_rdp_password(encrypted, passphrase="hunter2") == "Sup3r-s3cret!"
    with pytest.raises(settings.SecretDecryptionError):
        settings.decrypt_instance_rdp_password(encrypted)  # no passphrase


def test_decrypt_instance_rdp_password_with_a_different_key_raises(monkeypatch, tmp_path):
    _use_tmp_data_dir(monkeypatch, tmp_path)
    original = _write_ssh_keypair(tmp_path, name="id_ed25519_a")
    other = _write_ssh_keypair(tmp_path, name="id_ed25519_b")
    monkeypatch.setattr(settings, "resolve_instance_rdp_ssh_key_path", lambda: original)
    encrypted = settings.encrypt_instance_rdp_password("Sup3r-s3cret!")
    monkeypatch.setattr(settings, "resolve_instance_rdp_ssh_key_path", lambda: other)

    with pytest.raises(settings.SecretDecryptionError):
        settings.decrypt_instance_rdp_password(encrypted)


def test_encrypt_instance_rdp_password_without_any_ssh_key_raises(monkeypatch, tmp_path):
    _use_tmp_data_dir(monkeypatch, tmp_path)
    monkeypatch.setattr(settings, "resolve_instance_rdp_ssh_key_path", lambda: None)

    with pytest.raises(settings.SecretDecryptionError, match="No SSH key found"):
        settings.encrypt_instance_rdp_password("Sup3r-s3cret!")
