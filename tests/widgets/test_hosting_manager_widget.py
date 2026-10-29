import pytest
from PySide6.QtWidgets import QDialog, QMessageBox

from it_toolbox.core import hosting_manager as hm
from it_toolbox.core import remote_helper as rh
from it_toolbox.widgets import hosting_dialogs as dialogs
from it_toolbox.widgets import hosting_manager_widget as w
from it_toolbox.widgets import remote_helper_widget as rw

SERVER = hm.HostingServer(name="web", host="web.lan", username="admin")

STATUS = {
    "distro": {"id": "almalinux", "version": "10.0", "name": "AlmaLinux", "family": "el"},
    "supported": True,
    "usr_readonly": False,
    "security": {"kind": "selinux", "mode": "enforcing"},
    "firewall": {"kind": "firewalld", "active": True},
    "php_choices": ["8.3", "8.4"],
    "stack": {
        "nginx": {"version": "1.26.3", "active": True},
        "php": [{"version": "8.3", "source": "remi", "service": "php83-php-fpm", "active": True,
                 "cli_installed": True}],
        "mariadb": {"version": "10.11.11", "active": True},
        "certbot": {"version": "4.0.0"},
        "clamav": {"version": None, "active": False},
        "node": {"version": None},
        "podman": {"version": "5.4.0", "quadlet": True},
        "python": {"version": "3.12.9", "venv": True},
        "fail2ban": {"version": "1.1.0", "active": True},
    },
    "settings": {"acme_email": "me@ex.com", "dns_providers": {"porkbun": True, "cloudflare": False}},
}


def _site(name, site_type="php", **extra):
    site = {
        "name": name, "type": site_type, "system_user": name, "home": f"/home/{name}",
        "root_dir": f"/home/{name}/htdocs/{name}.com", "logs_dir": f"/home/{name}/logs",
        "data_dir": f"/home/{name}/data", "runtime_version": "8.3" if site_type == "php" else None,
        "php_settings": {"memory_limit": "256M", "upload_max_filesize": "64M", "post_max_size": "64M",
                         "max_execution_time": "60", "max_input_vars": "1000"} if site_type == "php" else None,
        "upstream": None, "app_command": None, "app_env": {}, "app_port": None, "app_state": None,
        "container": None, "volumes_dir": f"/home/{name}/volumes", "application": None,
        "ssl_mode": "none", "dns_provider": None, "force_https": False,
        "domains": [f"{name}.com", f"www.{name}.com"], "primary_domain": f"{name}.com",
        "certificate": None, "created_at": "2026-10-09T12:00:00+00:00",
        "custom_nginx": "", "container_info": None, "databases": [],
    }
    site.update(extra)
    return site


SITES = [
    _site("blog", ssl_mode="letsencrypt-http",
          certificate={"issuer": "Let's Encrypt", "expires": "2027-01-01T00:00:00+00:00"},
          application={"name": "wordpress", "version": "6.8", "admin_user": "admin", "admin_path": "/wp-admin/"},
          databases=[{"name": "blog_wp", "db_user": "blog_wp", "created_at": "2026-10-09T12:00:00+00:00"}]),
    _site("shop", "container", app_state="active", app_port=3001, upstream="http://127.0.0.1:3001",
          app_env={"MODE": "prod"},
          container={"image": "docker.io/library/nginx:latest", "port": 80, "volumes": ["/data"],
                     "command": None, "auto_update": False, "enabled": True}),
    _site("cloud", ssl_mode="self-signed",
          certificate={"issuer": "Self-signed", "expires": "2027-10-16T00:00:00+00:00"},
          application={"name": "nextcloud", "version": "31.0.9", "admin_user": "admin", "admin_path": "/",
                       "office": {"port": 9980, "state": "failed"}, "drawio": True},
          custom_nginx=None,
          vhost={"template": "server {\n    server_name {{server_name}};\n}\n", "edited": True, "outdated": True,
                 "generated": "server {\n    server_name {{server_name}};\n    listen 443;\n}\n",
                 "values": {"server_name": "cloud.com www.cloud.com"}, "path": "/etc/nginx/conf.d/hosting-cloud.conf"}),
]


BACKUP = {
    "enabled": True, "schedule": "0 2 * * *", "keep": {"daily": 7, "weekly": 4, "monthly": 6}, "alerts": True,
    "installed": True, "versions": {"restic": "0.17.3", "rclone": "1.68"},
    "destination": {"kind": "sftp", "path": "backups/web", "host": "nas.lan", "port": 22, "user": "bk",
                    "password_set": True, "private_key_set": False},
    "host": "web", "running": False, "busy_sites": [], "next_run": "Sat 2026-10-25 02:00:00 EDT",
    "alert_failure": None,
    "runs": [{"id": 2, "site": "shop", "kind": "backup", "started_at": "2026-10-24T02:00:00+00:00",
              "finished_at": "2026-10-24T02:01:00+00:00", "state": "failed", "snapshot": None, "bytes_added": None,
              "failure": "rclone: connection refused", "detail": None},
             {"id": 1, "site": "blog", "kind": "backup", "started_at": "2026-10-24T02:00:00+00:00",
              "finished_at": "2026-10-24T02:00:30+00:00", "state": "done", "snapshot": "a1b2c3d4e5f6",
              "bytes_added": 2048, "failure": None, "detail": {"databases": ["blog_wp"], "files": 10, "size": 1}}],
    "sites": [{"name": "blog", "mode": "global", "schedule": None, "last_backup": "2026-10-24T02:00:30+00:00"},
              {"name": "shop", "mode": "custom", "schedule": "0 */6 * * *", "last_backup": None},
              {"name": "cloud", "mode": "off", "schedule": None, "last_backup": None}],
}

TRAFFIC = {
    "range": "24h", "start": 1761264000, "end": 1761350400, "bucket": 3600,
    "series": [{"time": 1761264000 + i * 3600, "requests": i, "bytes": i * 100, "visitors": 1,
                "client_errors": 0, "server_errors": 0} for i in range(24)],
    "totals": {"requests": 276, "bytes": 27600, "visitors": 3, "client_errors": 4, "server_errors": 0},
    "statuses": [{"status": 200, "requests": 272}, {"status": 404, "requests": 4}],
    "pages": [{"path": "/", "requests": 200, "bytes": 20000}],
    "visitors": [{"ip": "203.0.113.9", "requests": 150, "bytes": 15000}],
    "missing": [{"path": "/wp-login.php", "requests": 4}], "referrers": [],
    "log_start": None, "truncated": False, "unparsed": 2, "log": "/home/blog/logs/access.log",
}


