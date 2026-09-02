import keyring
import pytest
from google.oauth2.credentials import Credentials
from keyring.backend import KeyringBackend

from it_toolbox.core.auth import credential_store


class InMemoryKeyring(KeyringBackend):
    priority = 1

    def __init__(self):
        self._store = {}

    def set_password(self, service, username, password):
        self._store[(service, username)] = password

    def get_password(self, service, username):
        return self._store.get((service, username))

    def delete_password(self, service, username):
        self._store.pop((service, username), None)


@pytest.fixture(autouse=True)
def fake_keyring():
    original = keyring.get_keyring()
    keyring.set_keyring(InMemoryKeyring())
    yield
    keyring.set_keyring(original)


def test_round_trip_save_and_load():
    credentials = Credentials(
        token="access-token",
        refresh_token="refresh-token",
        client_id="client-id",
        client_secret="client-secret",
        token_uri="https://oauth2.googleapis.com/token",
        scopes=["https://www.googleapis.com/auth/cloud-platform"],
    )

    credential_store.save_credentials(credentials)
    loaded = credential_store.load_credentials()

    assert loaded is not None
    assert loaded.token == "access-token"
    assert loaded.refresh_token == "refresh-token"


def test_load_returns_none_when_nothing_saved():
    assert credential_store.load_credentials() is None


def test_clear_credentials_is_idempotent():
    credential_store.clear_credentials()
    credential_store.clear_credentials()
