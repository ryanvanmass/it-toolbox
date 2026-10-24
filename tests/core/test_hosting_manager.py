import json
import shlex

import pytest

from it_toolbox.core import hosting_manager as hm
from it_toolbox.core import remote_helper as rh

SERVER = hm.HostingServer(name="web", host="web.lan", username="root")


class _Scripted(hm.HostingConnection):
    """Answers every helper call with `reply`, recording (subcommand, args, timeout)."""

    def __init__(self, reply):
        super().__init__(SERVER)
        self._client = object()
        self.helper_path = hm.HELPER_PATH
        self.reply = reply
        self.calls = []

    def _exec_raw(self, command, stdin=b"", timeout=rh.DEFAULT_TIMEOUT):
        argv = shlex.split(command)
        assert argv[0] == hm.HELPER_PATH
        self.calls.append((argv[1], json.loads(stdin), timeout))
        return 0, json.dumps(self.reply), ""


def test_finds_the_rpm_and_deb_helper_path():
    assert hm.HostingConnection.HELPER_PATHS == ("/usr/libexec/cockpit-hosting/cockpit-hosting-helper",)


def test_server_round_trips_as_hosting_server():
    assert hm.HostingServer.from_dict(SERVER.to_dict()) == SERVER
    assert isinstance(hm.HostingServer.from_dict(SERVER.to_dict()), hm.HostingServer)


