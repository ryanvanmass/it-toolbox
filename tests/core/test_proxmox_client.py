import pytest
import requests

from it_toolbox.core import pinned_tls
from it_toolbox.core import proxmox_client as pc
from it_toolbox.core.infrastructure_hosts import InfrastructureHost
from it_toolbox.core.proxmox_models import LXC, QEMU, ProxmoxGuest

HOST = InfrastructureHost(name="pve1", url="https://pve1.lan:8006", token_id="root@pam!tb", fingerprint="AA")

RESOURCES = [
    {"type": "node", "node": "pve1", "status": "online", "cpu": 0.05, "maxcpu": 8, "mem": 2 << 30,
     "maxmem": 16 << 30, "uptime": 3600, "id": "node/pve1"},
    {"type": "qemu", "vmid": 101, "name": "web", "node": "pve1", "status": "stopped", "maxmem": 2 << 30,
     "maxcpu": 2, "template": 0, "tags": "prod;web"},
    {"type": "qemu", "vmid": 100, "name": "dc01", "node": "pve1", "status": "running", "cpu": 0.1, "maxcpu": 4},
    {"type": "lxc", "vmid": 200, "name": "pihole", "node": "pve1", "status": "running"},
    {"type": "qemu", "vmid": 9000, "name": "alma10-tmpl", "node": "pve1", "status": "stopped", "template": 1},
    {"type": "storage", "storage": "local", "node": "pve1", "plugintype": "dir", "status": "available",
     "disk": 10 << 30, "maxdisk": 100 << 30, "content": "iso,vztmpl,backup", "shared": 0},
    {"type": "sdn", "sdn": "lab", "node": "pve1", "status": "ok"},
]


class FakeResponse:
    def __init__(self, status=200, data=None, reason="OK", body=None):
        self.status_code = status
        self.reason = reason
        self._body = {"data": data} if body is None else body

    def json(self):
        if isinstance(self._body, Exception):
            raise self._body
        return self._body


class FakeSession:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def request(self, method, url, headers=None, timeout=None, params=None, **kwargs):
        self.calls.append((method, url, headers, params))
        result = self.responses(method, url, params)
        if isinstance(result, Exception):
            raise result
        return result


@pytest.fixture
def api(monkeypatch):
    """Routes requests by path (after /api2/json) to `routes`."""
    routes = {}
    sessions = []

    def respond(method, url, params):
        path = url.split("/api2/json", 1)[1]
        value = routes.get(path)
        if callable(value):
            return value(params)
        if isinstance(value, (FakeResponse, Exception)):
            return value
        if value is None:
            return FakeResponse(501, reason=f"Method '{path}' not implemented")
        return FakeResponse(data=value)

    def make_session(url, verify_ssl, fingerprint):
        session = FakeSession(respond)
        sessions.append(session)
        return session

    monkeypatch.setattr(pc.pinned_tls, "make_session", make_session)
    routes["_sessions"] = sessions
    return routes


def test_requests_carry_the_token_header(api):
    api["/version"] = {"version": "9.0.3"}
    assert pc.get_version(HOST, "s3cret") == {"version": "9.0.3"}
    method, url, headers, _ = api["_sessions"][0].calls[0]
    assert url == "https://pve1.lan:8006/api2/json/version"
    assert headers == {"Authorization": "PVEAPIToken=root@pam!tb=s3cret"}


def test_resources_split_into_nodes_guests_storage_and_sdn(api):
    api["/cluster/resources"] = RESOURCES
    resources = pc.list_resources(HOST, "s")
    assert [n.name for n in resources.nodes] == ["pve1"]
    assert [g.vmid for g in resources.guests] == [100, 101, 200, 9000]
    web = resources.guests[1]
    assert web.tags == ("prod", "web") and web.type == QEMU and not web.template
    assert resources.guests[2].type == LXC and resources.guests[2].label == "200 pihole (CT)"
    assert resources.guests[3].template
    assert resources.storages[0].content == ("iso", "vztmpl", "backup")
    assert resources.sdn_zones == ("lab",)