class FakeConnection:
    instances = []
    connect_errors = []
    helper_path = hm.HELPER_PATH
    extra_sites = []

    def __init__(self, server, **credentials):
        self.server = server
        self.credentials = credentials
        self.calls = []
        self.helper_path = type(self).helper_path
        self.sites = {s["name"]: dict(s) for s in [*SITES, *type(self).extra_sites]}
        self.storage_job = None
        FakeConnection.instances.append(self)

    def connect(self):
        if FakeConnection.connect_errors:
            raise FakeConnection.connect_errors.pop(0)

    def close(self):
        pass

    def _record(self, *call):
        self.calls.append(call)

    def status(self):
        return STATUS

    def site_list(self):
        return [dict(s) for s in self.sites.values()]

    def site_get(self, name):
        return dict(self.sites[name])

    def site_create(self, site_input):
        self._record("site_create", site_input)
        site = _site(site_input["name"] or "new", site_input["type"])
        self.sites[site["name"]] = site
        return site

    def site_update(self, name, changes):
        self._record("site_update", name, changes)
        self.sites[name].update({k: v for k, v in changes.items() if k in ("force_https", "domains")})
        return dict(self.sites[name])

    def site_delete(self, name, delete_databases, keep_files):
        self._record("site_delete", name, delete_databases, keep_files)
        del self.sites[name]
        return {"deleted": name}

    def app_control(self, name, action):
        self._record("app_control", name, action)
        return dict(self.sites[name])

    def site_logs(self, name, log, lines):
        self._record("site_logs", name, log, lines)
        return {"path": f"/home/{name}/logs/{log}.log", "text": "GET / 200"}

    def cron_list(self, name):
        return [{"id": 1, "site": name, "schedule": "@daily", "on_calendar": "daily", "command": "php cron.php",
                 "enabled": True, "next_run": None, "last_run": None, "running": False,
                 "last_result": "exit-code", "last_status": 2}]

    def cron_update(self, job_id, changes):
        self._record("cron_update", job_id, changes)
        return {}

    def sftp_get(self, name):
        return {"enabled": False, "password_set": False, "keys": [], "user": name, "host": "web.lan",
                "port": 22, "path": "/htdocs", "server_path": f"/home/{name}/htdocs", "ssh_installed": True}

    def sftp_set(self, name, changes):
        self._record("sftp_set", name, changes)
        result = self.sftp_get(name)
        result.update(enabled=changes.get("enabled", False))
        return result

    def db_list(self):
        return [{"name": "blog_wp", "db_user": "blog_wp", "site": "blog", "size": 2 * 1024 * 1024,
                 "created_at": "2026-10-09T12:00:00+00:00"}]

    def db_create(self, **values):
        self._record("db_create", values)
        return {"name": values["name"], "user": values["name"], "password": "generated", "host": "localhost"}

    def malware_status(self):
        return {"installed": True, "version": "1.4.2", "signatures": {"version": "27000", "date": "today"},
                "updater_active": True, "enabled": True, "schedule": "@daily", "action": "report",
                "running": False, "next_run": None,
                "scans": [{"id": 1, "started_at": "2026-10-09T03:00:00+00:00", "finished_at": None,
                           "state": "done", "sites": 2, "files_scanned": 100, "infected": 1, "failure": None}],
                "findings": [{"id": 7, "site": "blog", "path": "/home/blog/htdocs/x.php", "signature": "Eicar",
                              "status": "found", "action_error": None, "first_seen": "", "last_seen": "",
                              "updated_at": ""}]}

    def malware_finding(self, finding_id, action):
        self._record("malware_finding", finding_id, action)
        return self.malware_status()

    def malware_alerts(self, pushover=None, smtp=None):
        self._record("malware_alerts", pushover, smtp)
        return self.malware_status()

    def malware_alert_test(self, target, changes):
        self._record("malware_alert_test", target, changes)
        return {"sent": [target]}

    def ssl_self_signed(self, name, days):
        self._record("ssl_self_signed", name, days)
        self.sites[name].update(ssl_mode="self-signed")
        return dict(self.sites[name])

    def app_update(self, name):
        self._record("app_update", name)
        return {"site": dict(self.sites[name]), "previous_version": "31.0.9", "version": "32.0.1",
                "drawio_error": "app store unreachable"}

    def app_office(self, name, enabled):
        self._record("app_office", name, enabled)
        app = dict(self.sites[name]["application"])
        app["office"] = {"port": 9980, "state": "active"} if enabled else None
        self.sites[name]["application"] = app
        return dict(self.sites[name])

    def site_vhost_set(self, name, template=None, reset=False):
        self._record("site_vhost_set", name, template, reset)
        vhost = dict(self.sites[name]["vhost"])
        vhost.update(template=vhost["generated"] if reset else template, edited=not reset, outdated=False)
        self.sites[name]["vhost"] = vhost
        return vhost

    def site_custom_nginx(self, name, text):
        self._record("site_custom_nginx", name, text)
        return text

    def app_drawio(self, name, enabled):
        self._record("app_drawio", name, enabled)
        return dict(self.sites[name])

    def stack_install(self, components, php):
        self._record("stack_install", components, php)
        return {"installed": components}

    def fail2ban_status(self):
        return {"installed": True, "version": "1.1.0", "active": True, "enabled": True, "bantime": 3600,
                "findtime": 600, "maxretry": 5, "increment": True, "ignoreip": ["198.51.100.0/24"],
                "sync_failure": None,
                "jails": [
                    {"id": "sshd", "managed": True, "enabled": True, "selected": True, "running": True,
                     "waiting": False, "failed": 3, "total_failed": 9, "banned_count": 1, "total_banned": 4,
                     "banned": [{"ip": "203.0.113.5", "until": "2026-10-16 08:00:00"}]},
                    {"id": "hosting-nextcloud", "managed": True, "enabled": True, "selected": True,
                     "running": False, "waiting": True, "failed": 0, "total_failed": 0, "banned_count": 0,
                     "total_banned": 0, "banned": []},
                    {"id": "hosting-bad-request", "managed": True, "enabled": False, "selected": False,
                     "running": False, "waiting": False, "failed": 0, "total_failed": 0, "banned_count": 0,
                     "total_banned": 0, "banned": []},
                    {"id": "postfix", "managed": False, "enabled": True, "selected": True, "running": True,
                     "waiting": False, "failed": 0, "total_failed": 0, "banned_count": 0, "total_banned": 0,
                     "banned": []},
                ]}

    def fail2ban_settings(self, settings):
        self._record("fail2ban_settings", settings)
        return self.fail2ban_status()

    def fail2ban_unban(self, jail, ip, allow):
        self._record("fail2ban_unban", jail, ip, allow)
        return self.fail2ban_status()

    def site_disable(self, name):
        self._record("site_disable", name)
        self.sites[name]["disabled"] = True
        return dict(self.sites[name])

    def site_enable(self, name):
        self._record("site_enable", name)
        self.sites[name]["disabled"] = False
        return dict(self.sites[name])

    def site_traffic(self, name, traffic_range):
        self._record("site_traffic", name, traffic_range)
        return TRAFFIC

    def storage_status(self, name, usage=False):
        return {"storage": None, "storage_dir": f"/home/{name}", "home": f"/home/{name}", "job": self.storage_job,
                "moving": False, **({"used": 5 * 1024 * 1024, "free": None} if usage else {})}

    def storage_move(self, name, location, keep_old):
        self._record("storage_move", name, location, keep_old)
        self.storage_job = {"from": f"/home/{name}", "to": location, "state": "running", "step": "Copying",
                            "progress": 40, "failure": None, "result": None, "keep_old": keep_old}
        return self.storage_status(name)

    def storage_clear(self, name):
        self._record("storage_clear", name)
        self.storage_job = None
        return self.storage_status(name)

    def schedule_check(self, schedule):
        self._record("schedule_check", schedule)
        if schedule == "bad":
            raise rh.RemoteHelperError("Not a cron schedule or systemd calendar expression")
        return {"on_calendar": "*-*-* 02:00:00", "next_run": "Sat 2026-10-25 02:00:00"}

    def cron_create(self, name, schedule, command):
        self._record("cron_create", name, schedule, command)
        return {}

    def app_deploy(self, name, deploy_input):
        self._record("app_deploy", name, deploy_input)
        app = deploy_input["application"]
        self.sites[name]["application"] = {"name": app, "version": "1", "admin_user": "me", "admin_path": "/"}
        return {"site": dict(self.sites[name]), "admin_url": f"https://{name}.com/", "admin_user": "me",
                "admin_password": "secret"}

    def app_team_folders(self, name, enabled):
        self._record("app_team_folders", name, enabled)
        app = dict(self.sites[name]["application"])
        app["team_folders"] = enabled
        self.sites[name]["application"] = app
        return dict(self.sites[name])

    def import_status(self):
        return {"job": None, "running": False, "source": None, "scan": None, "public_key": None}

    def backup_status(self):
        return BACKUP

    def backup_snapshots(self, name):
        return [{"id": "a1b2c3d4e5f6a7b8", "short_id": "a1b2c3d4", "time": "2026-10-24T02:00:30+00:00",
                 "host": "web", "paths": [], "size": 4096, "files": 10}]

    def backup_site(self, name, mode, schedule=None):
        self._record("backup_site", name, mode, schedule)
        return BACKUP

    def backup_restore(self, name, snapshot, files, databases):
        self._record("backup_restore", name, snapshot, files, databases)
        return BACKUP

    def backup_now(self, name=None):
        self._record("backup_now", name)
        return BACKUP

    def backup_destination(self, destination, password=""):
        self._record("backup_destination", destination, password)
        return {**BACKUP, "repository": "opened"}

    def repo_status(self, name):
        return {"url": f"https://{name}.com", "fingerprint": "ABCD1234", "key_url": f"https://{name}.com/key.asc",
                "repo_file_url": "", "sources_url": "", "commands": {"dnf": "dnf config-manager …", "apt": "curl …"},
                "incoming": f"/home/{name}/htdocs/incoming", "sftp_path": "/htdocs/incoming",
                "packages": [{"kind": "rpm", "file": "tool-1.0-1.noarch.rpm", "size": 2048, "modified": "today"}],
                "waiting": [{"file": "broken.rpm", "reason": "not signed"}], "indexed_at": None,
                "last_error": None, "watching": False}

    def repo_delete(self, name, kind, file):
        self._record("repo_delete", name, kind, file)
        return self.repo_status(name)

    def forgejo_runners(self, name):
        return [{"id": 1, "name": "git-1", "labels": ["docker:docker://node:22"], "capacity": 2, "uuid": "u",
                 "state": "active", "status": "idle", "version": "v13.0.0"}]

    def forgejo_runner_add(self, name, runner_name="", labels=None, capacity=1):
        self._record("forgejo_runner_add", name, runner_name, labels, capacity)
        return self.forgejo_runners(name)

    def zabbix_status(self, name):
        return {"zabbixdb": "active", "zabbixserver": "failed", "import_running": False,
                "counts": {"hosts": 12, "templates": 300}}

    def zabbix_update(self, name, version=""):
        self._record("zabbix_update", name, version)
        return {"site": dict(self.sites[name]), "previous_version": "7.0.5", "version": "7.4.1"}


