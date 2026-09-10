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

Exact response field names below (system.get_status()'s nested shape,
wifi.get_config()'s per-band/iface structure, etc.) are best-effort from
pyglinet's own README/bundled api_description.json example output, not
verified against a live router — see the small parsing helpers in each
function here, which exist specifically so a later field-name correction
stays isolated to this file.
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
        wifi = status.get("wifi", {})
        service = status.get("service", {})
        client = status.get("client", {})

        radios = tuple(
            GlinetWifiRadio(
                device=name,
                iface_name=radio.get("iface_name", name),
                band=radio.get("band", ""),
                ssid=radio.get("ssid", ""),
                enabled=bool(radio.get("up", False)),
            )
            for name, radio in wifi.items()
        )

        return GlinetOverview(
            uptime=str(system.get("uptime", "")),
            lan_ip=system.get("lan_ip", ""),
            memory_used_pct=_percent_used(system.get("memory")),
            cpu_temp=_as_float(system.get("cpu_temp")),
            wireless_client_count=int(client.get("wireless_total", 0) or 0),
            cable_client_count=int(client.get("cable_total", 0) or 0),
            wifi_radios=radios,
            wg_client_up=bool((service.get("wg_client") or {}).get("up", False)),
            wg_server_up=bool((service.get("wg_server") or {}).get("up", False)),
            ovpn_client_up=bool((service.get("ovpn_client") or {}).get("up", False)),
            ovpn_server_up=bool((service.get("ovpn_server") or {}).get("up", False)),
        )

    return _call(host, password, fetch)


def _percent_used(memory: dict | None) -> float | None:
    if not memory:
        return None
    total = memory.get("total")
    free = memory.get("free")
    if not total:
        return None
    return round((1 - free / total) * 100, 1) if free is not None else None


def _as_float(value) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


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
        for device, band_config in config.items():
            for iface in band_config.get("ifaces", []) or []:
                radios.append(
                    GlinetWifiRadio(
                        device=device,
                        iface_name=iface.get("iface_name", ""),
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
