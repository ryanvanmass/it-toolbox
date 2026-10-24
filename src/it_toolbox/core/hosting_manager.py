"""Remote management of a web server set up by the user's cockpit-hosting
Cockpit module, for the Cockpit Hosting Manager.

Everything is done by the module's own privileged helper
(`cockpit-hosting-helper <subcommand>`, JSON in, one JSON object out),
called over SSH exactly the way the Cockpit page's src/helper.ts calls it,
so both UIs share the module's SQLite database and generated nginx,
PHP-FPM and systemd configuration. Unlike the ProFTPD Manager there is no
bundled copy of the helper: it needs the module's schema, stack and
packaging, so the module itself must be installed on the server.

The methods below mirror helper.ts's `helper` object one to one.
"""

from __future__ import annotations

import re

from it_toolbox.core.remote_helper import (
    RemoteHelperConnection,
    RemoteHelperError,
    RemoteServer,
)

HELPER_PATH = "/usr/libexec/cockpit-hosting/cockpit-hosting-helper"

# Package installs and application downloads (Nextcloud's has its own
# 15-minute deadline in the helper, plus one retry) run far longer than
# an ordinary call.
SLOW_TIMEOUT = 45 * 60

SITE_TYPES = ["static", "php", "proxy", "node", "python", "container"]
SITE_TYPE_LABELS = {
    "static": "Static",
    "php": "PHP",
    "proxy": "Reverse proxy",
    "node": "Node.js",
    "python": "Python",
    "container": "Container",
}
# Sites that run an app the helper can start and stop.
APP_SITE_TYPES = {"node", "python", "container"}

STACK_COMPONENTS = ["nginx", "mariadb", "certbot", "nodejs", "python", "podman", "clamav", "fail2ban", "repo",
                    "backup"]
STACK_COMPONENT_LABELS = {
    "nginx": "nginx",
    "mariadb": "MariaDB",
    "certbot": "Certbot (Let's Encrypt)",
    "nodejs": "Node.js",
    "python": "Python",
    "podman": "Podman (container sites)",
    "clamav": "ClamAV (malware scanning)",
    "fail2ban": "fail2ban (intrusion protection)",
    "repo": "Package repository tools (createrepo_c, apt-ftparchive)",
    "backup": "Backup tools (restic and rclone)",
}

DNS_PROVIDERS = ["porkbun", "cloudflare"]
DNS_PROVIDER_LABELS = {"porkbun": "Porkbun", "cloudflare": "Cloudflare"}
# The fields each provider's credentials need (see the helper's
# cmd_dns_provider_set).
DNS_PROVIDER_FIELDS = {
    "porkbun": [("api_key", "API key"), ("secret_key", "Secret key")],
    "cloudflare": [("api_token", "API token")],
}

SSL_MODE_LABELS = {
    "none": "None",
    "letsencrypt-http": "Let's Encrypt (HTTP)",
    "letsencrypt-dns": "Let's Encrypt (DNS)",
    "custom": "Custom certificate",
    "self-signed": "Self-signed",
}
# Lifetimes the Cockpit page offers for a self-signed certificate; the
# helper takes days, at most 3650.
SELF_SIGNED_YEARS = [1, 2, 5, 10]

# What can be deployed into an existing, empty PHP site.
APPLICATIONS = ["wordpress", "nextcloud"]
APPLICATION_LABELS = {
    "wordpress": "WordPress",
    "nextcloud": "Nextcloud",
    "repo": "Package repository",
    "forgejo": "Forgejo",
    "zabbix": "Zabbix",
}

# The Create Site dialog's choices (the Cockpit page's siteTypeOptions):
# (id, site type, ready-made application or None, label). A ready-made
# application is created as a site of that type, then app-deploy'ed --
# except Forgejo and Zabbix, whose containers site-create sets up itself.
SITE_KINDS = [
    ("wordpress", "php", "wordpress", "WordPress"),
    ("nextcloud", "php", "nextcloud", "Nextcloud"),
    ("repo", "static", "repo", "Package repository (RPM and .deb)"),
    ("forgejo", "container", "forgejo", "Forgejo (Git hosting with Actions runners)"),
    ("zabbix", "container", "zabbix", "Zabbix (monitoring)"),
    ("php", "php", None, "PHP"),
    ("static", "static", None, "Static"),
    ("node", "node", None, "Node.js"),
    ("python", "python", None, "Python"),
    ("container", "container", None, "Container"),
    ("proxy", "proxy", None, "Reverse proxy"),
]
# Applications whose containers site-create makes (it takes `application`).
CONTAINER_APPLICATIONS = {"forgejo", "zabbix"}