@pytest.fixture(autouse=True)
def _reset_fake():
    FakeConnection.instances = []
    FakeConnection.connect_errors = []
    FakeConnection.helper_path = hm.HELPER_PATH
    FakeConnection.extra_sites = []


def _make(qtbot):
    widget = w.HostingManagerWidget(SERVER, connection_factory=FakeConnection)
    qtbot.addWidget(widget)
    qtbot.waitUntil(lambda: widget.site_table.rowCount() == 3 + len(FakeConnection.extra_sites))
    return widget


def _select(qtbot, widget, row):
    name = [*SITES, *FakeConnection.extra_sites][row]["name"]
    widget.site_table.selectRow(row)
    qtbot.waitUntil(lambda: widget.detail.site is not None and widget.detail.name == name)


def test_connects_and_lists_sites_databases_malware_and_stack(qtbot):
    widget = _make(qtbot)

    assert widget.stack.currentWidget() is widget.tabs
    assert [widget.site_table.item(0, c).text() for c in range(5)] == [
        "blog.com", "PHP", "blog", "Let's Encrypt (HTTP), expires " + w.when_label("2027-01-01T00:00:00+00:00"),
        "WordPress 6.8",
    ]
    assert widget.site_table.item(1, 4).text() == "active"
    qtbot.waitUntil(lambda: widget.db_table.rowCount() == 1)
    assert widget.db_table.item(0, 3).text() == "2.0 MB"
    qtbot.waitUntil(lambda: widget.findings_table.rowCount() == 1)
    assert widget.scans_table.item(0, 5).text() == "1"
    stack_rows = {widget.stack_table.item(r, 0).text(): widget.stack_table.item(r, 1).text()
                  for r in range(widget.stack_table.rowCount())}
    assert stack_rows["nginx"] == "1.26.3"
    assert stack_rows["ClamAV"] == "Not installed"
    assert stack_rows["PHP 8.3"] == "8.3"
    assert widget.dns_labels["porkbun"].text() == "Configured"
    assert widget.acme_email.text() == "me@ex.com"
    assert "SELinux: enforcing" in widget.system_info.text()


def test_missing_module_shows_the_install_page(qtbot):
    FakeConnection.helper_path = None
    widget = w.HostingManagerWidget(SERVER, connection_factory=FakeConnection)
    qtbot.addWidget(widget)

    qtbot.waitUntil(lambda: widget.stack.currentWidget() is widget.missing_page)
    assert "cockpit-hosting" in widget.missing_page.text()


def test_prompts_for_sudo_password_and_reconnects(qtbot, monkeypatch):
    FakeConnection.connect_errors = [rh.SudoPasswordRequired()]
    monkeypatch.setattr(rw.QInputDialog, "getText", lambda *a, **k: ("pw", True))
    _make(qtbot)

    assert FakeConnection.instances[-1].credentials == {"sudo_password": "pw"}


def test_filter_matches_aliases(qtbot):
    widget = _make(qtbot)

    widget.filter.setText("www.shop")

    assert widget.site_table.isRowHidden(0)
    assert not widget.site_table.isRowHidden(1)


def test_php_site_details(qtbot):
    widget = _make(qtbot)
    _select(qtbot, widget, 0)
    detail = widget.detail
    form = detail.settings_form

    assert detail.domains.toPlainText() == "blog.com\nwww.blog.com"
    assert form.isRowVisible(detail.php_version) and not form.isRowVisible(detail.image)
    assert detail.php_version.currentData() == "8.3"
    assert detail.php_settings["memory_limit"].text() == "256M"
    assert detail.force_https.isEnabled()
    assert detail.app_box.isHidden() and not detail.application_box.isHidden()
    assert "WordPress 6.8" in detail.application_label.text()
    assert detail.deploy_button.isHidden()
    assert detail.site_db_table.item(0, 0).text() == "blog_wp"
    assert "Let's Encrypt" in detail.https_state.text()


