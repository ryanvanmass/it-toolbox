"""JumpCloud device/user discovery via plain REST calls.

Mirrors connection_manager/gcp_client.py's shape: a flat exception class,
a module-level timeout tuple, a private _get() every real endpoint
function goes through, and the API key threaded as a plain first argument
rather than held on a client instance.

Exact JSON field names and the limit/skip pagination convention below are
best-effort from JumpCloud's public docs, not verified against a live org
or a real API key — see the "_device_from_*"/"_user_from_json" mapping
functions, which exist specifically so a later field-name correction stays
isolated here rather than rippling into models.py or the UI.
"""

import requests

from it_toolbox.modules.identity_management.models import Device, User

REQUEST_TIMEOUT_SEC = (10, 30)

API_BASE_V1 = "https://console.jumpcloud.com/api"

# JumpCloud v1 list endpoints page via limit/skip and stop once a page
# comes back shorter than requested — unverified against live docs, but
# matches the documented pattern for this API generation.
LIST_PAGE_LIMIT = 100


class JumpCloudApiError(Exception):
    pass


def _get(url: str, api_key: str, params: dict | None = None) -> dict:
    headers = {"x-api-key": api_key, "Accept": "application/json"}
    response = requests.get(url, headers=headers, params=params, timeout=REQUEST_TIMEOUT_SEC)
    if response.status_code >= 400:
        raise JumpCloudApiError(f"{response.status_code} {url}: {response.text[:500]}")
    return response.json()


def _device_from_list_json(data: dict) -> Device:
    return Device(
        id=data["id"],
        display_name=data.get("displayName") or data.get("hostname", data["id"]),
        os=data.get("os", ""),
        hostname=data.get("hostname", ""),
        last_contact=data.get("lastContact", ""),
        active=data.get("active", True),
    )


def _device_from_detail_json(data: dict) -> Device:
    return Device(
        id=data["id"],
        display_name=data.get("displayName") or data.get("hostname", data["id"]),
        os=data.get("os", ""),
        hostname=data.get("hostname", ""),
        os_version=data.get("version", ""),
        serial_number=data.get("serialNumber", ""),
        agent_version=data.get("agentVersion", ""),
        last_contact=data.get("lastContact", ""),
        active=data.get("active", True),
    )


def _user_from_json(data: dict) -> User:
    return User(
        id=data["id"],
        username=data.get("username", data["id"]),
        email=data.get("email", ""),
        first_name=data.get("firstname", ""),
        last_name=data.get("lastname", ""),
        suspended=data.get("suspended", False),
    )


def list_devices(api_key: str) -> list[Device]:
    devices: list[Device] = []
    skip = 0
    while True:
        data = _get(
            f"{API_BASE_V1}/systems", api_key, params={"limit": LIST_PAGE_LIMIT, "skip": skip}
        )
        results = data.get("results", [])
        devices.extend(_device_from_list_json(d) for d in results)
        if len(results) < LIST_PAGE_LIMIT:
            break
        skip += LIST_PAGE_LIMIT

    return sorted(devices, key=lambda d: d.display_name.lower())


def get_device(api_key: str, device_id: str) -> Device:
    data = _get(f"{API_BASE_V1}/systems/{device_id}", api_key)
    return _device_from_detail_json(data)


def list_users(api_key: str) -> list[User]:
    users: list[User] = []
    skip = 0
    while True:
        data = _get(
            f"{API_BASE_V1}/systemusers", api_key, params={"limit": LIST_PAGE_LIMIT, "skip": skip}
        )
        results = data.get("results", [])
        users.extend(_user_from_json(u) for u in results)
        if len(results) < LIST_PAGE_LIMIT:
            break
        skip += LIST_PAGE_LIMIT

    return sorted(users, key=lambda u: u.username.lower())


def test_connection(api_key: str) -> None:
    """Minimal call to validate a key/connectivity without paginating a
    potentially large org's full device list — raises JumpCloudApiError on
    failure, returns nothing on success.
    """
    _get(f"{API_BASE_V1}/systems", api_key, params={"limit": 1, "skip": 0})


def remote_assist_url(device_id: str) -> str:
    """Deep link to this device's JumpCloud Admin Portal page, where the
    user clicks "Launch Remote Assist" themselves — there is no documented
    public API to start a Remote Assist session programmatically (it's a
    WebRTC session negotiated through JumpCloud's own console, with no
    published SDK/API for third parties). Exact URL shape unverified
    against a live org.
    """
    return f"https://console.jumpcloud.com/devices/{device_id}"
