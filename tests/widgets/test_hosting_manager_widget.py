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


@pytest.fixture(autouse=True)
def _reset_fake():
    FakeConnection.instances = []
    FakeConnection.connect_errors = []
    FakeConnection.helper_path = hm.HELPER_PATH


def _make(qtbot):
    widget = w.HostingManagerWidget(SERVER, connection_factory=FakeConnection)
    qtbot.addWidget(widget)
    qtbot.waitUntil(lambda: widget.site_table.rowCount() == 2)
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

    qtbot.waitUntil(lambda: widget.site_table.rowCount() == 3)
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

    qtbot.waitUntil(lambda: widget.site_table.rowCount() == 1)
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
