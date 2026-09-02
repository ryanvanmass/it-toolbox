import json

import keyring
from google.oauth2.credentials import Credentials

SERVICE_NAME = "it-toolbox"
USERNAME = "gcp-oauth"


def save_credentials(credentials: Credentials) -> None:
    keyring.set_password(SERVICE_NAME, USERNAME, credentials.to_json())


def load_credentials() -> Credentials | None:
    blob = keyring.get_password(SERVICE_NAME, USERNAME)
    if blob is None:
        return None
    return Credentials.from_authorized_user_info(json.loads(blob))


def clear_credentials() -> None:
    try:
        keyring.delete_password(SERVICE_NAME, USERNAME)
    except keyring.errors.PasswordDeleteError:
        pass
