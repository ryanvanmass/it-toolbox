from google.cloud import compute_v1, resourcemanager_v3
from google.oauth2.credentials import Credentials

from it_toolbox.modules.connection_manager.models import GcpProject, Instance


def list_projects(credentials: Credentials) -> list[GcpProject]:
    client = resourcemanager_v3.ProjectsClient(credentials=credentials)
    projects = client.search_projects(query="state:ACTIVE")
    return sorted(
        (GcpProject(project_id=p.project_id, display_name=p.display_name) for p in projects),
        key=lambda p: p.display_name.lower(),
    )


def list_instances(credentials: Credentials, project_id: str) -> list[Instance]:
    client = compute_v1.InstancesClient(credentials=credentials)
    request = compute_v1.AggregatedListInstancesRequest(project=project_id)

    instances: list[Instance] = []
    for zone_path, scoped_list in client.aggregated_list(request=request):
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