def test_401_says_the_token_was_rejected(api):
    api["/version"] = FakeResponse(401, reason="authentication failure")
    with pytest.raises(pc.ProxmoxApiError, match="rejected the API token") as error:
        pc.get_version(HOST, "s")
    assert error.value.status == 401


def test_403_keeps_proxmox_s_permission_reason(api):
    api["/cluster/resources"] = FakeResponse(403, reason="Permission check failed (/, Sys.Audit)")
    with pytest.raises(pc.ProxmoxApiError, match=r"Permission check failed \(/, Sys.Audit\)"):
        pc.list_resources(HOST, "s")


def test_400_lists_field_errors(api):
    api["/version"] = FakeResponse(400, reason="Parameter verification failed.",
                                   body={"data": None, "errors": {"vmid": "invalid format"}})
    with pytest.raises(pc.ProxmoxApiError, match="vmid: invalid format"):
        pc.get_version(HOST, "s")


def test_connection_errors_become_api_errors(api):
    api["/version"] = requests.exceptions.ConnectionError("boom")
    with pytest.raises(pc.ProxmoxApiError, match="Couldn't connect to https://pve1.lan:8006"):
        pc.get_version(HOST, "s")


def test_tls_error_on_a_pinned_host_reports_a_changed_certificate(api, monkeypatch):
    api["/version"] = requests.exceptions.SSLError("fingerprints did not match")

    def mismatch(url, fingerprint):
        raise pinned_tls.CertificateMismatchError(url, fingerprint, "BB")

    monkeypatch.setattr(pc.pinned_tls, "check_pinned", mismatch)
    with pytest.raises(pc.ProxmoxApiError, match="has changed"):
        pc.get_version(HOST, "s")


def test_non_json_response_is_explained(api):
    api["/version"] = FakeResponse(body=ValueError("not json"))
    with pytest.raises(pc.ProxmoxApiError, match="Proxmox VE host"):
        pc.get_version(HOST, "s")


def test_unpinned_unverified_host_is_refused_before_connecting():
    host = HOST.with_changes(fingerprint=None)
    with pytest.raises(pc.ProxmoxApiError, match="No pinned certificate"):
        pc.get_version(host, "s")


def test_test_connection_summarises_version_nodes_and_permissions(api):
    api["/version"] = {"version": "9.0.3"}
    api["/nodes"] = [{"node": "pve1"}]
    api["/access/permissions"] = {"/": {"VM.Audit": 1, "Sys.Audit": 1}, "/vms": {"VM.PowerMgmt": 1}}
    assert pc.test_connection(HOST, "s") == "Proxmox VE 9.0.3, node pve1 — can manage VMs"


def test_test_connection_warns_about_older_versions(api):
    api["/version"] = {"version": "8.4.1"}
    api["/nodes"] = [{"node": "a"}, {"node": "b"}]
    api["/access/permissions"] = {"/": {"Sys.Audit": 1}}
    summary = pc.test_connection(HOST, "s")
    assert summary.startswith("Proxmox VE 8.4.1, nodes a, b — read-only token")
    assert "targets PVE 9" in summary


@pytest.mark.parametrize(
    "permissions, expected",
    [
        ({}, "this token can't see any VMs (give it PVEAuditor or PVEVMAdmin on /)"),
        ({"/": {"VM.Audit": 1}}, "read-only token"),
        ({"/": {"VM.Audit": 1, "VM.PowerMgmt": 1}, "/sdn": {"SDN.Allocate": 1}}, "can manage VMs, can edit SDN"),
        ({"/vms/100": {"VM.PowerMgmt": 1}, "/": {"VM.Audit": 1}}, "read-only token"),
    ],
)
def test_describe_permissions(permissions, expected):
    assert pc.describe_permissions(permissions) == expected