# Zabbix releases the module runs, oldest first.
ZABBIX_RELEASES = ["7.0", "7.2", "7.4"]
# What a new Zabbix site can start on.
ZABBIX_NEW_RELEASES = ["7.0", "7.4"]
ZABBIX_ENGINE_LABELS = {"postgresql": "PostgreSQL", "mysql": "MySQL", "mariadb": "MariaDB"}

# A new Forgejo runner's labels: what runs-on: says, and the image its jobs run in.
FORGEJO_DEFAULT_LABELS = [
    "docker:docker://data.forgejo.org/oci/node:22-bookworm",
    "ubuntu-latest:docker://data.forgejo.org/oci/node:22-bookworm",
]


def zabbix_release_label(release: str) -> str:
    return f"{release} LTS" if release == "7.0" else release


def release_newer(a: str, b: str) -> bool:
    return tuple(int(part) for part in a.split(".")) > tuple(int(part) for part in b.split("."))


LOG_NAMES = ["access", "error", "php", "app"]
LOG_LABELS = {"access": "Access log", "error": "Error log", "php": "PHP errors", "app": "App output"}

TRAFFIC_RANGES = [("24h", "24 hours"), ("7d", "7 days"), ("30d", "30 days"), ("90d", "90 days"),
                  ("365d", "365 days")]

PHP_SETTING_KEYS = ["memory_limit", "upload_max_filesize", "post_max_size", "max_execution_time", "max_input_vars"]

MALWARE_ACTIONS = ["report", "quarantine", "delete"]
MALWARE_ACTION_LABELS = {
    "report": "Report only",
    "quarantine": "Move to quarantine",
    "delete": "Delete",
}

SMTP_SECURITY = ["starttls", "tls", "none"]
SMTP_SECURITY_LABELS = {"starttls": "STARTTLS", "tls": "TLS", "none": "None (unencrypted)"}
SMTP_PORTS = {"starttls": 587, "tls": 465, "none": 25}

# The jails the module manages, in the helper's order, with what each
# guards against (the Cockpit page's Fail2banCard JAILS).
FAIL2BAN_JAILS = {
    "sshd": ("SSH and SFTP logins", "Failed logins to the server, including the sites' SFTP users"),
    "hosting-nginx-auth": ("Password-protected pages", "Wrong passwords for pages behind an nginx login"),
    "hosting-botsearch": ("Vulnerability scanners",
                          "Requests for phpMyAdmin, webmail or WordPress pages that don't exist"),
    "hosting-forbidden": ("Hidden files", "Requests for files that are never served, such as .env and .git"),
    "hosting-wordpress": ("WordPress logins", "Failed logins on WordPress sites"),
    "hosting-wordpress-xmlrpc": ("WordPress XML-RPC", (
        "Every call to xmlrpc.php, where password guessing goes. Also blocks the WordPress apps and Jetpack."
    )),
    "hosting-nextcloud": ("Nextcloud logins", "Failed logins and two-factor checks on Nextcloud sites"),
    "hosting-bad-request": ("Malformed requests", "Requests nginx answers with 400 Bad Request"),
}
# (seconds, label) choices for fail2ban's time window and ban time.
FAIL2BAN_DURATIONS = [
    (600, "10 minutes"),
    (3600, "1 hour"),
    (6 * 3600, "6 hours"),
    (86400, "1 day"),
    (7 * 86400, "1 week"),
    (30 * 86400, "30 days"),
]
# The time window only offers up to a day.
FAIL2BAN_FINDTIMES = FAIL2BAN_DURATIONS[:4]


BACKUP_KINDS = ["drive", "s3", "sftp", "local"]
BACKUP_KIND_LABELS = {"drive": "Google Drive", "s3": "S3", "sftp": "SFTP", "local": "Folder on this server"}
S3_PROVIDERS = [
    ("AWS", "Amazon S3"), ("Cloudflare", "Cloudflare R2"), ("Wasabi", "Wasabi"), ("Minio", "MinIO"),
    ("Ceph", "Ceph"), ("DigitalOcean", "DigitalOcean Spaces"), ("Other", "Other S3-compatible"),
]
BACKUP_SCHEDULE_PRESETS = [
    ("0 2 * * *", "Every day at 02:00"),
    ("0 */6 * * *", "Every 6 hours"),
    ("0 * * * *", "Every hour"),
    ("0 2 * * 0", "Every Sunday at 02:00"),
]
BACKUP_MODES = [("global", "On the server's schedule"), ("custom", "On its own schedule"),
                ("off", "Only when I click Back Up Now")]


