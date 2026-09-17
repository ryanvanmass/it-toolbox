"""GL.iNet router dashboard access via the third-party `python-glinet`
library (PyPI: python-glinet, import name pyglinet).

`pyglinet` is GPLv3+ licensed; it-toolbox is Apache-2.0. To avoid bundling
or distributing GPL code as part of this project, it is deliberately kept
out of pyproject.toml and never vendored — it's an optional, user-installed
runtime dependency, exactly like FreeRDP's native libraries
(core/rdp/freerdp_client.py) and SpiceWidget's PyGObject dependency
(widgets/spice_widget.py). If a user wants GL.iNet dashboards, they
`pip install python-glinet` themselves; is_available() reports whether
that's been done. See docs/glinet-dashboard-status.md.

Mirrors qemu_client.py's shape: a flat exception class, host passed as a
plain first argument, and one stateless function per operation rather than
a long-lived client object — every call opens its own GlInet session
(keep_alive=False) and always logs out afterward, so we never have to
manage GlInet's background keep-alive thread lifecycle.

Response field names below are grounded in pyglinet's own bundled
`api_description.json` (its `out_example`/`results` entries for
system.get_status, wifi.get_config, and clients.get_list) — installed
alongside the library at `pyglinet/api/api_description.json`. That file
corrected several wrong assumptions found only by testing against a
real router (see git history): `wifi`, `service`, and `client` in
system.get_status()'s result are lists, not dicts keyed by name (a
service's status is looked up by its own "name" field instead), and
wifi.get_config()'s per-band configs live under a top-level "res" list,
not directly on the result object. Still not exhaustively verified
against every router/firmware version — see the small parsing helpers
in each function here, which exist specifically so a later field-name
correction stays isolated to this file.
"""

import requests

from it_toolbox.modules.connection_manager.models import (
    GlinetClientInfo,
    GlinetHost,
    GlinetOverview,
    GlinetWifiRadio,
)

try:
    from pyglinet import GlInet
    from pyglinet.exceptions import (
        AccessDeniedError,
        KeepAliveThreadActiveError,
        LoggedInError,
        MethodNotFoundError,
        NotLoggedInError,
        UnsupportedHashAlgoError,
        WrongApiDescriptionError,
        WrongParametersError,
    )

    _PYGLINET_ERRORS: tuple[type[Exception], ...] = (
        AccessDeniedError,
        NotLoggedInError,
        LoggedInError,
        WrongParametersError,
        MethodNotFoundError,
        KeepAliveThreadActiveError,
        WrongApiDescriptionError,
        UnsupportedHashAlgoError,
    )
except ImportError:
    GlInet = None
    _PYGLINET_ERRORS = ()


class GlinetApiError(Exception):
    pass


def is_available() -> bool:
    return GlInet is not None


def _call(host: GlinetHost, password: str, fn):
    if GlInet is None:
        raise GlinetApiError(
            "python-glinet isn't installed — see Settings for install instructions."
        )

    glinet = GlInet(
        url=host.url,
        username=host.username,
        password=password,
        keep_alive=False,
        verify_ssl_certificate=host.verify_ssl,
    )
    try:
        glinet.login()
        return fn(glinet.get_api_client())
    except _PYGLINET_ERRORS as exc:
        raise GlinetApiError(str(exc)) from exc
    except (ConnectionError, requests.RequestException) as exc:
        raise GlinetApiError(f"Couldn't reach {host.url}: {exc}") from exc
    finally:
        try:
            glinet.logout()
        except Exception:  # noqa: BLE001 - best-effort cleanup, never masks the real result/error
            pass


def get_overview(host: GlinetHost, password: str) -> GlinetOverview:
    def fetch(api_client) -> GlinetOverview:
        status = api_client.system.get_status()
        system = status.get("system", {})
        wifi_list = status.get("wifi") or []
        service_list = status.get("service") or []
        client = _as_single_dict(status.get("client"))

        radios = tuple(
            GlinetWifiRadio(
                # This endpoint's wifi entries have no separate
                # device/iface distinction the way wifi.get_config()'s
                # do -- "name" (e.g. "default_radio0") is the only
                # identifier available. Not used as a set_wifi_config()
                # param (only get_wifi_config()'s richer output is), so
                # reusing it for both fields here is harmless.
                device=radio.get("name", ""),
                iface_name=radio.get("name", ""),
                band=radio.get("band", ""),
                ssid=radio.get("ssid", ""),
                enabled=bool(radio.get("up", False)),
            )
            for radio in wifi_list
        )

        def service_up(name: str) -> bool:
            # service.status: 0 not enabled | 1 connected successfully |
            # 2 enabled but connection not successful -- only 1 counts
            # as "up" for this at-a-glance overview.
            return _find_by_name(service_list, name).get("status") == 1

        return GlinetOverview(
            uptime=_format_uptime(system.get("uptime")),
            lan_ip=system.get("lan_ip", ""),
            memory_used_pct=_percent_used(system.get("memory_total"), system.get("memory_free")),
            cpu_temp=_as_float((system.get("cpu") or {}).get("temperature")),
            wireless_client_count=int(client.get("wireless_total", 0) or 0),
            cable_client_count=int(client.get("cable_total", 0) or 0),
            wifi_radios=radios,
            wg_client_up=service_up("wgclient"),
            wg_server_up=service_up("wgserver"),
            ovpn_client_up=service_up("ovpnclient"),
            ovpn_server_up=service_up("ovpnserver"),
        )

    return _call(host, password, fetch)