def test_node_status_parses_the_dashboard_fields(api):
    api["/nodes/pve1/status"] = {
        "pveversion": "pve-manager/9.0.3/abc", "current-kernel": {"release": "6.14.8-2-pve"},
        "cpuinfo": {"model": "Xeon", "cpus": 8}, "cpu": 0.12, "loadavg": ["0.10", "0.20", "0.30"],
        "memory": {"used": 1, "total": 2}, "swap": {"used": 0, "total": 0},
        "rootfs": {"used": 3, "total": 4}, "uptime": 99,
    }
    status = pc.get_node_status(HOST, "s", "pve1")
    assert status.pve_version == "pve-manager/9.0.3/abc"
    assert status.kernel == "6.14.8-2-pve" and status.cpus == 8
    assert status.loadavg == ("0.10", "0.20", "0.30") and status.rootfs_total == 4


def _vm(**kwargs):
    return ProxmoxGuest(vmid=100, name="dc01", node="pve1", type=QEMU, status="running", **kwargs)


def test_guest_details_read_ips_from_a_running_agent(api):
    api["/nodes/pve1/qemu/100/config"] = {"agent": "1,fstrim_cloned_disks=1", "net0": "virtio=AA,bridge=vmbr0"}
    api["/nodes/pve1/qemu/100/status/current"] = {"status": "running", "agent": 1, "uptime": 50, "name": "dc01"}
    api["/nodes/pve1/qemu/100/agent/network-get-interfaces"] = {"result": [
        {"name": "lo", "ip-addresses": [{"ip-address": "127.0.0.1", "prefix": 8}]},
        {"name": "eth0", "hardware-address": "aa:bb", "ip-addresses": [
            {"ip-address": "10.0.0.5", "prefix": 24}, {"ip-address": "fe80::1", "prefix": 64}]},
    ]}
    details = pc.get_guest_details(HOST, "s", _vm())
    assert details.agent_running is True
    assert details.ipv4_addresses == ("10.0.0.5",)
    assert details.interfaces[1].addresses == ("10.0.0.5/24", "fe80::1/64")
    assert details.guest.uptime == 50


def test_guest_without_an_agent_configured_reports_none(api):
    api["/nodes/pve1/qemu/100/config"] = {}
    api["/nodes/pve1/qemu/100/status/current"] = {"status": "running"}
    details = pc.get_guest_details(HOST, "s", _vm())
    assert details.agent_running is None and details.interfaces == ()


def test_agent_errors_mark_the_agent_not_running(api):
    api["/nodes/pve1/qemu/100/config"] = {"agent": "1"}
    api["/nodes/pve1/qemu/100/status/current"] = {"status": "running", "agent": 1}
    api["/nodes/pve1/qemu/100/agent/network-get-interfaces"] = FakeResponse(500, reason="QEMU guest agent is not running")
    details = pc.get_guest_details(HOST, "s", _vm())
    assert details.agent_running is False
    assert "not running" in details.interfaces_error


def test_container_interfaces(api):
    ct = ProxmoxGuest(vmid=200, name="pihole", node="pve1", type=LXC, status="running")
    api["/nodes/pve1/lxc/200/config"] = {"net0": "name=eth0,bridge=vnet10"}
    api["/nodes/pve1/lxc/200/status/current"] = {"status": "running"}
    api["/nodes/pve1/lxc/200/interfaces"] = [
        {"name": "lo", "hwaddr": "00:00", "inet": "127.0.0.1/8"},
        {"name": "eth0", "hwaddr": "bc:24", "inet": "10.10.0.2/24", "inet6": "fe80::2/64"},
    ]
    details = pc.get_guest_details(HOST, "s", ct)
    assert details.agent_running is None
    assert details.ipv4_addresses == ("10.10.0.2",)