def test_container_site_details(qtbot):
    widget = _make(qtbot)
    _select(qtbot, widget, 1)
    detail = widget.detail

    assert detail.settings_form.isRowVisible(detail.image)
    assert detail.image.text() == "docker.io/library/nginx:latest"
    assert detail.volumes.text() == "/data"
    assert detail.app_env.toPlainText() == "MODE=prod"
    assert not detail.app_box.isHidden() and not detail.app_buttons["pull"].isHidden()
    assert detail.application_box.isHidden()
    assert not detail.force_https.isEnabled()


def test_save_sends_only_changed_settings(qtbot):
    widget = _make(qtbot)
    _select(qtbot, widget, 0)
    detail = widget.detail
    connection = widget.connection

    detail.domains.setPlainText("blog.com\nwww.blog.com\nblog.org")
    detail.php_settings["memory_limit"].setText("512M")
    detail._save_settings()

    qtbot.waitUntil(lambda: any(c[0] == "site_update" for c in connection.calls))
    call = next(c for c in connection.calls if c[0] == "site_update")
    assert call == ("site_update", "blog", {"domains": ["blog.com", "www.blog.com", "blog.org"],
                                            "php_settings": {"memory_limit": "512M"}})


def test_container_settings_changes(qtbot):
    widget = _make(qtbot)
    _select(qtbot, widget, 1)
    detail = widget.detail

    detail.image.setText("docker.io/library/caddy:2")
    detail.app_env.setPlainText("MODE=dev\n# comment\nEXTRA=1")
    detail._save_settings()

    qtbot.waitUntil(lambda: any(c[0] == "site_update" for c in widget.connection.calls))
    call = next(c for c in widget.connection.calls if c[0] == "site_update")
    assert call[2] == {"image": "docker.io/library/caddy:2", "app_env": {"MODE": "dev", "EXTRA": "1"}}


def test_app_control_buttons(qtbot):
    widget = _make(qtbot)
    _select(qtbot, widget, 1)

    widget.detail.app_buttons["restart"].click()

    qtbot.waitUntil(lambda: ("app_control", "shop", "restart") in widget.connection.calls)


def test_create_site(qtbot, monkeypatch):
    widget = _make(qtbot)

    def fake_exec(dialog):
        dialog.type.setCurrentIndex(dialog.type.findData("php"))
        dialog.domain.setText("new.com")
        dialog.aliases.setText("www.new.com, alt.new.com")
        dialog.name.setText("new")
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(dialogs.CreateSiteDialog, "exec", fake_exec)
    widget.create_site()

    qtbot.waitUntil(lambda: widget.site_table.rowCount() == 4)
    assert ("site_create", {"type": "php", "domain": "new.com", "aliases": ["www.new.com", "alt.new.com"],
                            "name": "new", "php_version": "8.3"}) in widget.connection.calls
    qtbot.waitUntil(lambda: widget.detail.name == "new")


def test_create_site_dialog_fields_follow_the_type(qtbot):
    dialog = dialogs.CreateSiteDialog(STATUS)
    qtbot.addWidget(dialog)

    dialog.type.setCurrentIndex(dialog.type.findData("container"))
    dialog.domain.setText("app.com")
    dialog.image.setText("ghcr.io/x/y:1")
    dialog.container_port.setValue(8080)
    dialog.volumes.setText("/data, /config")
    dialog.env.setPlainText("A=1")

    assert dialog.form.isRowVisible(dialog.image) and not dialog.form.isRowVisible(dialog.php_version)
    assert dialog.site_input() == {
        "type": "container", "domain": "app.com", "aliases": ["www.app.com"], "name": "", "app_env": {"A": "1"},
        "image": "ghcr.io/x/y:1", "container_port": 8080, "volumes": ["/data", "/config"],
    }


def test_parse_env_rejects_bad_lines():
    assert dialogs.parse_env("A=1\n\n# x\nB==2") == {"A": "1", "B": "=2"}
    with pytest.raises(ValueError, match="KEY=value"):
        dialogs.parse_env("oops")


def test_delete_site(qtbot, monkeypatch):
    widget = _make(qtbot)
    _select(qtbot, widget, 1)

    def fake_exec(dialog):
        dialog.delete_databases.setChecked(True)
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(dialogs.DeleteSiteDialog, "exec", fake_exec)
    widget.delete_site(widget.detail.site)

    qtbot.waitUntil(lambda: widget.site_table.rowCount() == 2)
    assert ("site_delete", "shop", True, False) in widget.connection.calls
    assert widget.detail.site is None


def test_cron_and_logs_load_with_their_tab(qtbot):
    widget = _make(qtbot)
    _select(qtbot, widget, 0)
    detail = widget.detail

    detail.tabs.setCurrentIndex(detail.cron_index)
    qtbot.waitUntil(lambda: detail.cron_table.rowCount() == 1)
    assert detail.cron_table.item(0, 5).text() == "exit-code (exit 2)"

    detail.cron_table.selectRow(0)
    detail._toggle_cron()
    qtbot.waitUntil(lambda: ("cron_update", 1, {"enabled": False}) in widget.connection.calls)

    detail.tabs.setCurrentIndex(detail.logs_index)
    qtbot.waitUntil(lambda: detail.log_view.toPlainText() == "GET / 200")
    assert ("site_logs", "blog", "access", 200) in widget.connection.calls


def test_sftp_toggle(qtbot):
    widget = _make(qtbot)
    _select(qtbot, widget, 0)
    detail = widget.detail
    detail.tabs.setCurrentIndex(detail.sftp_index)
    qtbot.waitUntil(lambda: detail.sftp_loaded)

    detail.sftp_enabled.click()

    qtbot.waitUntil(lambda: ("sftp_set", "blog", {"enabled": True}) in widget.connection.calls)
    qtbot.waitUntil(lambda: detail.sftp_enabled.isChecked())


def test_create_database_shows_the_password_once(qtbot, monkeypatch):
    widget = _make(qtbot)
    shown = []

    def fake_db_exec(dialog):
        dialog.name.setText("shopdb")
        dialog.site.setCurrentIndex(dialog.site.findData("shop"))
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(dialogs.DatabaseDialog, "exec", fake_db_exec)
    monkeypatch.setattr(dialogs.CredentialsDialog, "exec", lambda dialog: shown.append(dialog) or 0)
    widget.create_database(None)

    qtbot.waitUntil(lambda: bool(shown))
    assert ("db_create", {"name": "shopdb", "user": "", "password": "", "site": "shop"}) in widget.connection.calls


def test_malware_finding_action(qtbot, monkeypatch):
    widget = _make(qtbot)
    qtbot.waitUntil(lambda: widget.findings_table.rowCount() == 1)
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)

    finding = widget.malware["findings"][0]
    widget._finding_action(finding, "quarantine")

    qtbot.waitUntil(lambda: ("malware_finding", 7, "quarantine") in widget.connection.calls)


