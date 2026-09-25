import json
import subprocess

import pytest

from it_toolbox.core.auth import gcp_auth

# gcloud's real wording (hard-wrapped, as it prints it) when the component
# manager is disabled, e.g. for a dnf-installed google-cloud-cli.
_DISABLED_STDERR = """ERROR: (gcloud.components.update)
You cannot perform this action because the Google Cloud CLI component manager
is disabled for this installation. You can run the following command
to achieve the same result for this installation:

sudo dnf makecache && sudo dnf upgrade google-cloud-cli

"""


class _FakeGcloud:
    """Stands in for subprocess.run: answers `gcloud version` with the
    current version and `gcloud components update` with the given outcome.
    """

    def __init__(self, version="540.0.0", updated_version=None, update_stderr=None):
        self.version = version
        self.updated_version = updated_version
        self.update_stderr = update_stderr
        self.calls = []

    def __call__(self, args, **kwargs):
        self.calls.append(args[1:])
        if args[1] == "version":
            stdout = json.dumps({"Google Cloud SDK": self.version, "core": "2026.09.01"})
            return subprocess.CompletedProcess(args, 0, stdout=stdout, stderr="")
        if args[1:3] == ["components", "update"]:
            if self.update_stderr is not None:
                return subprocess.CompletedProcess(args, 1, stdout="", stderr=self.update_stderr)
            if self.updated_version is not None:
                self.version = self.updated_version
            return subprocess.CompletedProcess(args, 0, stdout="", stderr="")
        raise AssertionError(f"unexpected gcloud call: {args}")


@pytest.fixture
def fake_gcloud(monkeypatch):
    def _install(**kwargs):
        fake = _FakeGcloud(**kwargs)
        monkeypatch.setattr(gcp_auth, "is_available", lambda: True)
        monkeypatch.setattr(gcp_auth.subprocess, "run", fake)
        return fake

    return _install


def test_get_version_reads_sdk_version(fake_gcloud):
    fake_gcloud(version="540.0.0")

    assert gcp_auth.get_version() == "540.0.0"


def test_update_runs_components_update_quietly(fake_gcloud):
    fake = fake_gcloud(version="540.0.0", updated_version="541.0.0")

    assert gcp_auth.update() == ("540.0.0", "541.0.0")
    assert ["components", "update", "--quiet"] in fake.calls


def test_update_when_already_up_to_date_returns_same_versions(fake_gcloud):
    fake_gcloud(version="540.0.0")

    assert gcp_auth.update() == ("540.0.0", "540.0.0")


def test_update_on_package_manager_install_raises_with_suggested_command(fake_gcloud):
    fake_gcloud(update_stderr=_DISABLED_STDERR)

    with pytest.raises(gcp_auth.GcloudUpdateUnsupported) as excinfo:
        gcp_auth.update()

    assert excinfo.value.suggested_command == (
        "sudo dnf makecache && sudo dnf upgrade google-cloud-cli"
    )


def test_update_on_package_manager_install_without_a_command(fake_gcloud):
    fake_gcloud(
        update_stderr="ERROR: the Google Cloud CLI component manager\nis disabled here."
    )

    with pytest.raises(gcp_auth.GcloudUpdateUnsupported) as excinfo:
        gcp_auth.update()

    assert excinfo.value.suggested_command is None


def test_update_other_failures_raise_runtime_error(fake_gcloud):
    fake_gcloud(update_stderr="ERROR: Permission denied: 'C:\\Program Files\\Google'")

    with pytest.raises(RuntimeError, match="Permission denied") as excinfo:
        gcp_auth.update()

    assert not isinstance(excinfo.value, gcp_auth.GcloudUpdateUnsupported)


def test_update_without_gcloud_raises_not_found(monkeypatch):
    monkeypatch.setattr(gcp_auth, "is_available", lambda: False)

    with pytest.raises(gcp_auth.GcloudNotFound):
        gcp_auth.update()
