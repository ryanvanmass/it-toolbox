"""GCP project/instance discovery via plain REST calls.

Deliberately not using the google-cloud-compute / google-cloud-resource-manager
client libraries here — both are gRPC-based, and in testing against a large
GCP org (500+ projects) calls would hang well past any timeout= passed to
them and leave orphaned native threads behind, eventually crashing the app
with no Python traceback (consistent with a native crash inside gRPC's C
core, not a bug in this app's own code). Plain requests-based REST calls
have simple, reliable timeouts and no native call threading of their own.
"""

import base64
import json
import time
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

import requests
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from google.oauth2.credentials import Credentials

from it_toolbox.modules.connection_manager.models import GcpProject, GcsBucket, GcsEntry, Instance

# (connect timeout, read timeout) — a real, hard requests-enforced deadline.
REQUEST_TIMEOUT_SEC = (10, 30)
# Downloads can legitimately take a while; only the connect phase is bounded
# tightly, the read timeout is generous rather than aborting a real transfer.
DOWNLOAD_TIMEOUT_SEC = (10, 300)

RESOURCE_MANAGER_BASE = "https://cloudresourcemanager.googleapis.com/v3"
COMPUTE_BASE = "https://compute.googleapis.com/compute/v1"
STORAGE_BASE = "https://storage.googleapis.com/storage/v1"

# Windows password reset (see reset_windows_password): the metadata key the
# guest agent watches, the serial port it answers on, how long a request
# stays valid, and how long we wait for the answer.
WINDOWS_KEYS_METADATA_KEY = "windows-keys"
WINDOWS_PASSWORD_SERIAL_PORT = 4
WINDOWS_KEY_TTL = timedelta(minutes=5)
WINDOWS_PASSWORD_TIMEOUT_SEC = 180
WINDOWS_PASSWORD_POLL_INTERVAL_SEC = 3


class GcpApiError(Exception):
    pass


def _get(url: str, token: str, params: dict | None = None, extra_headers: dict | None = None) -> dict:
    headers = {"Authorization": f"Bearer {token}"}
    if extra_headers:
        headers.update(extra_headers)
    response = requests.get(url, headers=headers, params=params, timeout=REQUEST_TIMEOUT_SEC)
    if response.status_code >= 400:
        raise GcpApiError(f"{response.status_code} {url}: {response.text[:500]}")
    return response.json()


def _post(
    url: str,
    token: str,
    params: dict | None = None,
    json_body: dict | None = None,
    extra_headers: dict | None = None,
) -> dict:
    headers = {"Authorization": f"Bearer {token}"}
    if extra_headers:
        headers.update(extra_headers)
    response = requests.post(
        url, headers=headers, params=params, json=json_body, timeout=REQUEST_TIMEOUT_SEC
    )
    if response.status_code >= 400:
        raise GcpApiError(f"{response.status_code} {url}: {response.text[:500]}")
    return response.json()


def list_projects(credentials: Credentials) -> list[GcpProject]:
    projects: list[GcpProject] = []
    page_token = None
    while True:
        params = {"query": "state:ACTIVE"}
        if page_token:
            params["pageToken"] = page_token
        data = _get(f"{RESOURCE_MANAGER_BASE}/projects:search", credentials.token, params=params)
        for p in data.get("projects", []):
            projects.append(
                GcpProject(
                    project_id=p["projectId"], display_name=p.get("displayName", p["projectId"])
                )
            )
        page_token = data.get("nextPageToken")
        if not page_token:
            break

    return sorted(projects, key=lambda p: p.display_name.lower())


def _os_hint_from_disks(disks: list[dict]) -> str | None:
    """Best-effort Windows-vs-Linux guess from the boot disk's license URLs
    (e.g. ".../licenses/windows-server-2022-dc") -- the Compute Engine API
    has no plain "OS" field on an instance, but every real image carries
    at least one license entry, and Windows images are unambiguous by
    name. None means inconclusive (no boot disk found, or no license
    entries at all) -- callers fall back to a user-configured default in
    that case rather than guessing further.
    """
    boot_disk = next((d for d in disks if d.get("boot")), None)
    if boot_disk is None:
        return None
    licenses = boot_disk.get("licenses", [])
    if any("windows" in lic.lower() for lic in licenses):
        return "windows"
    return "linux" if licenses else None


