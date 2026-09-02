from pathlib import Path

from platformdirs import user_data_dir

APP_NAME = "it-toolbox"


def data_dir() -> Path:
    """Cross-platform app-data directory for local storage (DB, cached state)."""
    path = Path(user_data_dir(APP_NAME))
    path.mkdir(parents=True, exist_ok=True)
    return path
