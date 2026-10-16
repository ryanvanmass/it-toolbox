"""Remote management of a web server set up by the user's cockpit-hosting
Cockpit module, for the General Tools Hosting Manager.

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

STACK_COMPONENTS = ["nginx", "mariadb", "certbot", "nodejs", "python", "podman", "clamav", "fail2ban"]
STACK_COMPONENT_LABELS = {
    "nginx": "nginx",
    "mariadb": "MariaDB",
    "certbot": "Certbot (Let's Encrypt)",
    "nodejs": "Node.js",
    "python": "Python",
    "podman": "Podman (container sites)",
    "clamav": "ClamAV (malware scanning)",
    "fail2ban": "fail2ban (intrusion protection)",
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

APPLICATIONS = ["wordpress", "nextcloud"]
APPLICATION_LABELS = {"wordpress": "WordPress", "nextcloud": "Nextcloud"}

LOG_NAMES = ["access", "error", "php", "app"]
LOG_LABELS = {"access": "Access log", "error": "Error log", "php": "PHP errors", "app": "App output"}

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


HostingError = RemoteHelperError


class HostingServer(RemoteServer):
    """A server saved in the Hosting Manager's sidebar."""


class HostingConnection(RemoteHelperConnection):
    HELPER_PATHS = (HELPER_PATH,)
    MODULE_NAME = "cockpit-hosting"

    # -- Server -----------------------------------------------------------

    def status(self) -> dict:
        return self.call("status")

    def settings_set(self, acme_email: str) -> dict:
        return self.call("settings-set", {"acme_email": acme_email})

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

    def site_custom_nginx(self, name: str, text: str) -> str:
        return self.call("site-custom-nginx", {"name": name, "text": text})["text"]

    def site_delete(self, name: str, delete_databases: bool, keep_files: bool) -> dict:
        return self.call(
            "site-delete", {"name": name, "delete_databases": delete_databases, "keep_files": keep_files}
        )

    def site_logs(self, name: str, log: str, lines: int) -> dict:
        return self.call("site-logs", {"name": name, "log": log, "lines": lines})

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

    def app_control(self, name: str, action: str) -> dict:
        timeout = SLOW_TIMEOUT if action == "pull" else 300
        return self.call("app-control", {"name": name, "action": action}, timeout=timeout)["site"]

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

    # -- Intrusion protection (fail2ban) ----------------------------------

    def fail2ban_status(self) -> dict:
        return self.call("fail2ban-status")

    def fail2ban_settings(self, settings: dict) -> dict:
        return self.call("fail2ban-settings", settings)

    def fail2ban_unban(self, jail: str, ip: str, allow: bool) -> dict:
        return self.call("fail2ban-unban", {"jail": jail, "ip": ip, "allow": allow})
