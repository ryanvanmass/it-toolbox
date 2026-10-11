import subprocess

from it_toolbox.core import cockpit_machines as cm
from it_toolbox.core import hosting_manager as hm
from it_toolbox.core import proftpd_manager as pm
from it_toolbox.core import scheduler_manager as sm
from it_toolbox.core.cockpit_machines import CockpitMachine

WEB = CockpitMachine(name="web", host="web.lan", username="admin")


def test_round_trips_through_a_dict():
    machine = CockpitMachine(
        name="nas", host="nas.lan", username="admin", port=2222, key_path="/k",
        proftpd_container="ftp", tools=["proftpd"],
    )
    again = CockpitMachine.from_dict(machine.to_dict())
    assert again == machine and again.tools == ["proftpd"]
    assert CockpitMachine.from_dict({"name": "x"}) is None
    assert CockpitMachine.from_dict(WEB.to_dict()).tools is None


def test_server_for_builds_each_managers_server():
    machine = CockpitMachine(name="nas", host="nas.lan", username="admin", proftpd_container="ftp")
    proftpd = machine.server_for(cm.PROFTPD)
    assert isinstance(proftpd, pm.ProftpdServer) and proftpd.docker_container == "ftp"
    assert machine.server_for(cm.HOSTING) == hm.HostingServer(name="nas", host="nas.lan", username="admin")
    assert isinstance(machine.server_for(cm.SCHEDULER), sm.SchedulerServer)
    assert machine.cockpit_url == "https://nas.lan:9090/"


def test_parse_detected_keeps_sidebar_order():
    assert cm.parse_detected("scheduler\nhosting\nproftpd\n") == ["proftpd", "hosting", "scheduler"]
    assert cm.parse_detected("proftpd-no-helper\n") == ["proftpd-no-helper"]
    assert cm.parse_detected("") == []


def _run_detect(tmp_path, machine, present):
    """Runs the detection script locally with the helper paths mapped into
    tmp_path, so the real shell logic is exercised."""
    script = cm.detect_script(machine)
    for path in (pm.COCKPIT_HELPER_PATH, pm.BUNDLED_HELPER_PATH, hm.HELPER_PATH, sm.HELPER_PATH):
        script = script.replace(path, str(tmp_path / path.lstrip("/")))
    for path in present:
        target = tmp_path / path.lstrip("/")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("")
        target.chmod(0o755)
    script = script.replace("command -v proftpd", "false")
    out = subprocess.run(["sh", "-c", script], capture_output=True, text=True, check=True).stdout
    return cm.parse_detected(out)


def test_detect_script_finds_installed_helpers(tmp_path):
    assert _run_detect(tmp_path, WEB, []) == []
    assert _run_detect(tmp_path, WEB, [pm.BUNDLED_HELPER_PATH, sm.HELPER_PATH]) == ["proftpd", "scheduler"]


def test_detect_script_checks_proftpd_inside_its_container():
    script = cm.detect_script(CockpitMachine(name="n", host="n", username="u", proftpd_container="ftp"))
    assert "docker exec ftp sh -c" in script
    assert f"[ -x {hm.HELPER_PATH} ]" in script


def test_migrate_merges_tool_servers_by_login():
    machines = cm.migrate_tool_servers(
        [{"name": "NAS", "host": "nas.lan", "username": "admin", "docker_container": "ftp"}],
        [{"name": "web", "host": "web.lan", "username": "admin"},
         {"name": "nas again", "host": "NAS.lan", "username": "admin", "key_path": "/k"}],
        [{"name": "web", "host": "web.lan", "username": "admin"}, {"broken": True}],
    )
    assert [(m.name, m.tools) for m in machines] == [
        ("NAS", ["proftpd", "hosting"]),
        ("web", ["hosting", "scheduler"]),
    ]
    assert machines[0].proftpd_container == "ftp" and machines[0].key_path == "/k"


def test_has_tool_counts_proftpd_without_its_helper():
    machine = CockpitMachine(name="n", host="n", username="u", tools=["proftpd-no-helper"])
    assert cm.has_tool(machine, cm.PROFTPD) and not cm.has_tool(machine, cm.HOSTING)
