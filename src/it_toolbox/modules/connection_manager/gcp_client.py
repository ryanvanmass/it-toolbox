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
import dataclasses
from concurrent.futures import ThreadPoolExecutor
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

import requests
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from google.oauth2.credentials import Credentials

from it_toolbox.modules.connection_manager.models import (
    GcpIamBinding,
    GcpImageChoice,
    GcpInstanceSpec,
    GcpMachineType,
    GcpProject,
    GcpSubnetwork,
    GcsBucket,
    GcsEntry,
    Instance,
)

# (connect timeout, read timeout) — a real, hard requests-enforced deadline.
REQUEST_TIMEOUT_SEC = (10, 30)
# Downloads can legitimately take a while; only the connect phase is bounded
# tightly, the read timeout is generous rather than aborting a real transfer.
DOWNLOAD_TIMEOUT_SEC = (10, 300)

RESOURCE_MANAGER_BASE = "https://cloudresourcemanager.googleapis.com/v3"
COMPUTE_BASE = "https://compute.googleapis.com/compute/v1"
IAM_BASE = "https://iam.googleapis.com/v1"
STORAGE_BASE = "https://storage.googleapis.com/storage/v1"

# Windows password reset (see reset_windows_password): the metadata key the
# guest agent watches, the serial port it answers on, how long a request
# stays valid, and how long we wait for the answer.
WINDOWS_KEYS_METADATA_KEY = "windows-keys"
WINDOWS_PASSWORD_SERIAL_PORT = 4
WINDOWS_KEY_TTL = timedelta(minutes=5)
WINDOWS_PASSWORD_TIMEOUT_SEC = 180
WINDOWS_PASSWORD_POLL_INTERVAL_SEC = 3

# VM creation (see create_instance): how long to wait for the insert
# operation to finish, and how often to check on it.
CREATE_INSTANCE_TIMEOUT_SEC = 300
OPERATION_POLL_INTERVAL_SEC = 2

# The public images CreateGcpVmDialog offers, as (label, image project,
# image family). Families, not image names, so each always resolves to
# its newest build; resolve_public_images drops any family that doesn't
# resolve (retired, or not visible to this account) rather than offering
# something instances.insert would reject.
PUBLIC_IMAGE_FAMILIES = (
    ("Debian 13", "debian-cloud", "debian-13"),
    ("Debian 12", "debian-cloud", "debian-12"),
    ("Ubuntu 24.04 LTS", "ubuntu-os-cloud", "ubuntu-2404-lts-amd64"),
    ("Ubuntu 22.04 LTS", "ubuntu-os-cloud", "ubuntu-2204-lts"),
    ("AlmaLinux 10", "almalinux-cloud", "almalinux-10"),
    ("AlmaLinux 9", "almalinux-cloud", "almalinux-9"),
    ("Rocky Linux 9", "rocky-linux-cloud", "rocky-linux-9"),
    ("Red Hat Enterprise Linux 9", "rhel-cloud", "rhel-9"),
    ("Windows Server 2025 Datacenter", "windows-cloud", "windows-2025"),
    ("Windows Server 2022 Datacenter", "windows-cloud", "windows-2022"),
    ("Windows Server 2019 Datacenter", "windows-cloud", "windows-2019"),
)


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


def _get_role_title(token: str, role: str) -> str:
    """A role's display title (e.g. "Compute Admin" for roles/compute.admin),
    or "" if it can't be read — custom org/project roles in particular need
    iam.roles.get, which a caller may not have.
    """
    try:
        return _get(f"{IAM_BASE}/{role}", token).get("title", "")
    except (GcpApiError, requests.RequestException):
        return ""


def resolve_role_titles(
    credentials: Credentials, bindings: list[GcpIamBinding]
) -> list[GcpIamBinding]:
    """Fill in role_title on each binding, one lookup per distinct role.
    Never raises: an unresolvable role just keeps an empty title.
    """
    roles = sorted({b.role for b in bindings})
    if not roles:
        return bindings
    with ThreadPoolExecutor(max_workers=8) as pool:
        titles = dict(zip(roles, pool.map(lambda r: _get_role_title(credentials.token, r), roles)))
    return [dataclasses.replace(b, role_title=titles[b.role]) for b in bindings]