def list_instances(credentials: Credentials, project_id: str) -> list[Instance]:
    instances: list[Instance] = []
    page_token = None
    while True:
        params = {}
        if page_token:
            params["pageToken"] = page_token
        # X-Goog-User-Project attributes quota/billing to the project being
        # queried, not whatever project the OAuth token happens to be minted
        # against — that project already runs Compute Engine (and so already
        # has billing enabled) if it has any instances to list.
        data = _get(
            f"{COMPUTE_BASE}/projects/{project_id}/aggregated/instances",
            credentials.token,
            params=params,
            extra_headers={"X-Goog-User-Project": project_id},
        )
        for zone_path, scoped in data.get("items", {}).items():
            zone = zone_path.rsplit("/", 1)[-1]
            for instance in scoped.get("instances", []):
                network_interfaces = instance.get("networkInterfaces", [])
                network_interface = network_interfaces[0]["name"] if network_interfaces else "nic0"
                instances.append(
                    Instance(
                        name=instance["name"],
                        zone=zone,
                        project_id=project_id,
                        status=instance.get("status", "UNKNOWN"),
                        network_interface=network_interface,
                        os_hint=_os_hint_from_disks(instance.get("disks", [])),
                    )
                )
        page_token = data.get("nextPageToken")
        if not page_token:
            break

    return sorted(instances, key=lambda i: i.name.lower())


def start_instance(credentials: Credentials, project_id: str, zone: str, name: str) -> None:
    _post(
        f"{COMPUTE_BASE}/projects/{project_id}/zones/{zone}/instances/{name}/start",
        credentials.token,
        extra_headers={"X-Goog-User-Project": project_id},
    )


def stop_instance(
    credentials: Credentials, project_id: str, zone: str, name: str, force: bool = False
) -> None:
    """Stops the instance. By default this is a graceful stop — Compute
    Engine sends the guest OS an ACPI shutdown signal and gives it up to
    ~120s to shut down cleanly before forcing it off regardless. `force`
    sets `noGracefulShutdown`, skipping that guest shutdown attempt
    entirely and cutting power immediately (same risk as pulling the plug
    on a physical machine — unflushed disk writes can be lost).
    """
    params = {"noGracefulShutdown": "true"} if force else None
    _post(
        f"{COMPUTE_BASE}/projects/{project_id}/zones/{zone}/instances/{name}/stop",
        credentials.token,
        params=params,
        extra_headers={"X-Goog-User-Project": project_id},
    )


