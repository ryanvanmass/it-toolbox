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
                       "office": {"port": 9980, "state": "failed"}, "drawio": True}),
]


class FakeConnection:
    instances = []
    connect_errors = []
    helper_path = hm.HELPER_PATH

    def __init__(self, server, **credentials):
        self.server = server
        self.credentials = credentials
        self.calls = []
        self.helper_path = type(self).helper_path
        self.sites = {s["name"]: dict(s) for s in SITES}
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


@pytest.fixture(autouse=True)
def _reset_fake():
    FakeConnection.instances = []
    FakeConnection.connect_errors = []
    FakeConnection.helper_path = hm.HELPER_PATH


def _make(qtbot):
    widget = w.HostingManagerWidget(SERVER, connection_factory=FakeConnection)
    qtbot.addWidget(widget)
    qtbot.waitUntil(lambda: widget.site_table.rowCount() == 3)
    return widget


def _select(qtbot, widget, row):
    widget.site_table.selectRow(row)
    qtbot.waitUntil(lambda: widget.detail.site is not None and widget.detail.name == SITES[row]["name"])


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
        "type": "container", "domain": "app.com", "aliases": [], "name": "", "app_env": {"A": "1"},
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
