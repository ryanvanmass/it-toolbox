"""GCP project/instance discovery via plain REST calls.

Deliberately not using the google-cloud-compute / google-cloud-resource-manager
client libraries here — both are gRPC-based, and in testing against a large
GCP org (500+ projects) calls would hang well past any timeout= passed to
them and leave orphaned native threads behind, eventually crashing the app
with no Python traceback (consistent with a native crash inside gRPC's C
core, not a bug in this app's own code). Plain requests-based REST calls
have simple, reliable timeouts and no native call threading of their own.
"""

from urllib.parse import quote

import requests
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
    url: str, token: str, json_body: dict | None = None, extra_headers: dict | None = None
) -> dict:
    headers = {"Authorization": f"Bearer {token}"}
    if extra_headers:
        headers.update(extra_headers)
    response = requests.post(url, headers=headers, json=json_body, timeout=REQUEST_TIMEOUT_SEC)
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


def stop_instance(credentials: Credentials, project_id: str, zone: str, name: str) -> None:
    _post(
        f"{COMPUTE_BASE}/projects/{project_id}/zones/{zone}/instances/{name}/stop",
        credentials.token,
        extra_headers={"X-Goog-User-Project": project_id},
    )


def reset_windows_password(
    credentials: Credentials,
    project_id: str,
    zone: str,
    name: str,
    username: str = "Administrator",
) -> tuple[str, str]:
    """Creates (or resets) a local Windows account on the instance and
    returns its new (username, password) — same operation `gcloud compute
    reset-windows-password` performs. Unlike start/stop this call responds
    with the credential directly rather than a long-running Operation.
    Only meaningful for Windows instances; the API rejects it otherwise.
    """
    data = _post(
        f"{COMPUTE_BASE}/projects/{project_id}/zones/{zone}/instances/{name}/resetWindowsPassword",
        credentials.token,
        json_body={"email": username},
        extra_headers={"X-Goog-User-Project": project_id},
    )
    return data["userName"], data["password"]


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