@pytest.mark.parametrize(
    "call, reply, subcommand, args, result",
    [
        (lambda c: c.site_list(), {"sites": [{"name": "a"}]}, "site-list", {}, [{"name": "a"}]),
        (lambda c: c.site_get("a"), {"site": {"name": "a"}}, "site-get", {"name": "a"}, {"name": "a"}),
        (lambda c: c.site_suggest("ex.com"), {"name": "ex"}, "site-suggest", {"domain": "ex.com"}, "ex"),
        (lambda c: c.site_update("a", {"force_https": True}), {"site": {"name": "a"}}, "site-update",
         {"name": "a", "force_https": True}, {"name": "a"}),
        (lambda c: c.site_delete("a", True, False), {"deleted": "a"}, "site-delete",
         {"name": "a", "delete_databases": True, "keep_files": False}, {"deleted": "a"}),
        (lambda c: c.site_logs("a", "error", 50), {"path": "/p", "text": "t"}, "site-logs",
         {"name": "a", "log": "error", "lines": 50}, {"path": "/p", "text": "t"}),
        (lambda c: c.site_vhost_set("a", "server {}\n"), {"vhost": {"edited": True}}, "site-vhost-set",
         {"name": "a", "template": "server {}\n"}, {"edited": True}),
        (lambda c: c.site_vhost_set("a", reset=True), {"vhost": {"edited": False}}, "site-vhost-set",
         {"name": "a", "reset": True}, {"edited": False}),
        (lambda c: c.site_custom_nginx("a", "x;"), {"text": "x;"}, "site-custom-nginx",
         {"name": "a", "text": "x;"}, "x;"),
        (lambda c: c.app_control("a", "restart"), {"site": {"name": "a"}}, "app-control",
         {"name": "a", "action": "restart"}, {"name": "a"}),
        (lambda c: c.cron_list("a"), {"jobs": []}, "cron-list", {"name": "a"}, []),
        (lambda c: c.cron_update(3, {"enabled": False}), {"job": {"id": 3}}, "cron-update",
         {"id": 3, "enabled": False}, {"id": 3}),
        (lambda c: c.cron_log(3), {"text": "out"}, "cron-log", {"id": 3}, "out"),
        (lambda c: c.sftp_set("a", {"keys": "k"}), {"sftp": {"enabled": True}}, "sftp-set",
         {"name": "a", "keys": "k"}, {"enabled": True}),
        (lambda c: c.ssl_custom("a", "C", "K"), {"site": {"name": "a"}}, "ssl-custom",
         {"name": "a", "certificate": "C", "private_key": "K"}, {"name": "a"}),
        (lambda c: c.ssl_remove("a"), {"site": {"name": "a"}}, "ssl-remove", {"name": "a"}, {"name": "a"}),
        (lambda c: c.db_list(), {"databases": [{"name": "d"}]}, "db-list", {}, [{"name": "d"}]),
        (lambda c: c.db_create("d", site="a"), {"password": "p"}, "db-create", {"name": "d", "site": "a"},
         {"password": "p"}),
        (lambda c: c.db_password("d"), {"password": "p"}, "db-password", {"name": "d"}, {"password": "p"}),
        (lambda c: c.malware_finding(4, "ignore"), {"findings": []}, "malware-finding",
         {"id": 4, "action": "ignore"}, {"findings": []}),
        (lambda c: c.dns_provider_set("porkbun", {"api_key": "a", "secret_key": "b"}),
         {"configured": True}, "dns-provider-set", {"provider": "porkbun", "api_key": "a", "secret_key": "b"},
         {"configured": True}),
        (lambda c: c.dns_provider_set("cloudflare", None), {"configured": False}, "dns-provider-set",
         {"provider": "cloudflare", "clear": True}, {"configured": False}),
        (lambda c: c.settings_set("me@ex.com"), {}, "settings-set", {"acme_email": "me@ex.com"}, {}),
        (lambda c: c.ssl_self_signed("a", 730), {"site": {"name": "a"}}, "ssl-self-signed",
         {"name": "a", "days": 730}, {"name": "a"}),
        (lambda c: c.app_update("a"), {"site": {}, "version": "32.0.1"}, "app-update", {"name": "a"},
         {"site": {}, "version": "32.0.1"}),
        (lambda c: c.app_office("a", True), {"site": {"name": "a"}}, "app-office", {"name": "a", "enabled": True},
         {"name": "a"}),
        (lambda c: c.app_drawio("a", False), {"site": {"name": "a"}}, "app-drawio", {"name": "a", "enabled": False},
         {"name": "a"}),
        (lambda c: c.malware_alerts(smtp={"enabled": False}), {"alerts": {}}, "malware-alerts",
         {"smtp": {"enabled": False}}, {"alerts": {}}),
        (lambda c: c.malware_alert_test("pushover", {"token": "t"}), {"sent": ["pushover"]}, "malware-alert-test",
         {"target": "pushover", "pushover": {"token": "t"}}, {"sent": ["pushover"]}),
        (lambda c: c.fail2ban_status(), {"installed": True}, "fail2ban-status", {}, {"installed": True}),
        (lambda c: c.fail2ban_settings({"maxretry": 3}), {"maxretry": 3}, "fail2ban-settings", {"maxretry": 3},
         {"maxretry": 3}),
        (lambda c: c.fail2ban_unban("sshd", "203.0.113.5", True), {"jails": []}, "fail2ban-unban",
         {"jail": "sshd", "ip": "203.0.113.5", "allow": True}, {"jails": []}),
        (lambda c: c.settings_set(storage_default="/srv/sites"), {}, "settings-set",
         {"storage_default": "/srv/sites"}, {}),
        (lambda c: c.site_disable("a"), {"site": {"disabled": True}}, "site-disable", {"name": "a"},
         {"disabled": True}),
        (lambda c: c.site_enable("a"), {"site": {"disabled": False}}, "site-enable", {"name": "a"},
         {"disabled": False}),
        (lambda c: c.site_traffic("a", "7d"), {"range": "7d"}, "site-traffic", {"name": "a", "range": "7d"},
         {"range": "7d"}),
        (lambda c: c.storage_status("a", usage=True), {"job": None}, "storage-status", {"name": "a", "usage": True},
         {"job": None}),
        (lambda c: c.storage_move("a", "/srv", True), {"job": {}}, "storage-move",
         {"name": "a", "location": "/srv", "keep_old": True}, {"job": {}}),
        (lambda c: c.storage_clear("a"), {"job": None}, "storage-clear", {"name": "a"}, {"job": None}),
        (lambda c: c.app_team_folders("a", True), {"site": {"name": "a"}}, "app-team-folders",
         {"name": "a", "enabled": True}, {"name": "a"}),
        (lambda c: c.forgejo_runners("a"), {"runners": [{"id": 1}]}, "forgejo-runners", {"name": "a"}, [{"id": 1}]),
        (lambda c: c.forgejo_runner_add("a", labels=["x:docker://y"], capacity=2), {"runners": []},
         "forgejo-runner-add", {"name": "a", "capacity": 2, "labels": ["x:docker://y"]}, []),
        (lambda c: c.forgejo_runner_delete("a", 3), {"runners": [], "warning": "w"}, "forgejo-runner-delete",
         {"name": "a", "id": 3}, {"runners": [], "warning": "w"}),
        (lambda c: c.forgejo_password("a"), {"user": "me", "password": "p"}, "forgejo-password", {"name": "a"},
         {"user": "me", "password": "p"}),
        (lambda c: c.zabbix_status("a"), {"zabbixdb": "active"}, "zabbix-status", {"name": "a"},
         {"zabbixdb": "active"}),
        (lambda c: c.zabbix_password("a", "Admin"), {"user": "Admin"}, "zabbix-password",
         {"name": "a", "user": "Admin"}, {"user": "Admin"}),
        (lambda c: c.zabbix_update("a", "7.4"), {"version": "7.4.1"}, "app-update",
         {"name": "a", "zabbix_version": "7.4"}, {"version": "7.4.1"}),
        (lambda c: c.zabbix_update("a"), {"version": "7.0.5"}, "app-update", {"name": "a"}, {"version": "7.0.5"}),
        (lambda c: c.zabbix_import_start("a", {"history": False}), {"running": True}, "zabbix-import-start",
         {"name": "a", "history": False}, {"running": True}),
        (lambda c: c.zabbix_import_forget("a"), {"scan": None}, "zabbix-import-forget", {"name": "a"},
         {"scan": None}),
        (lambda c: c.repo_status("a"), {"repo": {"url": "u"}}, "repo-status", {"name": "a"}, {"url": "u"}),
        (lambda c: c.repo_delete("a", "incoming", "x.rpm"), {"repo": {}}, "repo-delete",
         {"name": "a", "kind": "incoming", "file": "x.rpm"}, {}),
        (lambda c: c.import_key(), {"public_key": "ssh-ed25519 K"}, "import-key", {}, "ssh-ed25519 K"),
        (lambda c: c.import_start([{"id": 1, "name": "a"}]), {"running": True}, "import-start",
         {"sites": [{"id": 1, "name": "a"}]}, {"running": True}),
        (lambda c: c.import_cancel(), {"running": False}, "import-cancel", {}, {"running": False}),
        (lambda c: c.backup_destination({"kind": "local", "local_path": "/b"}, "pw"), {"repository": "created"},
         "backup-destination", {"kind": "local", "local_path": "/b", "repository_password": "pw"},
         {"repository": "created"}),
        (lambda c: c.backup_destination({"kind": "local", "local_path": "/b"}), {"repository": "opened"},
         "backup-destination", {"kind": "local", "local_path": "/b"}, {"repository": "opened"}),
        (lambda c: c.backup_password(), {"password": "pw"}, "backup-password", {}, "pw"),
        (lambda c: c.backup_site("a", "custom", "0 3 * * *"), {"sites": []}, "backup-site",
         {"name": "a", "mode": "custom", "schedule": "0 3 * * *"}, {"sites": []}),
        (lambda c: c.backup_site("a", "off"), {"sites": []}, "backup-site", {"name": "a", "mode": "off"},
         {"sites": []}),
        (lambda c: c.backup_now(), {"running": True}, "backup-now", {}, {"running": True}),
        (lambda c: c.backup_now("a"), {"running": False}, "backup-now", {"name": "a"}, {"running": False}),
        (lambda c: c.backup_snapshots("a"), {"snapshots": [{"id": "s"}]}, "backup-snapshots", {"name": "a"},
         [{"id": "s"}]),
        (lambda c: c.backup_restore("a", "s", True, False), {"runs": []}, "backup-restore",
         {"name": "a", "snapshot": "s", "files": True, "databases": False}, {"runs": []}),
    ],
)
def test_methods_match_the_cockpit_pages_helper_calls(call, reply, subcommand, args, result):
    conn = _Scripted(reply)
    assert call(conn) == result
    assert conn.calls[0][:2] == (subcommand, args)


