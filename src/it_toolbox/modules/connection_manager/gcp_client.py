from google.cloud import compute_v1, resourcemanager_v3
from google.oauth2.credentials import Credentials

from it_toolbox.core.timeout_utils import run_with_timeout
from it_toolbox.modules.connection_manager.models import GcpProject, Instance

# Bounds each underlying API call so an unresponsive/slow project can't hang
# the calling background thread (and, since the Qt thread pool has a limited
# number of workers, indefinitely block other pending expansions behind it).
# Passed to the client library's own timeout= AND hard-enforced via
# run_with_timeout(), since the library's internal retry/deadline policy
# doesn't always fully respect the former on its own.
REQUEST_TIMEOUT_SEC = 30.0


def list_projects(credentials: Credentials) -> list[GcpProject]:
    return run_with_timeout(lambda: _list_projects(credentials), REQUEST_TIMEOUT_SEC + 5)


def _list_projects(credentials: Credentials) -> list[GcpProject]:
    client = resourcemanager_v3.ProjectsClient(credentials=credentials)
    projects = client.search_projects(query="state:ACTIVE", timeout=REQUEST_TIMEOUT_SEC)
    return sorted(
        (GcpProject(project_id=p.project_id, display_name=p.display_name) for p in projects),
        key=lambda p: p.display_name.lower(),
    )


def list_instances(credentials: Credentials, project_id: str) -> list[Instance]:
    return run_with_timeout(
        lambda: _list_instances(credentials, project_id), REQUEST_TIMEOUT_SEC + 5
    )


def _list_instances(credentials: Credentials, project_id: str) -> list[Instance]:
    # Attribute quota/billing to the project actually being queried, not
    # whatever project the OAuth client happens to live in — that project
    # already runs Compute Engine (and so already has billing enabled),
    # while the OAuth-client project may have neither and shouldn't need to.
    client = compute_v1.InstancesClient(credentials=credentials.with_quota_project(project_id))
    request = compute_v1.AggregatedListInstancesRequest(project=project_id)

    instances: list[Instance] = []
    for zone_path, scoped_list in client.aggregated_list(request=request, timeout=REQUEST_TIMEOUT_SEC):
        if not scoped_list.instances:
            continue
        zone = zone_path.rsplit("/", 1)[-1]
        for instance in scoped_list.instances:
            network_interface = (
                instance.network_interfaces[0].name if instance.network_interfaces else "nic0"
            )
            instances.append(
                Instance(
                    name=instance.name,
                    zone=zone,
                    project_id=project_id,
                    status=instance.status,
                    network_interface=network_interface,
                )
            )

    return sorted(instances, key=lambda i: i.name.lower())
