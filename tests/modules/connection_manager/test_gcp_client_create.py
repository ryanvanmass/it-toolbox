import pytest

from it_toolbox.modules.connection_manager import gcp_client
from it_toolbox.modules.connection_manager.models import GcpInstanceSpec, GcpSubnetwork


class _FakeCredentials:
    token = "fake-token"


class _FakeResponse:
    def __init__(self, json_data=None, status_code=200, text=""):
        self._json = json_data
        self.status_code = status_code
        self.text = text

    def json(self):
        return self._json


def _spec(**overrides):
    values = dict(
        project_id="proj",
        name="web-1",
        zone="us-east1-b",
        machine_type="e2-medium",
        source_image="projects/debian-cloud/global/images/family/debian-12",
        disk_size_gb=20,
        disk_type="pd-balanced",
        subnetwork=GcpSubnetwork(name="default", network="default", region="us-east1"),
        external_ip=True,
    )
    values.update(overrides)
    return GcpInstanceSpec(**values)


def test_list_zones_follows_pages_and_skips_down_zones(monkeypatch):
    pages = [
        {"items": [{"name": "us-east1-c", "status": "UP"}, {"name": "us-east1-a"}], "nextPageToken": "t"},
        {"items": [{"name": "europe-west1-b", "status": "DOWN"}, {"name": "asia-east1-a", "status": "UP"}]},
    ]
    seen = []

    def fake_get(url, headers, params, timeout):
        seen.append((url, dict(params), headers["X-Goog-User-Project"]))
        return _FakeResponse(json_data=pages[len(seen) - 1])

    monkeypatch.setattr(gcp_client.requests, "get", fake_get)

    zones = gcp_client.list_zones(_FakeCredentials(), "proj")

    assert zones == ["asia-east1-a", "us-east1-a", "us-east1-c"]
    assert seen[0][0].endswith("/projects/proj/zones")
    assert seen[1][1] == {"pageToken": "t"}
    assert seen[0][2] == "proj"


def test_list_machine_types_drops_deprecated_and_sorts_by_series_then_size(monkeypatch):
    items = [
        {"name": "n2-standard-4", "guestCpus": 4, "memoryMb": 16384},
        {"name": "e2-medium", "guestCpus": 2, "memoryMb": 4096},
        {"name": "e2-micro", "guestCpus": 2, "memoryMb": 1024},
        {"name": "n1-standard-1", "guestCpus": 1, "memoryMb": 3840, "deprecated": {"state": "DEPRECATED"}},
    ]
    monkeypatch.setattr(gcp_client.requests, "get", lambda *a, **k: _FakeResponse(json_data={"items": items}))

    types = gcp_client.list_machine_types(_FakeCredentials(), "proj", "us-east1-b")

    assert [t.name for t in types] == ["e2-micro", "e2-medium", "n2-standard-4"]
    assert types[1].guest_cpus == 2 and types[1].memory_mb == 4096


def test_region_of_zone():
    assert gcp_client.region_of_zone("us-central1-a") == "us-central1"
    assert gcp_client.region_of_zone("europe-west4-c") == "europe-west4"


def test_list_subnetworks_reads_network_short_name(monkeypatch):
    items = [
        {
            "name": "default",
            "network": "https://www.googleapis.com/compute/v1/projects/proj/global/networks/default",
            "ipCidrRange": "10.142.0.0/20",
        }
    ]
    urls = []

    def fake_get(url, headers, params, timeout):
        urls.append(url)
        return _FakeResponse(json_data={"items": items})

    monkeypatch.setattr(gcp_client.requests, "get", fake_get)

    subnets = gcp_client.list_subnetworks(_FakeCredentials(), "proj", "us-east1")

    assert subnets == [
        GcpSubnetwork(name="default", network="default", region="us-east1", ip_cidr_range="10.142.0.0/20")
    ]
    assert urls[0].endswith("/projects/proj/regions/us-east1/subnetworks")


def test_resolve_public_images_keeps_order_drops_failures_and_reads_min_size(monkeypatch):
    monkeypatch.setattr(
        gcp_client,
        "PUBLIC_IMAGE_FAMILIES",
        (
            ("Debian 12", "debian-cloud", "debian-12"),
            ("Gone", "old-cloud", "retired"),
            ("Windows Server 2022", "windows-cloud", "windows-2022"),
        ),
    )

    def fake_get(url, headers, params, timeout):
        if "retired" in url:
            return _FakeResponse(status_code=404, text="not found")
        if "windows" in url:
            return _FakeResponse(
                json_data={"diskSizeGb": "50", "licenses": [".../licenses/windows-server-2022-dc"]}
            )
        return _FakeResponse(json_data={"diskSizeGb": "10", "licenses": [".../licenses/debian-12"]})

    monkeypatch.setattr(gcp_client.requests, "get", fake_get)

    images = gcp_client.resolve_public_images(_FakeCredentials(), "proj")

    assert [i.label for i in images] == ["Debian 12", "Windows Server 2022"]
    assert images[0].source_image == "projects/debian-cloud/global/images/family/debian-12"
    assert (images[0].min_disk_gb, images[0].os_hint) == (10, "linux")
    assert (images[1].min_disk_gb, images[1].os_hint) == (50, "windows")