@pytest.mark.parametrize(
    "call",
    [
        lambda c: c.stack_install(["nginx"], ["8.3"]),
        lambda c: c.site_create({"type": "php", "domain": "ex.com"}),
        lambda c: c.app_deploy("a", {"application": "nextcloud"}),
        lambda c: c.app_control("a", "pull"),
        lambda c: c.ssl_issue("a", "dns", "porkbun"),
        lambda c: c.app_update("a"),
        lambda c: c.app_office("a", True),
        lambda c: c.app_drawio("a", True),
        lambda c: c.app_team_folders("a", True),
        lambda c: c.forgejo_runner_add("a"),
        lambda c: c.zabbix_update("a", "7.4"),
        lambda c: c.import_scan({"host": "cp.lan"}),
        lambda c: c.zabbix_import_scan("a", {"host": "zbx.lan"}),
        lambda c: c.backup_destination({"kind": "local"}),
        lambda c: c.backup_snapshots("a"),
        lambda c: c.repo_reindex("a"),
    ],
)
def test_slow_calls_get_the_long_timeout(call):
    conn = _Scripted({"site": {}, "installed": [], "repo": {}, "public_key": ""})
    call(conn)
    assert conn.calls[0][2] == hm.SLOW_TIMEOUT


class _Uploads(hm.HostingConnection):
    def __init__(self):
        super().__init__(SERVER)
        self._client = object()
        self.helper_path = hm.HELPER_PATH
        self.commands = []

    def _exec_raw(self, command, stdin=b"", timeout=rh.DEFAULT_TIMEOUT):
        self.commands.append((shlex.split(command), stdin))
        return 0, "", ""


