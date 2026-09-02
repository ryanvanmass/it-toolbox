from platformdirs import user_data_dir

APP_NAME = "it-toolbox"


def data_dir():
    """Cross-platform app-data directory for local storage (DB, cached state)."""
    from pathlib import Path

    path = Path(user_data_dir(APP_NAME))
    path.mkdir(parents=True, exist_ok=True)
    return path