def test_stack_dialog_marks_installed_components():
    dialog = dialogs.StackDialog(STATUS)
    assert dialog.components["nginx"].text().endswith("(installed)")
    assert not dialog.components["clamav"].text().endswith("(installed)")
    assert dialog.php["8.3"].text() == "8.3 (installed)"
    dialog.components["clamav"].setChecked(True)
    dialog.php["8.4"].setChecked(True)
    assert dialog.selection() == (["clamav"], ["8.4"])


def _yes(monkeypatch):
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)


def test_stack_lists_fail2ban(qtbot):
    widget = _make(qtbot)

    stack_rows = {widget.stack_table.item(r, 0).text(): widget.stack_table.item(r, 1).text()
                  for r in range(widget.stack_table.rowCount())}
    assert stack_rows["fail2ban"] == "1.1.0"
    dialog = dialogs.StackDialog(STATUS)
    assert dialog.components["fail2ban"].text().endswith("(installed)")


def test_nextcloud_site_shows_update_office_and_drawio(qtbot):
    widget = _make(qtbot)
    _select(qtbot, widget, 2)
    detail = widget.detail

    assert not detail.update_app_button.isHidden()
    assert not detail.nextcloud_extras.isHidden()
    assert detail.office_label.text() == "Nextcloud Office: failed"
    assert detail.office_setup.text() == "Repair" and not detail.office_remove.isHidden()
    assert detail.drawio_label.text() == "draw.io: set up"
    assert "Self-signed" in detail.https_state.text()
    assert detail.self_signed.text() == "Make New Self-Signed Certificate…"


def test_wordpress_site_has_no_nextcloud_extras(qtbot):
    widget = _make(qtbot)
    _select(qtbot, widget, 0)

    assert widget.detail.update_app_button.isHidden()
    assert widget.detail.nextcloud_extras.isHidden()


def test_office_repair(qtbot, monkeypatch):
    widget = _make(qtbot)
    _select(qtbot, widget, 2)
    _yes(monkeypatch)

    widget.detail.office_setup.click()

    qtbot.waitUntil(lambda: widget.detail.office_label.text() == "Nextcloud Office: running")
    assert ("app_office", "cloud", True) in widget.connection.calls
    assert widget.detail.office_setup.isHidden()


def test_nextcloud_update_reports_versions_and_extra_failures(qtbot, monkeypatch):
    widget = _make(qtbot)
    _select(qtbot, widget, 2)
    _yes(monkeypatch)
    info, warnings = [], []
    monkeypatch.setattr(QMessageBox, "information", lambda parent, title, text: info.append(text))
    monkeypatch.setattr(QMessageBox, "warning", lambda parent, title, text: warnings.append(text))

    widget.detail.update_app_button.click()

    qtbot.waitUntil(lambda: bool(info))
    assert ("app_update", "cloud") in widget.connection.calls
    assert info == ["Nextcloud was updated from 31.0.9 to 32.0.1."]
    assert len(warnings) == 1 and "draw.io could not be updated" in warnings[0]


def test_self_signed_certificate(qtbot, monkeypatch):
    widget = _make(qtbot)
    _select(qtbot, widget, 0)
    monkeypatch.setattr(w.QInputDialog, "getItem", lambda *a, **k: ("2 years", True))

    widget.detail.self_signed.click()

    qtbot.waitUntil(lambda: ("ssl_self_signed", "blog", 730) in widget.connection.calls)
    qtbot.waitUntil(lambda: "Self-signed" in widget.detail.https_state.text())


def test_malware_alerts_dialog_sends_only_typed_secrets(qtbot):
    alerts = {"pushover": {"enabled": True, "token_set": True, "user_set": True},
              "smtp": {"enabled": False, "host": "", "port": 587, "security": "starttls", "username": "",
                       "password_set": False, "sender": "", "recipients": []}}
    tests = []
    dialog = dialogs.MalwareAlertsDialog(alerts, lambda target, changes, _d: tests.append((target, changes)))
    qtbot.addWidget(dialog)

    assert dialog.pushover_ready()
    assert dialog.pushover_changes() == {"enabled": True}
    dialog.smtp_security.setCurrentIndex(dialog.smtp_security.findData("tls"))
    assert dialog.smtp_port.value() == 465
    dialog.smtp_enabled.setChecked(True)
    dialog.smtp_host.setText("smtp.ex.com")
    dialog.smtp_user.setText("me")
    dialog.smtp_password.setText("pw")
    dialog.smtp_sender.setText("server@ex.com")
    dialog.smtp_recipients.setText("a@ex.com, b@ex.com")
    dialog.smtp_test.click()

    assert tests == [("smtp", {"enabled": True, "host": "smtp.ex.com", "port": 465, "security": "tls",
                               "username": "me", "sender": "server@ex.com", "recipients": ["a@ex.com", "b@ex.com"],
                               "password": "pw"})]
    dialog.smtp_user.setText("")
    assert dialog.smtp_changes()["clear_password"] is True
    assert "password" not in dialog.smtp_changes()


def test_malware_alerts_saved_and_shown(qtbot, monkeypatch):
    widget = _make(qtbot)
    qtbot.waitUntil(lambda: bool(widget.malware))

    def fake_exec(dialog):
        dialog.pushover_enabled.setChecked(True)
        dialog.pushover_token.setText("tok")
        dialog.pushover_user.setText("usr")
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(dialogs.MalwareAlertsDialog, "exec", fake_exec)
    widget._edit_malware_alerts()

    qtbot.waitUntil(lambda: any(c[0] == "malware_alerts" for c in widget.connection.calls))
    call = next(c for c in widget.connection.calls if c[0] == "malware_alerts")
    assert call[1] == {"enabled": True, "token": "tok", "user": "usr"}
    assert call[2]["enabled"] is False


def test_fail2ban_tab(qtbot):
    widget = _make(qtbot)
    qtbot.waitUntil(lambda: widget.bans_table.rowCount() == 1)

    jails = {widget.jails_table.item(r, 0).text(): widget.jails_table.item(r, 1).text()
             for r in range(widget.jails_table.rowCount())}
    assert jails == {"SSH and SFTP logins": "Watching", "Nextcloud logins": "Waiting for a site",
                     "postfix (set up outside cockpit-hosting)": "Watching"}
    assert widget.bans_table.item(0, 0).text() == "203.0.113.5"
    assert widget.bans_table.item(0, 1).text() == "SSH and SFTP logins"
    info = widget.fail2ban_info.text()
    assert "after 5 failures within 10 minutes, for 1 hour, longer for repeat offenders" in info
    assert "198.51.100.0/24" in info
    assert widget.fail2ban_install.isHidden()


def test_fail2ban_unban_and_allow(qtbot):
    widget = _make(qtbot)
    qtbot.waitUntil(lambda: widget.bans_table.rowCount() == 1)

    widget._unban(widget.fail2ban["jails"][0]["banned"][0] | {"jail": "sshd"}, True)

    qtbot.waitUntil(lambda: ("fail2ban_unban", "sshd", "203.0.113.5", True) in widget.connection.calls)


