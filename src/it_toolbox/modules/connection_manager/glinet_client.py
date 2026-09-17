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
    GlinetVpnTunnel,
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
                guest=bool(radio.get("guest", False)),
            )
            for radio in wifi_list
        )

        return GlinetOverview(
            uptime=_format_uptime(system.get("uptime")),
            lan_ip=system.get("lan_ip", ""),
            memory_used_pct=_percent_used(system.get("memory_total"), system.get("memory_free")),
            cpu_temp=_as_float((system.get("cpu") or {}).get("temperature")),
            wireless_client_count=int(client.get("wireless_total", 0) or 0),
            cable_client_count=int(client.get("cable_total", 0) or 0),
            wifi_radios=radios,
        )

    return _call(host, password, fetch)


def list_vpn_tunnels(host: GlinetHost, password: str) -> list[GlinetVpnTunnel]:
    """VPN tunnels configured on this router.

    GL.iNet's newer firmware has a "VPN Policy" feature: any number of
    independently named tunnels (e.g. "Bonkcloud"), each wrapping a
    WireGuard/OpenVPN client or server config, each with its own
    on/off toggle and its own routing criteria (from/to/via/kill
    switch). This lives behind a "vpn-client" (hyphenated) RPC module
    confirmed via a real router's own web UI network capture -- it
    isn't in pyglinet's bundled api_description.json at all, so there's
    no api_client.vpn_client wrapper for it; reaching the session's own
    request() through api_client's private _session attribute is the
    only way to call it through this library. Two of its methods are
    combined here: get_tunnel() (the policy: name/enabled/from/to/via/
    killswitch) and get_status() (live connection status + peer_name),
    matched up by their shared tunnel_id.

    Falls back to the classic single-tunnel wg_client/wg_server/
    ovpn_client/ovpn_server endpoints (each surfaced as one fixed-name
    tunnel, with no routing-criteria info) for a router without this
    newer module -- get_tunnel()/get_status() for the whole "vpn-client"
    module raise outright (confirmed live) when it's absent, not just
    for one missing tunnel type.
    """

    def fetch(api_client) -> list[GlinetVpnTunnel]:
        try:
            tunnel_result = api_client._session.request(
                "call", ["vpn-client", "get_tunnel", {}]
            ).result
            status_result = api_client._session.request(
                "call", ["vpn-client", "get_status", {}]
            ).result
            status_by_tunnel_id = {
                entry.get("tunnel_id"): entry for entry in status_result.get("status_list") or []
            }
            return [
                GlinetVpnTunnel(
                    name=policy.get("name", ""),
                    type=(policy.get("via") or {}).get("type", ""),
                    enabled=bool(policy.get("enabled", False)),
                    up=status_by_tunnel_id.get(policy.get("tunnel_id"), {}).get("status") == 1,
                    from_summary=_format_vpn_from(policy.get("from") or {}),
                    to_summary=_format_vpn_to(policy.get("to") or {}),
                    via_summary=_vpn_via_summary(
                        api_client, policy.get("via") or {},
                        status_by_tunnel_id.get(policy.get("tunnel_id"), {}),
                    ),
                    killswitch=bool(policy.get("killswitch", False)),
                )
                # "tunnels" only -- "default_tunnels" is the router's own
                # built-in fallback policy (e.g. "last sort default
                # policy"), not a real named VPN tunnel an admin created.
                for policy in tunnel_result.get("tunnels") or []
            ]
        except Exception:  # noqa: BLE001 - fall back below; not every router has this module
            pass

        return [
            GlinetVpnTunnel(
                name=name, type=vpn_type,
                enabled=code not in (None, 0),
                up=code == 1,
            )
            for name, vpn_type, code in (
                ("WireGuard Client", "wireguard", _classic_vpn_status_code(api_client, "wg_client")),
                ("WireGuard Server", "wireguard", _classic_vpn_status_code(api_client, "wg_server")),
                ("OpenVPN Client", "openvpn", _classic_vpn_status_code(api_client, "ovpn_client")),
                ("OpenVPN Server", "openvpn", _classic_vpn_status_code(api_client, "ovpn_server")),
            )
        ]

    return _call(host, password, fetch)