def get_iam_policy(credentials: Credentials, project_id: str) -> list[GcpIamBinding]:
    """Who has access to a project and with which role(s) — Cloud Resource
    Manager's getIamPolicy is a POST (unlike every other read here) and
    returns bindings grouped by role, each with a list of members; flattened
    to one GcpIamBinding per member. No pagination on this endpoint.

    Deliberately no X-Goog-User-Project: that would bill the call to the
    inspected project and require the Resource Manager API to be enabled
    in every project looked at (403 SERVICE_DISABLED otherwise). Like
    list_projects, it's left to the caller's own quota project.
    """
    data = _post(
        f"{RESOURCE_MANAGER_BASE}/projects/{project_id}:getIamPolicy",
        credentials.token,
    )
    bindings = [
        GcpIamBinding(project_id=project_id, role=binding["role"], member=member)
        for binding in data.get("bindings", [])
        for member in binding.get("members", [])
    ]
    return sorted(bindings, key=lambda b: (b.role.lower(), b.member.lower()))


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


def _list_all(url: str, token: str, project_id: str, params: dict | None = None) -> list[dict]:
    """Every item of a paginated Compute Engine list call, billed to
    `project_id` (see list_instances for why)."""
    items: list[dict] = []
    page_token = None
    while True:
        page_params = dict(params or {})
        if page_token:
            page_params["pageToken"] = page_token
        data = _get(url, token, params=page_params, extra_headers={"X-Goog-User-Project": project_id})
        items.extend(data.get("items", []))
        page_token = data.get("nextPageToken")
        if not page_token:
            return items


def list_zones(credentials: Credentials, project_id: str) -> list[str]:
    """Short names of the zones this project can create VMs in."""
    zones = _list_all(f"{COMPUTE_BASE}/projects/{project_id}/zones", credentials.token, project_id)
    return sorted(z["name"] for z in zones if z.get("status", "UP") == "UP")


def _machine_type_sort_key(machine_type: GcpMachineType) -> tuple:
    # Group by series ("e2", "n2d", ...) and then smallest first, so the
    # list reads e2-micro, e2-small, e2-medium, ... rather than A-Z.
    return (machine_type.name.split("-", 1)[0], machine_type.guest_cpus, machine_type.memory_mb)


def list_machine_types(credentials: Credentials, project_id: str, zone: str) -> list[GcpMachineType]:
    items = _list_all(
        f"{COMPUTE_BASE}/projects/{project_id}/zones/{zone}/machineTypes", credentials.token, project_id
    )
    machine_types = [
        GcpMachineType(
            name=item["name"],
            guest_cpus=int(item.get("guestCpus", 0)),
            memory_mb=int(item.get("memoryMb", 0)),
        )
        for item in items
        if "deprecated" not in item
    ]
    return sorted(machine_types, key=_machine_type_sort_key)


def region_of_zone(zone: str) -> str:
    """"us-central1-a" -> "us-central1"."""
    return zone.rsplit("-", 1)[0]


def list_subnetworks(credentials: Credentials, project_id: str, region: str) -> list[GcpSubnetwork]:
    """The project's own subnets in `region` -- a VM's NIC has to land on
    one in its zone's region. (Shared-VPC subnets from a host project
    aren't listed here.)"""
    items = _list_all(
        f"{COMPUTE_BASE}/projects/{project_id}/regions/{region}/subnetworks",
        credentials.token,
        project_id,
    )
    subnetworks = [
        GcpSubnetwork(
            name=item["name"],
            network=item.get("network", "").rsplit("/", 1)[-1],
            region=region,
            ip_cidr_range=item.get("ipCidrRange", ""),
        )
        for item in items
    ]
    return sorted(subnetworks, key=lambda s: (s.network.lower(), s.name.lower()))


def _image_os_hint(image: dict) -> str:
    licenses = image.get("licenses", [])
    if any("windows" in lic.lower() for lic in licenses):
        return "windows"
    return "linux"


def _resolve_image_family(
    token: str, project_id: str, label: str, image_project: str, family: str
) -> GcpImageChoice | None:
    path = f"projects/{image_project}/global/images/family/{family}"
    try:
        image = _get(f"{COMPUTE_BASE}/{path}", token, extra_headers={"X-Goog-User-Project": project_id})
    except (GcpApiError, requests.RequestException):
        return None
    return GcpImageChoice(
        label=label,
        source_image=path,
        min_disk_gb=int(image.get("diskSizeGb", 10)),
        os_hint=_image_os_hint(image),
    )


