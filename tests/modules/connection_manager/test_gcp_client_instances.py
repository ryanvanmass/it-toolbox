from it_toolbox.modules.connection_manager import gcp_client


class _FakeCredentials:
    token = "fake-token"


class _FakeResponse:
    def __init__(self, json_data=None, status_code=200, text=""):
        self._json = json_data
        self.status_code = status_code
        self.text = text

    def json(self):
        return self._json


def test_start_instance_posts_to_start_endpoint(monkeypatch):
    calls = []

    def fake_post(url, headers, json, timeout):
        calls.append((url, headers, json))
        return _FakeResponse(json_data={"status": "RUNNING"})

    monkeypatch.setattr(gcp_client.requests, "post", fake_post)

    gcp_client.start_instance(_FakeCredentials(), "proj", "us-central1-a", "my-vm")

    (url, headers, body) = calls[0]
    assert url.endswith("/projects/proj/zones/us-central1-a/instances/my-vm/start")
    assert headers["Authorization"] == "Bearer fake-token"
    assert headers["X-Goog-User-Project"] == "proj"
    assert body is None


def test_stop_instance_posts_to_stop_endpoint(monkeypatch):
    calls = []

    def fake_post(url, headers, json, timeout):
        calls.append(url)
        return _FakeResponse(json_data={"status": "STOPPING"})

    monkeypatch.setattr(gcp_client.requests, "post", fake_post)

    gcp_client.stop_instance(_FakeCredentials(), "proj", "us-central1-a", "my-vm")

    assert calls[0].endswith("/projects/proj/zones/us-central1-a/instances/my-vm/stop")


def test_start_instance_raises_on_http_error(monkeypatch):
    monkeypatch.setattr(
        gcp_client.requests, "post", lambda url, headers, json, timeout: _FakeResponse(
            status_code=400, text="bad request"
        )
    )

    try:
        gcp_client.start_instance(_FakeCredentials(), "proj", "us-central1-a", "my-vm")
        raise AssertionError("expected GcpApiError")
    except gcp_client.GcpApiError:
        pass


def test_reset_windows_password_returns_username_and_password(monkeypatch):
    calls = []

    def fake_post(url, headers, json, timeout):
        calls.append((url, json))
        return _FakeResponse(json_data={"userName": "Administrator", "password": "s3cr3t!"})

    monkeypatch.setattr(gcp_client.requests, "post", fake_post)

    username, password = gcp_client.reset_windows_password(
        _FakeCredentials(), "proj", "us-central1-a", "my-vm"
    )

    assert username == "Administrator"
    assert password == "s3cr3t!"
    (url, body) = calls[0]
    assert url.endswith("/projects/proj/zones/us-central1-a/instances/my-vm/resetWindowsPassword")
    assert body == {"email": "Administrator"}


def test_reset_windows_password_uses_given_username(monkeypatch):
    calls = []

    def fake_post(url, headers, json, timeout):
        calls.append(json)
        return _FakeResponse(json_data={"userName": "alice", "password": "s3cr3t!"})

    monkeypatch.setattr(gcp_client.requests, "post", fake_post)

    gcp_client.reset_windows_password(
        _FakeCredentials(), "proj", "us-central1-a", "my-vm", username="alice"
    )

    assert calls[0] == {"email": "alice"}