def _b64_int(value: int) -> str:
    """Big-endian, no leading zero bytes, base64 — the encoding the Windows
    guest agent expects for an RSA key's modulus and exponent."""
    return base64.b64encode(value.to_bytes((value.bit_length() + 7) // 8, "big")).decode()


def _live_windows_key_lines(existing_value: str, now: datetime) -> list[str]:
    """The lines of an existing `windows-keys` metadata value worth keeping:
    everything still unexpired, plus anything we can't parse (not ours to
    delete). Each line is one JSON request, and other people's pending
    requests share this key, so it has to be merged into, not replaced."""
    kept = []
    for line in existing_value.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            expire_on = datetime.fromisoformat(json.loads(line)["expireOn"])
        except (ValueError, KeyError, TypeError):
            kept.append(line)
            continue
        if expire_on > now:
            kept.append(line)
    return kept


def _wait_for_windows_password(
    credentials: Credentials,
    project_id: str,
    zone: str,
    name: str,
    modulus: str,
    timeout: float,
    poll_interval: float,
    sleep: Callable[[float], None],
    monotonic: Callable[[], float],
) -> dict:
    """Polls the instance's serial port 4 — where the guest agent prints one
    JSON line per password request — until the line answering *our* request
    (matched by the modulus we sent) appears. Returns that line's dict."""
    url = f"{COMPUTE_BASE}/projects/{project_id}/zones/{zone}/instances/{name}/serialPort"
    deadline = monotonic() + timeout
    start = 0
    pending = ""  # an unfinished last line, completed by the next chunk
    while True:
        data = _get(
            url,
            credentials.token,
            params={"port": WINDOWS_PASSWORD_SERIAL_PORT, "start": start},
            extra_headers={"X-Goog-User-Project": project_id},
        )
        start = int(data.get("next", start))
        pending += data.get("contents", "")
        *complete_lines, pending_tail = pending.split("\n")
        # The tail is normally an unfinished line, but if it already parses
        # as a whole JSON object there's no reason to wait for its newline.
        candidates = complete_lines + [pending_tail]
        pending = pending_tail
        for index, line in enumerate(candidates):
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            if not isinstance(entry, dict) or entry.get("modulus") != modulus:
                continue
            if index == len(candidates) - 1:
                pending = ""  # the tail turned out to be a whole line
            if entry.get("errorMessage"):
                raise GcpApiError(
                    f"{name}'s guest agent couldn't reset the password: {entry['errorMessage']}"
                )
            if entry.get("encryptedPassword"):
                return entry
        if monotonic() >= deadline:
            raise GcpApiError(
                f"{name} didn't answer within {int(timeout)} seconds. Resetting a Windows "
                "password needs the Google guest agent running inside the VM; check that it "
                "is installed and the VM has finished booting, then try again."
            )
        sleep(poll_interval)


def reset_windows_password(
    credentials: Credentials,
    project_id: str,
    zone: str,
    name: str,
    username: str,
    timeout: float = WINDOWS_PASSWORD_TIMEOUT_SEC,
    poll_interval: float = WINDOWS_PASSWORD_POLL_INTERVAL_SEC,
    _sleep: Callable[[float], None] = time.sleep,
    _monotonic: Callable[[], float] = time.monotonic,
) -> tuple[str, str]:
    """Creates (or resets) a local Windows account on the instance and
    returns its new (username, password) — the same flow `gcloud compute
    reset-windows-password` performs. There is no Compute Engine REST
    method for this (an earlier version POSTed to a non-existent
    `.../resetWindowsPassword` and got a 404); it is a handshake with the
    Google guest agent running inside the VM:

      1. Generate a throwaway RSA key pair.
      2. Add a `windows-keys` metadata entry — the account name, the public
         key, and a 5-minute expiry — via setMetadata.
      3. The guest agent creates/resets the account, encrypts the new
         password with that public key and prints it on serial port 4.
      4. Read it back with getSerialPortOutput and decrypt it (RSA-OAEP,
         SHA-1) with the private key, which never leaves this process.

    Blocking (it waits for the agent) — call from a background thread. Only
    meaningful for a running Windows instance with the guest environment
    installed; otherwise raises GcpApiError.
    """
    headers = {"X-Goog-User-Project": project_id}
    instance_url = f"{COMPUTE_BASE}/projects/{project_id}/zones/{zone}/instances/{name}"

    instance = _get(instance_url, credentials.token, extra_headers=headers)
    status = instance.get("status")
    if status != "RUNNING":
        raise GcpApiError(
            f"{name} is {status or 'not running'}. Start it first: the password is set by "
            "an agent inside the running VM."
        )

    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    numbers = private_key.public_key().public_numbers()
    modulus = _b64_int(numbers.n)
    now = datetime.now(timezone.utc)
    request = {
        "userName": username,
        "modulus": modulus,
        "exponent": _b64_int(numbers.e),
        "expireOn": (now + WINDOWS_KEY_TTL).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }

    metadata = instance.get("metadata", {})
    items = list(metadata.get("items", []))
    keys_item = next((item for item in items if item["key"] == WINDOWS_KEYS_METADATA_KEY), None)
    lines = _live_windows_key_lines(keys_item["value"] if keys_item else "", now)
    lines.append(json.dumps(request, separators=(",", ":")))
    new_value = "\n".join(lines)
    if keys_item is not None:
        keys_item["value"] = new_value
    else:
        items.append({"key": WINDOWS_KEYS_METADATA_KEY, "value": new_value})

    _post(
        f"{instance_url}/setMetadata",
        credentials.token,
        json_body={"fingerprint": metadata.get("fingerprint"), "items": items},
        extra_headers=headers,
    )

    answer = _wait_for_windows_password(
        credentials, project_id, zone, name, modulus, timeout, poll_interval, _sleep, _monotonic
    )
    password = private_key.decrypt(
        base64.b64decode(answer["encryptedPassword"]),
        padding.OAEP(mgf=padding.MGF1(hashes.SHA1()), algorithm=hashes.SHA1(), label=None),
    ).decode("utf-8")
    return answer.get("userName") or username, password


def add_ssh_key(
    credentials: Credentials,
    project_id: str,
    zone: str,
    name: str,
    username: str,
    public_key: str,
) -> None:
    """Grants SSH access to a Linux instance by appending an instance-
    metadata SSH key entry -- the mechanism Linux guest images actually
    use (password auth is disabled by default on GCP's images), the same
    one `gcloud compute ssh` sets up automatically on a first connection.
    Unlike reset_windows_password, this is a read-modify-write: setMetadata
    replaces the whole metadata payload, so existing items (including any
    other users' ssh-keys entries) must be preserved, and the current
    fingerprint must be echoed back so the update is rejected instead of
    silently clobbering a concurrent metadata change.
    """
    instance = _get(
        f"{COMPUTE_BASE}/projects/{project_id}/zones/{zone}/instances/{name}",
        credentials.token,
        extra_headers={"X-Goog-User-Project": project_id},
    )
    metadata = instance.get("metadata", {})
    items = list(metadata.get("items", []))
    ssh_keys_item = next((item for item in items if item["key"] == "ssh-keys"), None)
    existing_lines = ssh_keys_item["value"].splitlines() if ssh_keys_item else []
    new_line = f"{username}:{public_key}"
    if new_line not in existing_lines:
        existing_lines.append(new_line)
    new_value = "\n".join(existing_lines)

    if ssh_keys_item is not None:
        ssh_keys_item["value"] = new_value
    else:
        items.append({"key": "ssh-keys", "value": new_value})

    _post(
        f"{COMPUTE_BASE}/projects/{project_id}/zones/{zone}/instances/{name}/setMetadata",
        credentials.token,
        json_body={"fingerprint": metadata.get("fingerprint"), "items": items},
        extra_headers={"X-Goog-User-Project": project_id},
    )


def list_buckets(credentials: Credentials, project_id: str) -> list[GcsBucket]:
    buckets: list[GcsBucket] = []
    page_token = None
    while True:
        params = {"project": project_id}
        if page_token:
            params["pageToken"] = page_token
        data = _get(
            f"{STORAGE_BASE}/b",
            credentials.token,
            params=params,
            extra_headers={"X-Goog-User-Project": project_id},
        )
        for b in data.get("items", []):
            buckets.append(GcsBucket(name=b["name"], project_id=project_id))
        page_token = data.get("nextPageToken")
        if not page_token:
            break

    return sorted(buckets, key=lambda b: b.name.lower())


def list_objects(credentials: Credentials, bucket: GcsBucket, prefix: str = "") -> list[GcsEntry]:
    """One "directory level" of a bucket — folders (delimiter-based prefix
    grouping; GCS has no real directories) followed by objects, both sorted
    by name. `prefix` is the current folder path, e.g. "photos/2024/".
    """
    folders: list[GcsEntry] = []
    objects: list[GcsEntry] = []
    page_token = None
    while True:
        params = {"delimiter": "/", "userProject": bucket.project_id}
        if prefix:
            params["prefix"] = prefix
        if page_token:
            params["pageToken"] = page_token
        data = _get(
            f"{STORAGE_BASE}/b/{quote(bucket.name, safe='')}/o",
            credentials.token,
            params=params,
            extra_headers={"X-Goog-User-Project": bucket.project_id},
        )
        for folder_prefix in data.get("prefixes", []):
            name = folder_prefix[len(prefix) :].rstrip("/")
            folders.append(GcsEntry(name=name, full_path=folder_prefix, is_folder=True))
        for obj in data.get("items", []):
            full_path = obj["name"]
            if full_path == prefix:
                continue  # an explicit zero-byte "folder marker" object, not a real file
            objects.append(
                GcsEntry(
                    name=full_path[len(prefix) :],
                    full_path=full_path,
                    is_folder=False,
                    size=int(obj.get("size", 0)),
                    updated=obj.get("updated", ""),
                )
            )
        page_token = data.get("nextPageToken")
        if not page_token:
            break

    folders.sort(key=lambda e: e.name.lower())
    objects.sort(key=lambda e: e.name.lower())
    return folders + objects


def download_object(
    credentials: Credentials, bucket: GcsBucket, object_path: str, dest_path: str
) -> None:
    url = f"{STORAGE_BASE}/b/{quote(bucket.name, safe='')}/o/{quote(object_path, safe='')}"
    headers = {"Authorization": f"Bearer {credentials.token}"}
    params = {"alt": "media", "userProject": bucket.project_id}
    with requests.get(
        url, headers=headers, params=params, timeout=DOWNLOAD_TIMEOUT_SEC, stream=True
    ) as response:
        if response.status_code >= 400:
            raise GcpApiError(f"{response.status_code} {url}: {response.text[:500]}")
        with open(dest_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                f.write(chunk)