def schedule_label(schedule: str) -> str:
    return dict(BACKUP_SCHEDULE_PRESETS).get(schedule, schedule)


def backup_destination_text(destination: dict) -> str:
    kind = destination.get("kind")
    if kind == "drive":
        return f"Google Drive, {destination.get('path', '')}"
    if kind == "s3":
        return f"{destination.get('endpoint') or 's3.amazonaws.com'} {destination.get('path', '')}"
    if kind == "sftp":
        port = destination.get("port") or 22
        return (f"{destination.get('user')}@{destination.get('host')}{'' if port == 22 else f':{port}'}:"
                f"{destination.get('path', '')}")
    return destination.get("local_path") or ""


def backup_run_label(run: dict) -> str:
    """What a backup run did, as the Cockpit page's runWhat()."""
    snapshot = (run.get("snapshot") or "")[:8]
    detail = run.get("detail") or {}
    if run.get("kind") == "prune":
        return "Cleaned up old backups"
    if run.get("kind") == "restore":
        parts = (["files"] if detail.get("files") else []) + (["databases"] if detail.get("databases") else [])
        return f"Restored {' and '.join(parts)} from {snapshot}" if parts else f"Restore from {snapshot}"
    if run.get("state") != "done":
        return "Backup"
    text = f"Snapshot {snapshot}"
    databases = len(detail.get("databases") or [])
    if databases:
        text += f", {databases} database" + ("" if databases == 1 else "s")
    if run.get("bytes_added") is not None:
        text += f", {format_bytes(run['bytes_added'])} new"
    return text


def format_bytes(num_bytes: int | None) -> str:
    if num_bytes is None:
        return ""
    value = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{int(value)} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return ""


def jail_label(jail_id: str) -> str:
    return FAIL2BAN_JAILS.get(jail_id, (jail_id, ""))[0]


def duration_label(seconds: int) -> str:
    known = dict(FAIL2BAN_DURATIONS).get(seconds)
    if known:
        return known
    if seconds % 3600 == 0:
        hours = seconds // 3600
        return f"{hours} hour" + ("" if hours == 1 else "s")
    minutes = round(seconds / 60)
    return f"{minutes} minute" + ("" if minutes == 1 else "s")


# File names the helper takes from a package repository's incoming folder.
PACKAGE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+~^-]{0,250}\.(rpm|deb)$")

HostingError = RemoteHelperError


class HostingServer(RemoteServer):
    """A server saved in the Hosting Manager's sidebar."""