def test_repo_upload_writes_into_incoming_as_root():
    conn = _Uploads()
    conn.repo_upload("/home/pkgs/incoming/", "tool-1.0-1.noarch.rpm", b"RPM")
    argv, stdin = conn.commands[0]
    assert argv == ["sh", "-c", 'cat > "$1"', "sh", "/home/pkgs/incoming/tool-1.0-1.noarch.rpm"]
    assert stdin == b"RPM"


def test_repo_upload_refuses_other_file_names():
    with pytest.raises(hm.HostingError, match="not an .rpm or .deb"):
        _Uploads().repo_upload("/in", "../evil.rpm.sh", b"")


def test_backup_labels():
    assert hm.backup_destination_text({"kind": "sftp", "user": "bk", "host": "nas", "port": 2222, "path": "b"}) == \
        "bk@nas:2222:b"
    assert hm.backup_destination_text({"kind": "s3", "path": "bucket/x"}) == "s3.amazonaws.com bucket/x"
    assert hm.schedule_label("0 */6 * * *") == "Every 6 hours"
    assert hm.backup_run_label({"kind": "backup", "state": "done", "snapshot": "abcdef123456", "bytes_added": 2048,
                                "detail": {"databases": ["a", "b"]}}) == "Snapshot abcdef12, 2 databases, 2.0 KB new"
    assert hm.backup_run_label({"kind": "restore", "snapshot": "abcdef123456",
                                "detail": {"files": True, "databases": []}}) == "Restored files from abcdef12"
    assert hm.release_newer("7.4", "7.0") and not hm.release_newer("7.0", "7.0")


def test_ssl_issue_over_http_sends_no_provider():
    conn = _Scripted({"site": {}})
    conn.ssl_issue("a", "http")
    assert conn.calls[0][1] == {"name": "a", "method": "http"}


def test_duration_labels():
    assert hm.duration_label(3600) == "1 hour"
    assert hm.duration_label(7200) == "2 hours"
    assert hm.duration_label(120) == "2 minutes"
    assert hm.jail_label("hosting-nextcloud") == "Nextcloud logins"
    assert hm.jail_label("custom-jail") == "custom-jail"