def _as_single_dict(value) -> dict:
    """system.get_status()'s "client" field is documented as a single
    object but the API's own bundled example response wraps it in a
    one-item list -- handle either shape rather than trust one over the
    other."""
    if isinstance(value, list):
        return value[0] if value else {}
    return value or {}


def _find_by_name(items, name: str) -> dict:
    if not isinstance(items, list):
        return {}
    return next((item for item in items if item.get("name") == name), {})


def _percent_used(total, free) -> float | None:
    if not total or free is None:
        return None
    return round((1 - free / total) * 100, 1)


def _as_float(value) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _format_uptime(value) -> str:
    """system.get_status()'s uptime is a raw seconds count (confirmed
    against a real router: fractional, e.g. 862.15 -- not the whole
    integer the API's own bundled example shows), not a display string
    -- render it as a human-readable duration instead of the bare
    number."""
    try:
        total_seconds = int(float(value))
    except (TypeError, ValueError):
        return ""
    days, remainder = divmod(total_seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, seconds = divmod(remainder, 60)
    parts = []
    if days:
        parts.append(f"{days}d")
    if days or hours:
        parts.append(f"{hours}h")
    if days or hours or minutes:
        parts.append(f"{minutes}m")
    parts.append(f"{seconds}s")
    return " ".join(parts)


def list_clients(host: GlinetHost, password: str) -> list[GlinetClientInfo]:
    def fetch(api_client) -> list[GlinetClientInfo]:
        result = api_client.clients.get_list()
        clients = result.get("clients", [])
        return sorted(
            (
                GlinetClientInfo(
                    mac=c.get("mac", ""),
                    name=c.get("name", ""),
                    ip=c.get("ip", ""),
                    online=bool(c.get("online", False)),
                    vendor=c.get("vendor", ""),
                )
                for c in clients
            ),
            key=lambda c: (c.name or c.mac).lower(),
        )

    return _call(host, password, fetch)


def get_wifi_config(host: GlinetHost, password: str) -> list[GlinetWifiRadio]:
    def fetch(api_client) -> list[GlinetWifiRadio]:
        config = api_client.wifi.get_config()
        radios: list[GlinetWifiRadio] = []
        # Per-band configs live under a top-level "res" list, each with
        # its own "device" field -- not a dict keyed by device.
        for band_config in config.get("res") or []:
            device = band_config.get("device", "")
            for iface in band_config.get("ifaces", []) or []:
                radios.append(
                    GlinetWifiRadio(
                        device=device,
                        # The iface's own identifier is "name" (e.g.
                        # "default_radio0"), not "iface_name".
                        iface_name=iface.get("name", ""),
                        band=band_config.get("hwmode", ""),
                        ssid=iface.get("ssid", ""),
                        enabled=bool(iface.get("enabled", False)),
                    )
                )
        return radios

    return _call(host, password, fetch)


def set_wifi_config(
    host: GlinetHost,
    password: str,
    device: str,
    iface_name: str,
    ssid: str,
    key: str | None,
    enabled: bool,
) -> None:
    params = {"device": device, "iface_name": iface_name, "ssid": ssid, "enabled": enabled}
    if key:
        params["key"] = key

    def apply(api_client) -> None:
        api_client.wifi.set_config(params)

    _call(host, password, apply)


def reboot(host: GlinetHost, password: str, delay: int | None = None) -> None:
    def do_reboot(api_client) -> None:
        api_client.system.reboot({"delay": delay} if delay else None)

    _call(host, password, do_reboot)


def test_connection(host: GlinetHost, password: str) -> None:
    """Minimal call to validate a host/password without fetching real data
    — raises GlinetApiError on failure, returns nothing on success.
    """
    _call(host, password, lambda api_client: None)
