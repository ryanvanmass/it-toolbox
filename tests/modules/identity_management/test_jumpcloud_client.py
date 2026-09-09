from it_toolbox.modules.identity_management import jumpcloud_client


class _FakeCredentials:
    pass


class _FakeResponse:
    def __init__(self, json_data=None, status_code=200, text=""):
        self._json = json_data
        self.status_code = status_code
        self.text = text

    def json(self):
        return self._json


def test_list_devices_sends_x_api_key_header_not_bearer(monkeypatch):
    calls = []

    def fake_get(url, headers, params, timeout):
        calls.append(headers)
        return _FakeResponse(json_data={"results": []})

    monkeypatch.setattr(jumpcloud_client.requests, "get", fake_get)

    jumpcloud_client.list_devices("jca_testkey")

    headers = calls[0]
    assert headers["x-api-key"] == "jca_testkey"
    assert "Authorization" not in headers


def test_list_devices_single_page(monkeypatch):
    def fake_get(url, headers, params, timeout):
        assert url.endswith("/api/systems")
        return _FakeResponse(
            json_data={
                "results": [
                    {"id": "d2", "displayName": "zeta", "os": "linux", "hostname": "zeta-host"},
                    {"id": "d1", "displayName": "alpha", "os": "windows", "hostname": "alpha-host"},
                ]
            }
        )

    monkeypatch.setattr(jumpcloud_client.requests, "get", fake_get)

    devices = jumpcloud_client.list_devices("jca_testkey")

    assert [d.display_name for d in devices] == ["alpha", "zeta"]  # sorted case-insensitively
    assert devices[0].id == "d1"
    assert devices[0].os == "windows"
    assert devices[0].hostname == "alpha-host"


def test_list_devices_paginates_until_a_short_page(monkeypatch):
    calls = []

    def fake_get(url, headers, params, timeout):
        calls.append(params["skip"])
        if params["skip"] == 0:
            results = [
                {"id": f"d{i}", "displayName": f"d{i}", "os": "linux"}
                for i in range(jumpcloud_client.LIST_PAGE_LIMIT)
            ]
            return _FakeResponse(json_data={"results": results})
        return _FakeResponse(json_data={"results": [{"id": "last", "displayName": "last", "os": "linux"}]})

    monkeypatch.setattr(jumpcloud_client.requests, "get", fake_get)

    devices = jumpcloud_client.list_devices("jca_testkey")

    assert calls == [0, jumpcloud_client.LIST_PAGE_LIMIT]
    assert len(devices) == jumpcloud_client.LIST_PAGE_LIMIT + 1


def test_list_devices_empty_result(monkeypatch):
    monkeypatch.setattr(
        jumpcloud_client.requests,
        "get",
        lambda url, headers, params, timeout: _FakeResponse(json_data={"results": []}),
    )

    assert jumpcloud_client.list_devices("jca_testkey") == []


def test_list_devices_raises_on_http_error(monkeypatch):
    monkeypatch.setattr(
        jumpcloud_client.requests,
        "get",
        lambda url, headers, params, timeout: _FakeResponse(status_code=401, text="unauthorized"),
    )

    try:
        jumpcloud_client.list_devices("jca_badkey")
        raise AssertionError("expected JumpCloudApiError")
    except jumpcloud_client.JumpCloudApiError:
        pass


def test_get_device_maps_detail_fields(monkeypatch):
    def fake_get(url, headers, params, timeout):
        assert url.endswith("/api/systems/d1")
        return _FakeResponse(
            json_data={
                "id": "d1",
                "displayName": "alpha",
                "os": "windows",
                "hostname": "alpha-host",
                "version": "10.0.19045",
                "serialNumber": "ABC123",
                "agentVersion": "1.2.3",
                "lastContact": "2026-09-05T00:00:00Z",
                "active": True,
                "created": "2025-01-01T00:00:00Z",
                "remoteIP": "203.0.113.5",
                "arch": "x86_64",
                "description": "Finance laptop",
            }
        )

    monkeypatch.setattr(jumpcloud_client.requests, "get", fake_get)

    device = jumpcloud_client.get_device("jca_testkey", "d1")

    assert device.id == "d1"
    assert device.os_version == "10.0.19045"
    assert device.serial_number == "ABC123"
    assert device.agent_version == "1.2.3"
    assert device.last_contact == "2026-09-05T00:00:00Z"
    assert device.created == "2025-01-01T00:00:00Z"
    assert device.remote_ip == "203.0.113.5"
    assert device.arch == "x86_64"
    assert device.description == "Finance laptop"