def test_fail2ban_settings_dialog(qtbot):
    dialog = dialogs.Fail2banSettingsDialog(FakeConnection(SERVER).fail2ban_status())
    qtbot.addWidget(dialog)

    assert list(dialog.jails) == ["sshd", "hosting-nextcloud", "hosting-bad-request"]
    dialog.jails["hosting-bad-request"].setChecked(True)
    dialog.maxretry.setValue(3)
    dialog.bantime.setCurrentIndex(dialog.bantime.findData(86400))
    dialog.ignoreip.setPlainText("198.51.100.0/24\n192.0.2.7")

    assert dialog.settings() == {
        "enabled": True, "jails": ["sshd", "hosting-nextcloud", "hosting-bad-request"], "maxretry": 3,
        "findtime": 600, "bantime": 86400, "increment": True, "ignoreip": ["198.51.100.0/24", "192.0.2.7"],
    }
    dialog.enabled.setChecked(False)
    assert not dialog.jails["sshd"].isEnabled()


def test_fail2ban_not_installed_offers_install(qtbot, monkeypatch):
    monkeypatch.setattr(FakeConnection, "fail2ban_status", lambda self: {"installed": False, "jails": []})
    widget = _make(qtbot)
    qtbot.waitUntil(lambda: "isn't installed" in widget.fail2ban_info.text())

    assert not widget.fail2ban_install.isHidden() and widget.fail2ban_settings_button.isHidden()
    widget.fail2ban_install.click()
    qtbot.waitUntil(lambda: ("stack_install", ["fail2ban"], []) in widget.connection.calls)


def test_vhost_editor(qtbot, monkeypatch):
    widget = _make(qtbot)
    _select(qtbot, widget, 2)
    detail = widget.detail

    assert "{{server_name}}" in detail.custom_nginx.toPlainText()
    assert "/etc/nginx/conf.d/hosting-cloud.conf (edited)" in detail.nginx_note.text()
    assert not detail.vhost_outdated_row.isHidden() and not detail.vhost_reset.isHidden()
    detail.custom_nginx.setPlainText("server {\n    server_name {{server_name}};\n    listen 443;\n}\n")
    detail._save_nginx()
    qtbot.waitUntil(lambda: detail.vhost is not None and not detail.vhost["outdated"])
    assert widget.connection.calls[-1][0:2] == ("site_vhost_set", "cloud")
    assert detail.vhost_outdated_row.isHidden()

    _yes(monkeypatch)
    detail._reset_vhost()
    qtbot.waitUntil(lambda: ("site_vhost_set", "cloud", None, True) in widget.connection.calls)
    qtbot.waitUntil(lambda: detail.vhost_reset.isHidden())


def test_old_servers_keep_custom_directives(qtbot):
    widget = _make(qtbot)
    _select(qtbot, widget, 0)
    detail = widget.detail

    assert detail.vhost is None and detail.vhost_placeholders.isHidden() and detail.vhost_reset.isHidden()
    detail.custom_nginx.setPlainText("autoindex on;")
    detail._save_nginx()

    qtbot.waitUntil(lambda: ("site_custom_nginx", "blog", "autoindex on;") in widget.connection.calls)


# -- Parity with cockpit-hosting releases 8 to 14 and Zabbix ------------------------------

REPO_SITE = _site("pkgs", "static", application={"name": "repo", "version": "", "admin_user": "", "admin_path": "",
                                                  "fingerprint": "ABCD1234"})
FORGEJO_SITE = _site("git", "container", app_state="active", ssl_mode="letsencrypt-dns",
                     container={"image": "data.forgejo.org/forgejo/forgejo:17-rootless", "port": 3000,
                                "volumes": ["/var/lib/gitea"], "command": None, "auto_update": False, "enabled": True},
                     application={"name": "forgejo", "version": "17.0.1", "admin_user": "ryan",
                                  "admin_path": "/-/admin", "ssh_port": 2222, "runners": []})
ZABBIX_SITE = _site("zbx", "container", app_state="active",
                    container={"image": "zabbix/zabbix-web-nginx-pgsql:alpine-7.0-latest", "port": 8080,
                               "volumes": [], "command": None, "auto_update": False, "enabled": True},
                    application={"name": "zabbix", "version": "7.0.5", "admin_user": "", "admin_path": "/",
                                 "zabbix": "7.0", "engine": "postgresql", "server_port": 10051, "imported": None})

FULL_STATUS = {**STATUS, "stack": {**STATUS["stack"], "repo": {"version": None, "ready": False},
                                   "backup": {"version": "0.17.3", "rclone": "1.68"}},
               "settings": {**STATUS["settings"], "storage_default": "/srv/sites"}}


def test_create_dialog_offers_the_ready_made_applications(qtbot):
    dialog = dialogs.CreateSiteDialog(FULL_STATUS)
    qtbot.addWidget(dialog)

    kinds = [dialog.type.itemData(i) for i in range(dialog.type.count())]
    assert kinds[:5] == ["wordpress", "nextcloud", "repo", "forgejo", "zabbix"]
    repo = dialog.type.model().item(kinds.index("repo"))
    assert not repo.isEnabled()
    assert "package repository tools" in dialog.type.itemData(kinds.index("repo"), w.Qt.ItemDataRole.ToolTipRole)
    assert dialog.type.currentData() == "php"


def test_create_forgejo_site_input_and_admin(qtbot):
    dialog = dialogs.CreateSiteDialog(FULL_STATUS)
    qtbot.addWidget(dialog)
    dialog.type.setCurrentIndex(dialog.type.findData("forgejo"))
    dialog.domain.setText("git.example.com")
    dialog.deploy.admin_user.setText("ryan")

    assert not dialog.form.isRowVisible(dialog.image) and dialog.form.isRowVisible(dialog.deploy.admin_user)
    assert not dialog.form.isRowVisible(dialog.www)
    assert dialog.site_input() == {"type": "container", "domain": "git.example.com", "aliases": [], "name": "",
                                   "application": "forgejo"}
    assert dialog.deploy_input() == {"application": "forgejo", "admin_user": "ryan"}
    dialog.deploy.admin_user.setText("")
    assert "Forgejo needs an admin user" in dialog.deploy.problem()


def test_create_zabbix_site_input(qtbot):
    dialog = dialogs.CreateSiteDialog(FULL_STATUS)
    qtbot.addWidget(dialog)
    dialog.type.setCurrentIndex(dialog.type.findData("zabbix"))
    dialog.domain.setText("zbx.example.com")
    dialog.zabbix_version.setCurrentIndex(dialog.zabbix_version.findData("7.4"))
    dialog.deploy.admin_password.setText("long-password")

    assert not dialog.form.isRowVisible(dialog.deploy.admin_user)
    assert dialog.site_input()["zabbix_version"] == "7.4"
    assert dialog.deploy_input() == {"application": "zabbix", "admin_password": "long-password"}


def test_create_wordpress_deploys_after_creating(qtbot, monkeypatch):
    widget = _make(qtbot)
    shown = []

    def fake_exec(dialog):
        dialog.type.setCurrentIndex(dialog.type.findData("wordpress"))
        dialog.domain.setText("new.com")
        dialog.name.setText("new")
        dialog.deploy.admin_email.setText("me@new.com")
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(dialogs.CreateSiteDialog, "exec", fake_exec)
    monkeypatch.setattr(dialogs.CredentialsDialog, "exec", lambda dialog: shown.append(dialog) or 0)
    widget.create_site()

    qtbot.waitUntil(lambda: bool(shown))
    calls = widget.connection.calls
    assert ("site_create", {"type": "php", "domain": "new.com", "aliases": ["www.new.com"], "name": "new",
                            "php_version": "8.3"}) in calls
    deploy = next(c for c in calls if c[0] == "app_deploy")
    assert deploy[1:] == ("new", {"application": "wordpress", "admin_email": "me@new.com"})


