from pathlib import Path

from platformdirs import user_config_dir, user_data_dir

APP_NAME = "it-toolbox"


def data_dir() -> Path:
    """Cross-platform app-data directory for local storage (DB, cached state)."""
    path = Path(user_data_dir(APP_NAME))
    path.mkdir(parents=True, exist_ok=True)
    return path


def config_dir() -> Path:
    """Cross-platform config directory for user-provided config (OAuth client)."""
    path = Path(user_config_dir(APP_NAME))
    path.mkdir(parents=True, exist_ok=True)
    return path


def oauth_client_path() -> Path:
    """Where the user places their downloaded OAuth 'Desktop app' client JSON."""
    return config_dir() / "oauth_client.json"
