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


def _instance_response(metadata_items=None, fingerprint="abc123"):
    return _FakeResponse(
        json_data={"metadata": {"fingerprint": fingerprint, "items": metadata_items or []}}
    )


def test_add_ssh_key_fetches_the_instance_first(monkeypatch):
    get_calls = []

    def fake_get(url, headers, params, timeout):
        get_calls.append((url, headers))
        return _instance_response()

    monkeypatch.setattr(gcp_client.requests, "get", fake_get)
    monkeypatch.setattr(
        gcp_client.requests, "post", lambda *a, **k: _FakeResponse(json_data={})
    )

    gcp_client.add_ssh_key(_FakeCredentials(), "proj", "us-central1-a", "vm", "alice", "ssh-ed25519 AAAA")

    (url, headers) = get_calls[0]
    assert url.endswith("/projects/proj/zones/us-central1-a/instances/vm")
    assert headers["Authorization"] == "Bearer fake-token"
    assert headers["X-Goog-User-Project"] == "proj"


def test_add_ssh_key_creates_new_ssh_keys_item_when_none_exists(monkeypatch):
    monkeypatch.setattr(gcp_client.requests, "get", lambda *a, **k: _instance_response())
    calls = []

    def fake_post(url, headers, params, json, timeout):
        calls.append((url, headers, json))
        return _FakeResponse(json_data={})

    monkeypatch.setattr(gcp_client.requests, "post", fake_post)

    gcp_client.add_ssh_key(
        _FakeCredentials(), "proj", "us-central1-a", "vm", "alice", "ssh-ed25519 AAAA alice@laptop"
    )

    (url, headers, body) = calls[0]
    assert url.endswith("/projects/proj/zones/us-central1-a/instances/vm/setMetadata")
    assert headers["X-Goog-User-Project"] == "proj"
    assert body["fingerprint"] == "abc123"
    assert body["items"] == [
        {"key": "ssh-keys", "value": "alice:ssh-ed25519 AAAA alice@laptop"}
    ]


def test_add_ssh_key_appends_to_an_existing_ssh_keys_item(monkeypatch):
    existing = [{"key": "ssh-keys", "value": "bob:ssh-rsa BBBB bob@work"}]
    monkeypatch.setattr(gcp_client.requests, "get", lambda *a, **k: _instance_response(existing))
    calls = []
    monkeypatch.setattr(
        gcp_client.requests,
        "post",
        lambda url, headers, params, json, timeout: calls.append(json) or _FakeResponse(json_data={}),
    )

    gcp_client.add_ssh_key(
        _FakeCredentials(), "proj", "us-central1-a", "vm", "alice", "ssh-ed25519 AAAA alice@laptop"
    )

    (item,) = [i for i in calls[0]["items"] if i["key"] == "ssh-keys"]
    assert item["value"] == "bob:ssh-rsa BBBB bob@work\nalice:ssh-ed25519 AAAA alice@laptop"


def test_add_ssh_key_does_not_duplicate_an_identical_existing_entry(monkeypatch):
    existing = [{"key": "ssh-keys", "value": "alice:ssh-ed25519 AAAA alice@laptop"}]
    monkeypatch.setattr(gcp_client.requests, "get", lambda *a, **k: _instance_response(existing))
    calls = []
    monkeypatch.setattr(
        gcp_client.requests,
        "post",
        lambda url, headers, params, json, timeout: calls.append(json) or _FakeResponse(json_data={}),
    )

    gcp_client.add_ssh_key(
        _FakeCredentials(), "proj", "us-central1-a", "vm", "alice", "ssh-ed25519 AAAA alice@laptop"
    )

    (item,) = [i for i in calls[0]["items"] if i["key"] == "ssh-keys"]
    assert item["value"] == "alice:ssh-ed25519 AAAA alice@laptop"


def test_add_ssh_key_preserves_other_metadata_items(monkeypatch):
    existing = [{"key": "enable-oslogin", "value": "FALSE"}]
    monkeypatch.setattr(gcp_client.requests, "get", lambda *a, **k: _instance_response(existing))
    calls = []
    monkeypatch.setattr(
        gcp_client.requests,
        "post",
        lambda url, headers, params, json, timeout: calls.append(json) or _FakeResponse(json_data={}),
    )

    gcp_client.add_ssh_key(
        _FakeCredentials(), "proj", "us-central1-a", "vm", "alice", "ssh-ed25519 AAAA alice@laptop"
    )

    keys = {i["key"] for i in calls[0]["items"]}
    assert keys == {"enable-oslogin", "ssh-keys"}
    (oslogin_item,) = [i for i in calls[0]["items"] if i["key"] == "enable-oslogin"]
    assert oslogin_item["value"] == "FALSE"


def test_add_ssh_key_raises_on_http_error_fetching_the_instance(monkeypatch):
    monkeypatch.setattr(
        gcp_client.requests,
        "get",
        lambda *a, **k: _FakeResponse(status_code=404, text="not found"),
    )

    try:
        gcp_client.add_ssh_key(_FakeCredentials(), "proj", "us-central1-a", "vm", "alice", "key")
        raise AssertionError("expected GcpApiError")
    except gcp_client.GcpApiError:
        pass


def test_add_ssh_key_raises_on_http_error_setting_metadata(monkeypatch):
    monkeypatch.setattr(gcp_client.requests, "get", lambda *a, **k: _instance_response())
    monkeypatch.setattr(
        gcp_client.requests,
        "post",
        lambda *a, **k: _FakeResponse(status_code=403, text="permission denied"),
    )

    try:
        gcp_client.add_ssh_key(_FakeCredentials(), "proj", "us-central1-a", "vm", "alice", "key")
        raise AssertionError("expected GcpApiError")
    except gcp_client.GcpApiError:
        pass