def test_disable_and_enable_site(qtbot, monkeypatch):
    widget = _make(qtbot)
    _select(qtbot, widget, 0)
    _yes(monkeypatch)
    detail = widget.detail

    detail.disable_button.click()
    qtbot.waitUntil(lambda: ("site_disable", "blog") in widget.connection.calls)
    qtbot.waitUntil(lambda: detail.disable_button.text() == "Enable Site")
    assert not detail.disabled_note.isHidden()
    assert widget.site_table.item(0, 0).text() == "blog.com (disabled)"

    detail.disable_button.click()
    qtbot.waitUntil(lambda: ("site_enable", "blog") in widget.connection.calls)
    qtbot.waitUntil(lambda: detail.disabled_note.isHidden())


def test_traffic_tab_loads_with_its_range(qtbot):
    widget = _make(qtbot)
    _select(qtbot, widget, 0)
    detail = widget.detail

    detail.tabs.setCurrentIndex(detail.traffic_index)
    qtbot.waitUntil(lambda: ("site_traffic", "blog", "24h") in widget.connection.calls)
    qtbot.waitUntil(lambda: detail.traffic.pages_table.rowCount() == 1)
    assert "Requests: 276" in detail.traffic.totals.text() and "(1.4%)" in detail.traffic.totals.text()
    assert detail.traffic.statuses_table.item(1, 1).text() == "4 (1.4%)"
    assert "2 lines were not in nginx's log format" in detail.traffic.source.text()

    assert not detail.traffic.chart.grab().isNull()  # paints the bars and scale
    detail.traffic.range.setCurrentIndex(detail.traffic.range.findData("365d"))
    qtbot.waitUntil(lambda: ("site_traffic", "blog", "365d") in widget.connection.calls)


def test_move_files_shows_progress(qtbot, monkeypatch):
    widget = _make(qtbot)
    _select(qtbot, widget, 0)
    detail = widget.detail
    seen = []

    def fake_exec(dialog):
        seen.append(dialog)
        dialog.location.setText("/srv/sites/")
        dialog.keep_old.setChecked(True)
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(dialogs.MoveStorageDialog, "exec", fake_exec)
    detail.move_button.click()

    qtbot.waitUntil(lambda: ("storage_move", "blog", "/srv/sites", True) in widget.connection.calls)
    qtbot.waitUntil(lambda: "Moving the files to /srv/sites: Copying (40%)" in detail.storage_note.text())
    assert not detail.move_button.isEnabled()
    detail.stop()


def test_move_dialog_needs_a_folder_when_files_are_home(qtbot, monkeypatch):
    dialog = dialogs.MoveStorageDialog(SITES[0], 5 * 1024 * 1024)
    qtbot.addWidget(dialog)
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a: warnings.append(a[2]))

    dialog._accept()

    assert warnings and "already in the home folder" in warnings[0]
    dialog.location.setText("/mnt/disk")
    assert "/mnt/disk/blog" in dialog.help.text()


def test_cron_dialog_checks_the_schedule(qtbot):
    checks = []

    def checker(schedule):
        checks.append(schedule)
        if schedule == "bad":
            raise rh.RemoteHelperError("Not a cron schedule")
        return {"on_calendar": "*-*-* 02:00:00", "next_run": "tomorrow 02:00"}

    dialog = dialogs.CronJobDialog(checker=checker)
    qtbot.addWidget(dialog)
    dialog.schedule.edit.setText("0 2 * * *")
    qtbot.waitUntil(lambda: "tomorrow 02:00" in dialog.schedule.result.text())
    assert dialog.schedule.error() is None

    dialog.schedule.edit.setText("bad")
    qtbot.waitUntil(lambda: dialog.schedule.error() == "Not a cron schedule")
    assert checks == ["0 2 * * *", "bad"]


def test_team_folders(qtbot, monkeypatch):
    widget = _make(qtbot)
    _select(qtbot, widget, 2)
    _yes(monkeypatch)
    detail = widget.detail

    assert detail.team_folders_label.text() == "Team folders: not set up"
    detail.team_folders_setup.click()

    qtbot.waitUntil(lambda: detail.team_folders_label.text() == "Team folders: set up")
    assert ("app_team_folders", "cloud", True) in widget.connection.calls


def test_backups_tab(qtbot):
    widget = _make(qtbot)
    tab = widget.backups_tab
    qtbot.waitUntil(lambda: tab.sites_table.rowCount() == 3)

    assert "bk@nas.lan:backups/web" in tab.info.text()
    assert "The last backup failed for: shop.com" in tab.info.text()
    assert tab.sites_table.item(1, 1).text() == "Own schedule: Every 6 hours"
    assert tab.sites_table.item(1, 2).text() == "Never — last one failed"
    assert tab.runs_table.item(1, 2).text() == "Snapshot a1b2c3d4, 1 database, 2.0 KB new"
    assert tab.runs_table.item(0, 3).text() == "Failed: rclone: connection refused"
    assert tab.install_button.isHidden() and not tab.now_button.isHidden()


def test_site_backups_restore(qtbot, monkeypatch):
    widget = _make(qtbot)
    _select(qtbot, widget, 0)
    detail = widget.detail
    detail.tabs.setCurrentIndex(detail.backups_index)
    qtbot.waitUntil(lambda: detail.backups.snapshots_table.rowCount() == 1)
    assert detail.backups.modes["global"].isChecked()

    def fake_exec(dialog):
        dialog.databases.setChecked(False)
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(dialogs.RestoreDialog, "exec", fake_exec)
    detail.backups.snapshots_table.selectRow(0)
    detail.backups._restore()
    qtbot.waitUntil(lambda: ("backup_restore", "blog", "a1b2c3d4e5f6a7b8", True, False) in widget.connection.calls)

    detail.backups.modes["off"].setChecked(True)
    detail.backups._save()
    qtbot.waitUntil(lambda: ("backup_site", "blog", "off", None) in widget.connection.calls)


def test_backup_destination_dialog_keeps_saved_secrets(qtbot):
    dialog = dialogs.BackupDestinationDialog(BACKUP)
    qtbot.addWidget(dialog)

    assert dialog.kind.currentData() == "sftp"
    assert dialog.problem() is None
    assert dialog.destination() == {"kind": "sftp", "path": "backups/web", "host": "nas.lan", "port": 22,
                                    "user": "bk"}
    dialog.kind.setCurrentIndex(dialog.kind.findData("s3"))
    assert dialog.problem() == "S3 needs an access key and a secret key."
    dialog.kind.setCurrentIndex(dialog.kind.findData("local"))
    dialog.local_path.setText("relative")
    assert "absolute" in dialog.problem()