def _format_vpn_from(from_obj: dict) -> str:
    """Matches the router's own web UI wording ("All Clients" / "1
    Connection Type") for a policy's traffic-source criteria."""
    if from_obj.get("type") == "interface":
        count = len(from_obj.get("interface_list") or [])
        return f"{count} connection type" + ("" if count == 1 else "s")
    return "All clients"


def _format_vpn_to(to_obj: dict) -> str:
    """Matches the router's own web UI wording ("All targets" / "3
    Addresses") for a policy's traffic-destination criteria."""
    if to_obj.get("type") == "domain":
        count = len([line for line in (to_obj.get("domain_list") or "").splitlines() if line.strip()])
        return f"{count} address" + ("" if count == 1 else "es")
    return "All targets"


def _vpn_via_summary(api_client, via: dict, status_entry: dict) -> str:
    """"<group name> / <peer name>", matching the router's own web UI
    (e.g. "Bonkcloud / WireGuard-Server-GLINet") -- peer_name comes from
    the matched get_status() entry; the group name needs its own lookup
    (wg_client/ovpn_client.get_group_list(), by the policy's group_id),
    which is best-effort: an older/different firmware might not expose
    it the same way, in which case the peer name alone is still useful.
    """
    peer_name = status_entry.get("peer_name", "")
    group_id = via.get("group_id")
    if group_id is None:
        return peer_name
    module_name = "wg_client" if via.get("type") == "wireguard" else "ovpn_client"
    try:
        groups = getattr(api_client, module_name).get_group_list().get("groups") or []
        group = next((g for g in groups if g.get("group_id") == group_id), None)
        group_name = group.get("group_name") if group else None
    except Exception:  # noqa: BLE001 - the peer name alone is still a useful fallback
        group_name = None
    if group_name and peer_name:
        return f"{group_name} / {peer_name}"
    return group_name or peer_name


def _classic_vpn_status_code(api_client, module_name: str) -> int | None:
    """Real per-tunnel VPN status code, from that VPN type's own
    dedicated get_status() call (wg_client/wg_server/ovpn_client/
    ovpn_server each have one, per pyglinet's bundled
    api_description.json) -- fallback path for a router without the
    newer "vpn-client" module (see list_vpn_tunnels). Confirmed against
    a real router that system.get_status()'s generic "service" list is
    NOT a substitute for this: it only reports whether a global service
    feature is present/enabled at all, and omitted "wgclient"/
    "ovpnclient" entirely even with an active, connected WireGuard
    client tunnel configured.

    wg_server's status lives one level deeper, under "server", unlike
    the other three. Calling get_status() for a VPN type not supported
    by this firmware, or with no tunnel/config set up, raises rather
    than returning a clean "not configured" result.

    status: 0 not enabled | 1 connected successfully | 2 enabled but
    connection not successful.
    """
    try:
        result = getattr(api_client, module_name).get_status()
    except Exception:  # noqa: BLE001 - "not configured"/"not supported" is expected, not a failure
        return None
    if module_name == "wg_server":
        result = result.get("server") or {}
    return result.get("status")


def _as_single_dict(value) -> dict:
    """system.get_status()'s "client" field is documented as a single
    object but the API's own bundled example response wraps it in a
    one-item list -- handle either shape rather than trust one over the
    other."""
    if isinstance(value, list):
        return value[0] if value else {}
    return value or {}


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
                        # "band" ("2G"/"5G") is a separate field from
                        # "hwmode" ("11ac/ax", the PHY standard) -- easy
                        # to mix up since they sit right next to each
                        # other in the response; this is the one meant
                        # for display as the radio's band.
                        band=band_config.get("band", ""),
                        ssid=iface.get("ssid", ""),
                        enabled=bool(iface.get("enabled", False)),
                        guest=bool(iface.get("guest", False)),
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