def test_list_project_images_skips_deprecated(monkeypatch):
    items = [
        {"name": "golden-2", "diskSizeGb": "30"},
        {"name": "golden-1", "diskSizeGb": "30", "deprecated": {"state": "DEPRECATED"}},
    ]
    monkeypatch.setattr(gcp_client.requests, "get", lambda *a, **k: _FakeResponse(json_data={"items": items}))

    images = gcp_client.list_project_images(_FakeCredentials(), "proj")

    assert [(i.label, i.source_image, i.min_disk_gb) for i in images] == [
        ("golden-2", "projects/proj/global/images/golden-2", 30)
    ]


def test_create_instance_posts_the_spec_and_waits_for_the_operation(monkeypatch):
    posts = []
    gets = []
    statuses = iter(["RUNNING", "DONE"])

    def fake_post(url, headers, params, json, timeout):
        posts.append((url, headers, json))
        return _FakeResponse(json_data={"name": "op-1", "status": "PENDING"})

    def fake_get(url, headers, params, timeout):
        gets.append(url)
        return _FakeResponse(json_data={"name": "op-1", "status": next(statuses)})

    monkeypatch.setattr(gcp_client.requests, "post", fake_post)
    monkeypatch.setattr(gcp_client.requests, "get", fake_get)
    sleeps = []

    gcp_client.create_instance(_FakeCredentials(), _spec(), _sleep=sleeps.append, _monotonic=lambda: 0)

    url, headers, body = posts[0]
    assert url.endswith("/projects/proj/zones/us-east1-b/instances")
    assert headers["X-Goog-User-Project"] == "proj"
    assert body["name"] == "web-1"
    assert body["machineType"] == "zones/us-east1-b/machineTypes/e2-medium"
    (disk,) = body["disks"]
    assert disk["boot"] is True and disk["autoDelete"] is True
    assert disk["initializeParams"] == {
        "sourceImage": "projects/debian-cloud/global/images/family/debian-12",
        "diskSizeGb": "20",
        "diskType": "zones/us-east1-b/diskTypes/pd-balanced",
    }
    (nic,) = body["networkInterfaces"]
    assert nic["subnetwork"] == "projects/proj/regions/us-east1/subnetworks/default"
    assert nic["accessConfigs"] == [{"type": "ONE_TO_ONE_NAT", "name": "External NAT"}]
    assert "serviceAccounts" not in body
    assert gets == [gets[0]] * 2 and gets[0].endswith("/zones/us-east1-b/operations/op-1")
    assert len(sleeps) == 2


def test_create_instance_without_external_ip_has_no_access_config(monkeypatch):
    bodies = []

    def fake_post(url, headers, params, json, timeout):
        bodies.append(json)
        return _FakeResponse(json_data={"name": "op-1", "status": "DONE"})

    monkeypatch.setattr(gcp_client.requests, "post", fake_post)

    gcp_client.create_instance(_FakeCredentials(), _spec(external_ip=False))

    assert bodies[0]["networkInterfaces"][0]["accessConfigs"] == []


def test_create_instance_raises_the_operations_error(monkeypatch):
    operation = {
        "name": "op-1",
        "status": "DONE",
        "error": {"errors": [{"code": "QUOTA_EXCEEDED", "message": "Quota 'CPUS' exceeded."}]},
    }
    monkeypatch.setattr(gcp_client.requests, "post", lambda *a, **k: _FakeResponse(json_data=operation))

    with pytest.raises(gcp_client.GcpApiError, match="Couldn't create web-1: Quota 'CPUS' exceeded."):
        gcp_client.create_instance(_FakeCredentials(), _spec())


def test_create_instance_gives_up_after_the_timeout(monkeypatch):
    monkeypatch.setattr(
        gcp_client.requests, "post", lambda *a, **k: _FakeResponse(json_data={"name": "op-1", "status": "PENDING"})
    )
    monkeypatch.setattr(
        gcp_client.requests, "get", lambda *a, **k: _FakeResponse(json_data={"name": "op-1", "status": "RUNNING"})
    )
    clock = iter(range(0, 1000, 100))

    with pytest.raises(gcp_client.GcpApiError, match="still being created"):
        gcp_client.create_instance(
            _FakeCredentials(), _spec(), timeout=250, _sleep=lambda _: None, _monotonic=lambda: next(clock)
        )


def test_create_instance_surfaces_a_rejected_insert(monkeypatch):
    monkeypatch.setattr(
        gcp_client.requests,
        "post",
        lambda *a, **k: _FakeResponse(status_code=409, text="The resource 'web-1' already exists"),
    )

    with pytest.raises(gcp_client.GcpApiError, match="already exists"):
        gcp_client.create_instance(_FakeCredentials(), _spec())