def test_package_repository_card(qtbot, monkeypatch):
    FakeConnection.extra_sites = [REPO_SITE]
    widget = _make(qtbot)
    _select(qtbot, widget, 3)
    card = widget.detail.repo_card
    _yes(monkeypatch)

    qtbot.waitUntil(lambda: card.packages.rowCount() == 2)
    assert not card.isHidden() and widget.detail.application_box.isHidden()
    assert "Uploads are not being watched" in card.problem.text()
    assert card.packages.item(1, 1).text() == "incoming"
    card.packages.selectRow(1)
    card._delete()
    qtbot.waitUntil(lambda: ("repo_delete", "pkgs", "incoming", "broken.rpm") in widget.connection.calls)


def test_forgejo_card_and_runner(qtbot, monkeypatch):
    FakeConnection.extra_sites = [FORGEJO_SITE]
    widget = _make(qtbot)
    _select(qtbot, widget, 3)
    card = widget.detail.forgejo_card

    qtbot.waitUntil(lambda: card.runners.rowCount() == 1)
    assert "ssh://git@git.com:2222/OWNER/REPO.git" in card.info.text()
    assert card.runners.item(0, 3).text() == "Idle"
    assert card.admin_button.isHidden() and not card.password_button.isHidden()
    assert widget.detail.settings_form.isRowVisible(widget.detail.image)

    def fake_exec(dialog):
        dialog.runner_name.setText("big")
        dialog.capacity.setValue(4)
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(dialogs.AddRunnerDialog, "exec", fake_exec)
    card._add_runner()
    qtbot.waitUntil(lambda: ("forgejo_runner_add", "git", "big", hm.FORGEJO_DEFAULT_LABELS, 4)
                    in widget.connection.calls)
    card.stop()


def test_zabbix_card(qtbot, monkeypatch):
    FakeConnection.extra_sites = [ZABBIX_SITE]
    widget = _make(qtbot)
    _select(qtbot, widget, 3)
    detail = widget.detail
    card = detail.zabbix_card

    qtbot.waitUntil(lambda: "server failed" in card.info.text())
    assert "12 hosts, 300 templates" in card.info.text()
    assert "Admin still has the default password" in card.info.text()
    assert not card.admin_button.isHidden()
    assert not detail.settings_form.isRowVisible(detail.image)

    def fake_exec(dialog):
        dialog.release.setCurrentIndex(dialog.release.findData("7.4"))
        return QDialog.DialogCode.Accepted

    infos = []
    monkeypatch.setattr(dialogs.ZabbixUpdateDialog, "exec", fake_exec)
    monkeypatch.setattr(QMessageBox, "information", lambda parent, title, text: infos.append(text))
    card._update()
    qtbot.waitUntil(lambda: bool(infos))
    assert ("zabbix_update", "zbx", "7.4") in widget.connection.calls
    assert infos == ["Zabbix was updated from 7.0.5 to 7.4.1."]
    card.stop()


def test_zabbix_update_dialog_offers_only_newer_releases(qtbot):
    dialog = dialogs.ZabbixUpdateDialog("7.2")
    qtbot.addWidget(dialog)

    assert [dialog.release.itemData(i) for i in range(dialog.release.count())] == ["7.2", "7.4"]
    assert dialog.new_release() == ""


def test_server_tab_shows_new_components_and_storage(qtbot, monkeypatch):
    monkeypatch.setattr(FakeConnection, "status", lambda self: FULL_STATUS)
    widget = _make(qtbot)

    stack_rows = {widget.stack_table.item(r, 0).text(): widget.stack_table.item(r, 1).text()
                  for r in range(widget.stack_table.rowCount())}
    assert stack_rows["restic (backups)"] == "0.17.3, rclone 1.68"
    assert stack_rows["Package repository tools"] == "Not installed"
    assert widget.storage_default.text() == "/srv/sites/<site>"
    dialog = dialogs.StackDialog(FULL_STATUS)
    assert dialog.components["backup"].text().endswith("(installed)")
    assert not dialog.components["repo"].text().endswith("(installed)")


def test_cloudpanel_import_choices(qtbot):
    scan = {
        "source": {"host": "cp.lan", "port": 22, "user": "root", "auth": "password", "fingerprint": "SHA256:x",
                   "cloudpanel_version": "2.5", "db_version": "8.0", "mysql_error": None},
        "php_here": ["8.3"],
        "scanned_at": "",
        "sites": [
            {"id": 1, "domain": "shop.com", "domains": ["shop.com"], "cloudpanel_type": "php", "type": "php",
             "application": "WooCommerce", "user": "shop", "name": "shop", "existing": None, "root": "shop.com",
             "php_version": "8.2", "php_target": None, "php_settings": {}, "app_port": None, "app_command": None,
             "upstream": None, "force_https": True, "databases": [], "cron": [], "certificate": None,
             "sftp_keys": 0, "size": 1024, "skipped": [], "notes": [],
             "blockers": ["PHP 8.2 is not installed here"]},
            {"id": 2, "domain": "api.com", "domains": ["api.com"], "cloudpanel_type": "nodejs", "type": "node",
             "application": None, "user": "api", "name": "api", "existing": None, "root": "api.com",
             "php_version": None, "php_target": None, "php_settings": {}, "app_port": 3000,
             "app_command": "npm start", "upstream": None, "force_https": False, "databases": [], "cron": [],
             "certificate": None, "sftp_keys": 1, "size": None, "skipped": ["Node.js version"], "notes": [],
             "blockers": []},
            {"id": 3, "domain": "old.com", "domains": ["old.com"], "cloudpanel_type": "static", "type": "static",
             "application": None, "user": "old", "name": "old", "existing": "old", "root": "old.com",
             "php_version": None, "php_target": None, "php_settings": {}, "app_port": None, "app_command": None,
             "upstream": None, "force_https": False, "databases": [], "cron": [], "certificate": None,
             "sftp_keys": 0, "size": 10, "skipped": [], "notes": [], "blockers": []},
        ],
    }

    class Conn(FakeConnection):
        def import_status(self):
            return {"job": None, "running": False, "source": scan["source"], "scan": scan, "public_key": None}

    from it_toolbox.widgets import hosting_import

    dialog = hosting_import.CloudPanelImportDialog(Conn(SERVER))
    qtbot.addWidget(dialog)
    qtbot.waitUntil(lambda: dialog.sites_table.rowCount() == 3)

    assert not dialog.sites_table.cellWidget(0, 0).isEnabled()
    dialog.sites_table.cellWidget(1, 4).setText("api2")
    assert dialog.chosen() == [{"id": 2, "name": "api2", "app_command": "npm start"}, {"id": 3}]
    php = dialog.sites_table.cellWidget(0, 3)
    php.setCurrentIndex(php.findData("8.3"))
    assert dialog.sites_table.cellWidget(0, 0).isChecked()
    assert dialog.chosen()[0] == {"id": 1, "name": "shop", "php_version": "8.3"}
    assert "Not copied (no equivalent here):\n  • Node.js version" in hosting_import.plan_details(scan["sites"][1])


def test_detail_shows_a_placeholder_until_a_site_is_picked(qtbot):
    widget = _make(qtbot)
    detail = widget.detail

    assert detail.pages.currentWidget() is detail.placeholder
    _select(qtbot, widget, 0)
    assert detail.pages.currentWidget() is detail.content
    assert "Files: /home/blog/htdocs/blog.com" in detail.overview_text()
    assert detail.heading.text() == "blog.com"
    assert "WordPress" in detail.subheading.text()