def test_tasks_are_newest_first(api):
    api["/cluster/tasks"] = [
        {"upid": "U1", "node": "pve1", "type": "qmstart", "id": "100", "user": "root@pam", "starttime": 10,
         "endtime": 12, "status": "OK"},
        {"upid": "U2", "node": "pve1", "type": "vzdump", "id": "", "user": "root@pam", "starttime": 20},
    ]
    tasks = pc.list_tasks(HOST, "s")
    assert [t.upid for t in tasks] == ["U2", "U1"]
    assert tasks[0].running and tasks[1].ok


def test_task_log_lines(api):
    api["/nodes/pve1/tasks/UPID%3Apve1%3A1/log"] = [{"n": 1, "t": "starting"}, {"n": 2, "t": "TASK OK"}]
    assert pc.get_task_log(HOST, "s", "pve1", "UPID:pve1:1") == ["starting", "TASK OK"]


def test_sdn_overview_merges_pending_changes(api):
    api["/cluster/sdn/zones"] = [
        {"zone": "lab", "type": "vlan", "bridge": "vmbr0"},
        {"zone": "new1", "type": "simple", "state": "new", "pending": {"ipam": "pve"}},
    ]
    api["/cluster/sdn/vnets"] = [
        {"vnet": "vnet10", "zone": "lab", "tag": 10, "state": "changed", "pending": {"tag": 20}},
        {"vnet": "vnet11", "zone": "lab", "state": "new"},
    ]
    api["/cluster/sdn/vnets/vnet10/subnets"] = [
        {"cidr": "10.10.0.0/24", "vnet": "vnet10", "gateway": "10.10.0.1", "snat": 1,
         "dhcp-range": ["start-address=10.10.0.100,end-address=10.10.0.200"]},
    ]
    api["/nodes/pve1/sdn/zones"] = [{"zone": "lab", "status": "available"}]
    api["/cluster/sdn/controllers"] = []
    api["/cluster/sdn/ipams"] = [{"ipam": "pve", "type": "pve"}]
    api["/cluster/sdn/dns"] = FakeResponse(403, reason="Permission check failed")

    sdn = pc.get_sdn(HOST, "s", ["pve1"])
    assert [z.zone for z in sdn.zones] == ["lab", "new1"]
    assert sdn.zones[1].state == "new" and sdn.zones[1].options == {"ipam": "pve"}
    assert sdn.vnets[0].tag == 20 and sdn.vnets[0].state == "changed"  # pending value wins
    assert sdn.subnets[0].dhcp_ranges == ("10.10.0.100–10.10.0.200",)
    assert sdn.subnets[0].snat and sdn.subnets[0].gateway == "10.10.0.1"
    assert sdn.zone_status[0].status == "available"
    assert sdn.ipams == ({"ipam": "pve", "type": "pve"},) and sdn.dns == ()
    assert sdn.has_pending


def test_guests_by_bridge(api):
    api["/nodes/pve1/qemu/100/config"] = {"net0": "virtio=AA,bridge=vnet10", "net1": "e1000=BB,bridge=vmbr0"}
    api["/nodes/pve1/lxc/200/config"] = {"net0": "name=eth0,bridge=vnet10,ip=dhcp"}
    ct = ProxmoxGuest(vmid=200, name="pihole", node="pve1", type=LXC, status="running")
    assert pc.guests_by_bridge(HOST, "s", [_vm(), ct]) == {
        "vnet10": ["100 dc01", "200 pihole (CT)"],
        "vmbr0": ["100 dc01"],
    }


def test_web_and_novnc_urls():
    ct = ProxmoxGuest(vmid=200, name="pi hole", node="pve1", type=LXC, status="running")
    assert pc.novnc_url(HOST, ct) == (
        "https://pve1.lan:8006/?console=lxc&novnc=1&vmid=200&vmname=pi%20hole&node=pve1&resize=off&cmd="
    )
    assert pc.guest_web_url(HOST, _vm()).startswith("https://pve1.lan:8006/#v1:0:=qemu%2F100")