def resolve_public_images(credentials: Credentials, project_id: str) -> list[GcpImageChoice]:
    """PUBLIC_IMAGE_FAMILIES that currently resolve, in that order, each
    with its real minimum disk size (Windows images need 50 GB, most Linux
    ones 10 or 20). Never raises: a family that fails to resolve is just
    left out."""
    with ThreadPoolExecutor(max_workers=8) as pool:
        resolved = pool.map(
            lambda entry: _resolve_image_family(credentials.token, project_id, *entry),
            PUBLIC_IMAGE_FAMILIES,
        )
        return [image for image in resolved if image is not None]


def list_project_images(credentials: Credentials, project_id: str) -> list[GcpImageChoice]:
    """The project's own (custom) images that aren't deprecated."""
    items = _list_all(
        f"{COMPUTE_BASE}/projects/{project_id}/global/images", credentials.token, project_id
    )
    images = [
        GcpImageChoice(
            label=item["name"],
            source_image=f"projects/{project_id}/global/images/{item['name']}",
            min_disk_gb=int(item.get("diskSizeGb", 10)),
            os_hint=_image_os_hint(item),
        )
        for item in items
        if "deprecated" not in item
    ]
    return sorted(images, key=lambda i: i.label.lower())


def _instance_body(spec: GcpInstanceSpec) -> dict:
    access_configs = (
        [{"type": "ONE_TO_ONE_NAT", "name": "External NAT"}] if spec.external_ip else []
    )
    return {
        "name": spec.name,
        "machineType": f"zones/{spec.zone}/machineTypes/{spec.machine_type}",
        "disks": [
            {
                "boot": True,
                "autoDelete": True,
                "initializeParams": {
                    "sourceImage": spec.source_image,
                    "diskSizeGb": str(spec.disk_size_gb),
                    "diskType": f"zones/{spec.zone}/diskTypes/{spec.disk_type}",
                },
            }
        ],
        "networkInterfaces": [
            {
                "subnetwork": (
                    f"projects/{spec.project_id}/regions/{spec.subnetwork.region}"
                    f"/subnetworks/{spec.subnetwork.name}"
                ),
                "accessConfigs": access_configs,
            }
        ],
    }


def _operation_error_message(operation: dict) -> str:
    errors = operation.get("error", {}).get("errors", [])
    messages = [e.get("message") or e.get("code", "") for e in errors]
    return "; ".join(m for m in messages if m) or operation.get("httpErrorMessage", "unknown error")


def create_instance(
    credentials: Credentials,
    spec: GcpInstanceSpec,
    timeout: float = CREATE_INSTANCE_TIMEOUT_SEC,
    poll_interval: float = OPERATION_POLL_INTERVAL_SEC,
    _sleep: Callable[[float], None] = time.sleep,
    _monotonic: Callable[[], float] = time.monotonic,
) -> None:
    """Creates and starts a VM (instances.insert) and waits for the insert
    operation to finish. Most real failures -- quota, an image that won't
    fit the disk, a disk type the machine series doesn't support -- only
    show up on the finished operation, not the insert call itself, so
    waiting is what lets the dialog show them. Blocking; call from a
    background thread.

    No service account is attached: that needs iam.serviceAccountUser on
    top of instance-create rights, and nothing this app does with the VM
    (IAP SSH/RDP, password reset, key upload) needs one.
    """
    headers = {"X-Goog-User-Project": spec.project_id}
    zone_url = f"{COMPUTE_BASE}/projects/{spec.project_id}/zones/{spec.zone}"
    operation = _post(
        f"{zone_url}/instances", credentials.token, json_body=_instance_body(spec), extra_headers=headers
    )
    deadline = _monotonic() + timeout
    while operation.get("status") != "DONE":
        if _monotonic() >= deadline:
            raise GcpApiError(
                f"{spec.name} is still being created after {int(timeout)} seconds. "
                "Refresh the project in a bit to see whether it finished."
            )
        _sleep(poll_interval)
        operation = _get(
            f"{zone_url}/operations/{operation['name']}", credentials.token, extra_headers=headers
        )
    if operation.get("error"):
        raise GcpApiError(f"Couldn't create {spec.name}: {_operation_error_message(operation)}")


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
