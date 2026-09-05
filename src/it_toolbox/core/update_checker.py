"""Checks the installed app version against GitHub Releases — see
docs/releasing.md for how a release actually gets published (a version
tag pushed by hand, never by the app itself).
"""

from dataclasses import dataclass
from importlib import metadata

import requests
from packaging.version import InvalidVersion, Version

PACKAGE_NAME = "it-toolbox"
REPO = "ryanvanmass/it-toolbox"
_LATEST_RELEASE_URL = f"https://api.github.com/repos/{REPO}/releases/latest"
_REQUEST_TIMEOUT = 10


@dataclass(frozen=True)
class ReleaseInfo:
    version: str
    html_url: str


def get_installed_version() -> str:
    return metadata.version(PACKAGE_NAME)


def get_latest_release() -> ReleaseInfo | None:
    """None means no release has been published yet (a real, expected
    state right now — see docs/releasing.md), not an error."""
    response = requests.get(_LATEST_RELEASE_URL, timeout=_REQUEST_TIMEOUT)
    if response.status_code == 404:
        return None
    response.raise_for_status()
    data = response.json()
    tag_name = data["tag_name"]
    version = tag_name.removeprefix("v")
    return ReleaseInfo(version=version, html_url=data["html_url"])


def is_update_available(installed_version: str, latest_version: str) -> bool:
    try:
        return Version(latest_version) > Version(installed_version)
    except InvalidVersion:
        # Unparseable version strings shouldn't crash the check — treat as
        # "can't tell, assume up to date" rather than surfacing an error for
        # what's ultimately just a version display comparison.
        return False
