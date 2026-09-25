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


def test_get_iam_policy_posts_to_get_iam_policy_endpoint(monkeypatch):
    calls = []

    def fake_post(url, headers, params, json, timeout):
        calls.append((url, headers, json))
        return _FakeResponse(json_data={"bindings": []})

    monkeypatch.setattr(gcp_client.requests, "post", fake_post)

    gcp_client.get_iam_policy(_FakeCredentials(), "proj")

    (url, headers, body) = calls[0]
    assert url.endswith("/projects/proj:getIamPolicy")
    assert headers["Authorization"] == "Bearer fake-token"
    assert headers["X-Goog-User-Project"] == "proj"
    assert body is None


def test_get_iam_policy_flattens_one_row_per_member(monkeypatch):
    response = _FakeResponse(
        json_data={
            "bindings": [
                {
                    "role": "roles/owner",
                    "members": ["user:alice@example.com", "user:bob@example.com"],
                },
                {"role": "roles/viewer", "members": ["group:team@example.com"]},
            ]
        }
    )
    monkeypatch.setattr(gcp_client.requests, "post", lambda *a, **k: response)

    bindings = gcp_client.get_iam_policy(_FakeCredentials(), "proj")

    assert len(bindings) == 3
    assert all(b.project_id == "proj" for b in bindings)
    assert {(b.role, b.member) for b in bindings} == {
        ("roles/owner", "user:alice@example.com"),
        ("roles/owner", "user:bob@example.com"),
        ("roles/viewer", "group:team@example.com"),
    }


def test_get_iam_policy_sorts_by_role_then_member(monkeypatch):
    response = _FakeResponse(
        json_data={
            "bindings": [
                {"role": "roles/viewer", "members": ["user:zed@example.com"]},
                {"role": "roles/owner", "members": ["user:bob@example.com", "user:alice@example.com"]},
            ]
        }
    )
    monkeypatch.setattr(gcp_client.requests, "post", lambda *a, **k: response)

    bindings = gcp_client.get_iam_policy(_FakeCredentials(), "proj")

    assert [(b.role, b.member) for b in bindings] == [
        ("roles/owner", "user:alice@example.com"),
        ("roles/owner", "user:bob@example.com"),
        ("roles/viewer", "user:zed@example.com"),
    ]


def test_get_iam_policy_with_no_bindings_returns_empty_list(monkeypatch):
    monkeypatch.setattr(
        gcp_client.requests, "post", lambda *a, **k: _FakeResponse(json_data={})
    )

    assert gcp_client.get_iam_policy(_FakeCredentials(), "proj") == []


def test_get_iam_policy_raises_on_http_error(monkeypatch):
    monkeypatch.setattr(
        gcp_client.requests,
        "post",
        lambda url, headers, params, json, timeout: _FakeResponse(
            status_code=403, text="permission denied"
        ),
    )

    try:
        gcp_client.get_iam_policy(_FakeCredentials(), "proj")
        raise AssertionError("expected GcpApiError")
    except gcp_client.GcpApiError:
        pass
