import pytest

from it_toolbox.core import update_checker


class _FakeResponse:
    def __init__(self, json_data=None, status_code=200):
        self._json = json_data
        self.status_code = status_code

    def json(self):
        return self._json

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def test_get_latest_release_returns_none_when_no_release_exists(monkeypatch):
    monkeypatch.setattr(
        update_checker.requests, "get", lambda url, timeout: _FakeResponse(status_code=404)
    )

    assert update_checker.get_latest_release() is None


def test_get_latest_release_parses_tag_and_url(monkeypatch):
    monkeypatch.setattr(
        update_checker.requests,
        "get",
        lambda url, timeout: _FakeResponse(
            json_data={
                "tag_name": "v1.2.3",
                "html_url": "https://github.com/ryanvanmass/it-toolbox/releases/tag/v1.2.3",
            }
        ),
    )

    release = update_checker.get_latest_release()

    assert release.version == "1.2.3"
    assert release.html_url == "https://github.com/ryanvanmass/it-toolbox/releases/tag/v1.2.3"


@pytest.mark.parametrize(
    ("installed", "latest", "expected"),
    [
        ("1.0.0", "1.0.1", True),
        ("1.0.0", "1.0.0", False),
        ("1.0.1", "1.0.0", False),
        ("1.0.0", "not-a-version", False),
    ],
)
def test_is_update_available(installed, latest, expected):
    assert update_checker.is_update_available(installed, latest) is expected


def test_get_installed_version_reads_real_package_metadata():
    # Not mocked deliberately — the installed dev copy of it-toolbox is
    # real, so this is a genuine end-to-end check of the importlib.metadata
    # lookup rather than a re-statement of a mock.
    version = update_checker.get_installed_version()
    assert isinstance(version, str)
    assert version
