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
    ],
)
def test_slow_calls_get_the_long_timeout(call):
    conn = _Scripted({"site": {}, "installed": []})
    call(conn)
    assert conn.calls[0][2] == hm.SLOW_TIMEOUT


def test_ssl_issue_over_http_sends_no_provider():
    conn = _Scripted({"site": {}})
    conn.ssl_issue("a", "http")
    assert conn.calls[0][1] == {"name": "a", "method": "http"}