class HostingConnection(RemoteHelperConnection):
    HELPER_PATHS = (HELPER_PATH,)
    MODULE_NAME = "cockpit-hosting"

    # -- Server -----------------------------------------------------------

    def status(self) -> dict:
        return self.call("status")

    def settings_set(self, acme_email: str | None = None, storage_default: str | None = None) -> dict:
        settings = {key: value for key, value in (("acme_email", acme_email), ("storage_default", storage_default))
                    if value is not None}
        return self.call("settings-set", settings)

    def stack_install(self, components: list[str], php: list[str]) -> dict:
        return self.call("stack-install", {"components": components, "php": php}, timeout=SLOW_TIMEOUT)

    def dns_provider_set(self, provider: str, credentials: dict | None) -> dict:
        args = {"provider": provider, **credentials} if credentials else {"provider": provider, "clear": True}
        return self.call("dns-provider-set", args)

    # -- Sites ------------------------------------------------------------

    def site_list(self) -> list[dict]:
        return self.call("site-list").get("sites", [])

    def site_get(self, name: str) -> dict:
        return self.call("site-get", {"name": name})["site"]

    def site_suggest(self, domain: str) -> str:
        return self.call("site-suggest", {"domain": domain})["name"]

    def site_create(self, site_input: dict) -> dict:
        return self.call("site-create", site_input, timeout=SLOW_TIMEOUT)["site"]

    def site_update(self, name: str, changes: dict) -> dict:
        return self.call("site-update", {"name": name, **changes}, timeout=SLOW_TIMEOUT)["site"]

    def site_vhost_set(self, name: str, template: str | None = None, reset: bool = False) -> dict:
        """Saves an edited vhost template, or with reset=True goes back to the
        generated one. Returns the new vhost (as in site-get's `vhost`)."""
        args = {"name": name, "reset": True} if reset else {"name": name, "template": template}
        return self.call("site-vhost-set", args)["vhost"]

    def site_custom_nginx(self, name: str, text: str) -> str:
        """Release 6 and earlier, which have custom directives instead of the
        vhost editor (their site-get has `custom_nginx`, not `vhost`)."""
        return self.call("site-custom-nginx", {"name": name, "text": text})["text"]

    def site_disable(self, name: str) -> dict:
        return self.call("site-disable", {"name": name})["site"]

    def site_enable(self, name: str) -> dict:
        return self.call("site-enable", {"name": name})["site"]

    def site_delete(self, name: str, delete_databases: bool, keep_files: bool) -> dict:
        return self.call(
            "site-delete", {"name": name, "delete_databases": delete_databases, "keep_files": keep_files}
        )

    def site_logs(self, name: str, log: str, lines: int) -> dict:
        return self.call("site-logs", {"name": name, "log": log, "lines": lines})

    def site_traffic(self, name: str, traffic_range: str) -> dict:
        # Reads a year of access logs at most.
        return self.call("site-traffic", {"name": name, "range": traffic_range}, timeout=SLOW_TIMEOUT)

    # -- Moving a site's files (in a unit of its own; poll storage_status) --

    def storage_status(self, name: str, usage: bool = False) -> dict:
        return self.call("storage-status", {"name": name, "usage": usage})

    def storage_move(self, name: str, location: str, keep_old: bool) -> dict:
        return self.call("storage-move", {"name": name, "location": location, "keep_old": keep_old})

    def storage_clear(self, name: str) -> dict:
        return self.call("storage-clear", {"name": name})

    # -- Apps -------------------------------------------------------------

    def app_deploy(self, name: str, deploy_input: dict) -> dict:
        return self.call("app-deploy", {"name": name, **deploy_input}, timeout=SLOW_TIMEOUT)

    def app_update(self, name: str) -> dict:
        # Nextcloud's updater goes one major version at a time, then
        # Nextcloud Office pulls Collabora's newest image.
        return self.call("app-update", {"name": name}, timeout=SLOW_TIMEOUT)

    def app_office(self, name: str, enabled: bool) -> dict:
        # Setting up downloads Collabora Online's image (about 1 GB).
        return self.call("app-office", {"name": name, "enabled": enabled}, timeout=SLOW_TIMEOUT)["site"]

    def app_drawio(self, name: str, enabled: bool) -> dict:
        # Installs the Nextcloud app from the app store.
        return self.call("app-drawio", {"name": name, "enabled": enabled}, timeout=SLOW_TIMEOUT)["site"]

    def app_team_folders(self, name: str, enabled: bool) -> dict:
        return self.call("app-team-folders", {"name": name, "enabled": enabled}, timeout=SLOW_TIMEOUT)["site"]

    def app_control(self, name: str, action: str) -> dict:
        timeout = SLOW_TIMEOUT if action == "pull" else 300
        return self.call("app-control", {"name": name, "action": action}, timeout=timeout)["site"]

    # -- Forgejo sites ------------------------------------------------------

    def forgejo_runners(self, name: str) -> list[dict]:
        return self.call("forgejo-runners", {"name": name}).get("runners", [])

    def forgejo_runner_add(self, name: str, runner_name: str = "", labels: list[str] | None = None,
                           capacity: int = 1) -> list[dict]:
        args: dict = {"name": name, "capacity": capacity}
        if runner_name:
            args["runner_name"] = runner_name
        if labels:
            args["labels"] = labels
        # The first runner pulls the runner image.
        return self.call("forgejo-runner-add", args, timeout=SLOW_TIMEOUT).get("runners", [])

    def forgejo_runner_delete(self, name: str, runner_id: int) -> dict:
        """{runners, warning?}: the warning says what could not be cleaned up."""
        return self.call("forgejo-runner-delete", {"name": name, "id": runner_id})

    def forgejo_password(self, name: str) -> dict:
        return self.call("forgejo-password", {"name": name})

    # -- Zabbix sites -------------------------------------------------------

    def zabbix_status(self, name: str) -> dict:
        return self.call("zabbix-status", {"name": name})

    def zabbix_password(self, name: str, user: str = "") -> dict:
        args = {"name": name, "user": user} if user else {"name": name}
        return self.call("zabbix-password", args)

    def zabbix_update(self, name: str, version: str = "") -> dict:
        """Pulls the newest images of the site's release, or moves it to `version`."""
        args = {"name": name, "zabbix_version": version} if version else {"name": name}
        return self.call("app-update", args, timeout=SLOW_TIMEOUT)

    def zabbix_import_scan(self, name: str, scan_input: dict) -> dict:
        return self.call("zabbix-import-scan", {"name": name, **scan_input}, timeout=SLOW_TIMEOUT)

    def zabbix_import_start(self, name: str, options: dict) -> dict:
        return self.call("zabbix-import-start", {"name": name, **options})

    def zabbix_import_status(self, name: str) -> dict:
        return self.call("zabbix-import-status", {"name": name})

    def zabbix_import_cancel(self, name: str) -> dict:
        return self.call("zabbix-import-cancel", {"name": name})

    def zabbix_import_clear(self, name: str) -> dict:
        return self.call("zabbix-import-clear", {"name": name})

    def zabbix_import_forget(self, name: str) -> dict:
        return self.call("zabbix-import-forget", {"name": name})

    # -- Package repository sites -------------------------------------------

    def repo_status(self, name: str) -> dict:
        return self.call("repo-status", {"name": name})["repo"]

    def repo_reindex(self, name: str) -> dict:
        return self.call("repo-reindex", {"name": name}, timeout=SLOW_TIMEOUT)["repo"]

    def repo_delete(self, name: str, kind: str, file: str) -> dict:
        """kind is rpm, deb, or incoming (a file left in the upload folder)."""
        return self.call("repo-delete", {"name": name, "kind": kind, "file": file}, timeout=SLOW_TIMEOUT)["repo"]

    def repo_upload(self, incoming: str, file_name: str, data: bytes) -> None:
        """Writes a package into the repository's incoming folder as root,
        as the Cockpit page does with cockpit.file(); repo_reindex() then
        takes it in."""
        if not PACKAGE_NAME.match(file_name):
            raise HostingError(f"{file_name} is not an .rpm or .deb file name")
        status, _, err = self.run(["sh", "-c", 'cat > "$1"', "sh", f"{incoming.rstrip('/')}/{file_name}"], data,
                                  timeout=SLOW_TIMEOUT)
        if status != 0:
            raise HostingError(f"Could not upload {file_name}: {err.strip() or f'exit status {status}'}")

    # -- Importing sites from CloudPanel ------------------------------------

    def import_key(self) -> str:
        return self.call("import-key")["public_key"]

    def import_scan(self, scan_input: dict) -> dict:
        # Measures every site's files and databases over SSH.
        return self.call("import-scan", scan_input, timeout=SLOW_TIMEOUT)

    def import_start(self, sites: list[dict]) -> dict:
        return self.call("import-start", {"sites": sites})

    def import_status(self) -> dict:
        return self.call("import-status")

    def import_cancel(self) -> dict:
        return self.call("import-cancel")

    def import_clear(self) -> dict:
        return self.call("import-clear")

    def import_forget(self) -> dict:
        return self.call("import-forget")

    # -- Cron -------------------------------------------------------------

    def cron_list(self, name: str) -> list[dict]:
        return self.call("cron-list", {"name": name}).get("jobs", [])

    def cron_create(self, name: str, schedule: str, command: str) -> dict:
        return self.call("cron-create", {"name": name, "schedule": schedule, "command": command})["job"]

    def cron_update(self, job_id: int, changes: dict) -> dict:
        return self.call("cron-update", {"id": job_id, **changes})["job"]

    def cron_delete(self, job_id: int) -> dict:
        return self.call("cron-delete", {"id": job_id})

    def cron_run(self, job_id: int) -> dict:
        return self.call("cron-run", {"id": job_id})["job"]

    def cron_log(self, job_id: int) -> str:
        return self.call("cron-log", {"id": job_id}).get("text", "")

    def schedule_check(self, schedule: str) -> dict:
        return self.call("schedule-check", {"schedule": schedule})

    # -- SFTP -------------------------------------------------------------

    def sftp_get(self, name: str) -> dict:
        return self.call("sftp-get", {"name": name})["sftp"]

    def sftp_set(self, name: str, changes: dict) -> dict:
        return self.call("sftp-set", {"name": name, **changes})["sftp"]

    # -- SSL --------------------------------------------------------------

    def ssl_issue(self, name: str, method: str, provider: str | None = None) -> dict:
        args = {"name": name, "method": method}
        if provider:
            args["provider"] = provider
        # A DNS challenge waits for the TXT record to reach the zone's name servers.
        return self.call("ssl-issue", args, timeout=SLOW_TIMEOUT)["site"]

    def ssl_custom(self, name: str, certificate: str, private_key: str) -> dict:
        return self.call("ssl-custom", {"name": name, "certificate": certificate, "private_key": private_key})["site"]

    def ssl_self_signed(self, name: str, days: int) -> dict:
        return self.call("ssl-self-signed", {"name": name, "days": days})["site"]

    def ssl_remove(self, name: str) -> dict:
        return self.call("ssl-remove", {"name": name})["site"]

    # -- Databases --------------------------------------------------------

    def db_list(self) -> list[dict]:
        return self.call("db-list").get("databases", [])

    def db_create(self, name: str, user: str = "", password: str = "", site: str = "") -> dict:
        args = {"name": name}
        for key, value in (("user", user), ("password", password), ("site", site)):
            if value:
                args[key] = value
        return self.call("db-create", args)

    def db_delete(self, name: str) -> dict:
        return self.call("db-delete", {"name": name})

    def db_password(self, name: str) -> dict:
        return self.call("db-password", {"name": name})

    # -- Malware scanning -------------------------------------------------

    def malware_status(self) -> dict:
        return self.call("malware-status")

    def malware_settings(self, settings: dict) -> dict:
        return self.call("malware-settings", settings)

    def malware_scan(self) -> dict:
        return self.call("malware-scan")

    def malware_finding(self, finding_id: int, action: str) -> dict:
        return self.call("malware-finding", {"id": finding_id, "action": action})

    def malware_alerts(self, pushover: dict | None = None, smtp: dict | None = None) -> dict:
        """Changes where scan alerts go. Secrets left out keep the stored ones."""
        changes = {key: value for key, value in (("pushover", pushover), ("smtp", smtp)) if value is not None}
        return self.call("malware-alerts", changes)

    def malware_alert_test(self, target: str, changes: dict) -> dict:
        """Sends a test alert with these (unsaved) values over the stored ones."""
        return self.call("malware-alert-test", {"target": target, target: changes})

    # -- Backups (restic on rclone) -----------------------------------------

    def backup_status(self) -> dict:
        return self.call("backup-status")

    def backup_destination(self, destination: dict, password: str = "") -> dict:
        """Saves where backups go, opening (or creating) the restic
        repository there; the reply's `repository` is opened or created."""
        args = {**destination, "repository_password": password} if password else dict(destination)
        return self.call("backup-destination", args, timeout=SLOW_TIMEOUT)

    def backup_password(self) -> str:
        return self.call("backup-password")["password"]

    def backup_settings(self, settings: dict) -> dict:
        return self.call("backup-settings", settings)

    def backup_site(self, name: str, mode: str, schedule: str | None = None) -> dict:
        args = {"name": name, "mode": mode}
        if schedule:
            args["schedule"] = schedule
        return self.call("backup-site", args)

    def backup_now(self, name: str | None = None) -> dict:
        return self.call("backup-now", {"name": name} if name else {})

    def backup_snapshots(self, name: str) -> list[dict]:
        return self.call("backup-snapshots", {"name": name}, timeout=SLOW_TIMEOUT).get("snapshots", [])

    def backup_restore(self, name: str, snapshot: str, files: bool, databases: bool) -> dict:
        return self.call("backup-restore", {"name": name, "snapshot": snapshot, "files": files,
                                            "databases": databases})

    # -- Intrusion protection (fail2ban) ----------------------------------

    def fail2ban_status(self) -> dict:
        return self.call("fail2ban-status")

    def fail2ban_settings(self, settings: dict) -> dict:
        return self.call("fail2ban-settings", settings)

    def fail2ban_unban(self, jail: str, ip: str, allow: bool) -> dict:
        return self.call("fail2ban-unban", {"jail": jail, "ip": ip, "allow": allow})
