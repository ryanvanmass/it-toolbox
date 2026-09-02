"""GCP project/instance discovery via plain REST calls.

Deliberately not using the google-cloud-compute / google-cloud-resource-manager
client libraries here — both are gRPC-based, and in testing against a large
GCP org (500+ projects) calls would hang well past any timeout= passed to
them and leave orphaned native threads behind, eventually crashing the app
with no Python traceback (consistent with a native crash inside gRPC's C
core, not a bug in this app's own code). Plain requests-based REST calls
have simple, reliable timeouts and no native call threading of their own.
"""

import requests
from google.oauth2.credentials import Credentials

from it_toolbox.modules.connection_manager.models import GcpProject, Instance

# (connect timeout, read timeout) — a real, hard requests-enforced deadline.
REQUEST_TIMEOUT_SEC = (10, 30)

RESOURCE_MANAGER_BASE = "https://cloudresourcemanager.googleapis.com/v3"
COMPUTE_BASE = "https://compute.googleapis.com/compute/v1"


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