def test_get_device_raises_on_http_error(monkeypatch):
    monkeypatch.setattr(
        jumpcloud_client.requests,
        "get",
        lambda url, headers, params, timeout: _FakeResponse(status_code=404, text="not found"),
    )

    try:
        jumpcloud_client.get_device("jca_testkey", "missing")
        raise AssertionError("expected JumpCloudApiError")
    except jumpcloud_client.JumpCloudApiError:
        pass


def test_list_users_single_page(monkeypatch):
    def fake_get(url, headers, params, timeout):
        assert url.endswith("/api/systemusers")
        return _FakeResponse(
            json_data={
                "results": [
                    {"id": "u2", "username": "zed", "email": "zed@example.com"},
                    {"id": "u1", "username": "alice", "email": "alice@example.com"},
                ]
            }
        )

    monkeypatch.setattr(jumpcloud_client.requests, "get", fake_get)

    users = jumpcloud_client.list_users("jca_testkey")

    assert [u.username for u in users] == ["alice", "zed"]
    assert users[0].email == "alice@example.com"


def test_list_users_maps_name_and_suspended_fields(monkeypatch):
    monkeypatch.setattr(
        jumpcloud_client.requests,
        "get",
        lambda url, headers, params, timeout: _FakeResponse(
            json_data={
                "results": [
                    {
                        "id": "u1",
                        "username": "alice",
                        "email": "alice@example.com",
                        "firstname": "Alice",
                        "lastname": "Anderson",
                        "suspended": True,
                    }
                ]
            }
        ),
    )

    (user,) = jumpcloud_client.list_users("jca_testkey")

    assert user.first_name == "Alice"
    assert user.last_name == "Anderson"
    assert user.suspended is True


def test_list_users_maps_general_info_fields(monkeypatch):
    monkeypatch.setattr(
        jumpcloud_client.requests,
        "get",
        lambda url, headers, params, timeout: _FakeResponse(
            json_data={
                "results": [
                    {
                        "id": "u1",
                        "username": "alice",
                        "email": "alice@example.com",
                        "activated": False,
                        "created": "2024-06-01T00:00:00Z",
                        "department": "R&D",
                        "jobTitle": "Engineer",
                        "mfa": {"configured": True},
                    }
                ]
            }
        ),
    )

    (user,) = jumpcloud_client.list_users("jca_testkey")

    assert user.activated is False
    assert user.created == "2024-06-01T00:00:00Z"
    assert user.department == "R&D"
    assert user.job_title == "Engineer"
    assert user.mfa_configured is True


def test_list_users_defaults_mfa_configured_false_when_field_missing(monkeypatch):
    # The "mfa" object's exact shape is the least-confirmed field here
    # (see jumpcloud_client.py's _user_from_json) -- a missing/differently
    # shaped field should degrade quietly, not raise.
    monkeypatch.setattr(
        jumpcloud_client.requests,
        "get",
        lambda url, headers, params, timeout: _FakeResponse(
            json_data={"results": [{"id": "u1", "username": "alice", "email": "a@example.com"}]}
        ),
    )

    (user,) = jumpcloud_client.list_users("jca_testkey")

    assert user.mfa_configured is False


def test_connection_uses_a_minimal_single_item_page(monkeypatch):
    calls = []

    def fake_get(url, headers, params, timeout):
        calls.append(params)
        return _FakeResponse(json_data={"results": []})

    monkeypatch.setattr(jumpcloud_client.requests, "get", fake_get)

    jumpcloud_client.test_connection("jca_testkey")

    assert calls == [{"limit": 1, "skip": 0}]


def test_connection_raises_on_http_error(monkeypatch):
    monkeypatch.setattr(
        jumpcloud_client.requests,
        "get",
        lambda url, headers, params, timeout: _FakeResponse(status_code=401, text="unauthorized"),
    )

    try:
        jumpcloud_client.test_connection("jca_badkey")
        raise AssertionError("expected JumpCloudApiError")
    except jumpcloud_client.JumpCloudApiError:
        pass
