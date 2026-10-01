# GL.iNet router dashboard — status and setup

Connection Manager's third connection family (alongside GCP and QEMU/
libvirt): manually-registered GL.iNet travel routers, each opening a
management dashboard tab (Overview/Clients/WiFi/VPN status/Reboot)
instead of a terminal or pixel-streamed session.

## Why `python-glinet` isn't bundled

The only maintained Python library for GL.iNet's firmware-4.0+ JSON-RPC
API is [`python-glinet`](https://github.com/tomtana/python-glinet)
(PyPI: `python-glinet`, import name `pyglinet`), which is **GPLv3+
licensed**. it-toolbox is Apache-2.0, and GPL's copyleft terms are
triggered by distribution — bundling `pyglinet` into an it-toolbox
release would force the whole combined work to be GPL-compatible.

Rather than relicense the project, `pyglinet` is treated as an
**optional, not-bundled runtime dependency** — the same pattern already
used for FreeRDP's native libraries (`core/rdp/freerdp_client.py`) and
SpiceWidget's PyGObject dependency (`widgets/spice_widget.py`), though
in those two cases the reason is packaging, not licensing. It is never
listed in `pyproject.toml` and never vendored; `glinet_client.py` only
imports it via `try: from pyglinet import GlInet; except ImportError:
GlInet = None`. If the import fails, GL.iNet dashboards are simply
unavailable (Settings shows "not installed", and opening a dashboard
shows a plain "not installed" message) — the rest of the app is
unaffected. it-toolbox itself never distributes GPL code; a user who
wants this feature installs it themselves:

```
pip install python-glinet
```

## v1 scope

- **Overview** — uptime, LAN IP, memory used, CPU temp, wireless/cable
  client counts (from a single `system.get_status()` call).
- **Clients** — connected devices (name, MAC, IP, online) from
  `clients.get_list()`.
- **WiFi** — a flat table (Network/Device/Band/SSID/Status, Main
  networks listed before Guest) matching the VPN tab's own format;
  double-click a row (or select + "Edit…") to change its SSID/password
  in a small dialog, via `wifi.get_config()`/`wifi.set_config()`.
- **VPN** — **read-only** list of configured tunnels (name, type,
  enabled/up status, routing criteria from/to/via, kill switch) via
  `list_vpn_tunnels()`. Adding, editing, or toggling VPN tunnels is out
  of scope for v1.
- **Reboot** — immediate reboot with a confirmation prompt.

Not in scope for v1: VPN tunnel configuration, full WiFi parameter
coverage (channel/tx power/hwmode), and caching a live session per host
(every dashboard action opens and closes its own `GlInet` session —
`keep_alive=False` throughout, so there's no background keep-alive
thread to manage).

## Field-mapping caveat

Exact JSON field names in `glinet_client.py` were originally best-effort
from `python-glinet`'s own README and bundled `api_description.json`
example output, then corrected against a real router (a GL-MT3000
"Berl AX") during manual testing:

- `system.get_status()`'s `wifi`, `service`, and `client` fields are
  **lists**, not dicts keyed by name (a service's status is looked up
  by its own `"name"` field) — the original dict assumption crashed
  outright (`'list' object has no attribute 'items'`).
- `wifi.get_config()`'s per-band configs live under a top-level `"res"`
  list, not directly on the result object; each band has *separate*
  `"band"` ("2G"/"5G") and `"hwmode"` ("11ac/ax") fields — easy to
  mix up, and a first fix did (showing hwmode as the WiFi tab's band
  label instead of "2G"/"5G").
- `system.get_status()`'s `uptime` is a raw (and, live, fractional)
  seconds count, not a display string — rendered via `_format_uptime()`.
- A WiFi radio's main and guest networks render as two separate
  `GlinetWifiRadio` entries with a `guest` field distinguishing them
  (present on both `system.get_status()`'s `wifi` list and
  `wifi.get_config()`'s per-iface objects) — the dashboard groups all
  Main networks together and all Guest networks together (not by
  physical radio), Main first.
- **VPN status needed a completely different module than the one
  first assumed.** `wg_client.get_status()`/`ovpn_client.get_status()`
  raise `MethodNotFoundError` outright on a router using GL.iNet's
  newer multi-tunnel "VPN Policy" feature — that firmware exposes VPN
  status through a `"vpn-client"` (**hyphenated**) module instead,
  confirmed via a HAR capture of the router's own web UI network
  traffic. `"vpn-client"` isn't in `pyglinet`'s bundled
  `api_description.json` at all, so there's no `api_client.*` wrapper
  for it — `list_vpn_tunnels()` reaches `api_client`'s private
  `_session` attribute (the real `GlInet` instance) to call
  `.request("call", ["vpn-client", "get_status", {}])` directly. Its
  response is a flat list of independently-named tunnels (e.g.
  "Bonkcloud"), each with its own `enabled`/`status` — a genuinely
  different shape from the classic single-tunnel model, which is why
  `GlinetOverview`'s four fixed `wg_client_up`/`wg_server_up`/
  `ovpn_client_up`/`ovpn_server_up` booleans were replaced with a
  `GlinetVpnTunnel` list from its own `list_vpn_tunnels()` call. The
  classic `wg_client`/`wg_server`/`ovpn_client`/`ovpn_server`
  `get_status()` endpoints are kept as a fallback (each surfaced as one
  fixed-name tunnel) for routers without the newer module.

If a field comes back missing or differently shaped than expected,
`glinet_client.py` is the file to check first; corrections should stay
isolated there rather than rippling into `models.py` or the UI.
`scripts/glinet_dump.py` is the diagnostic tool used to ground each of
the fixes above against a real router rather than guessing — reuse it
for the next one, extending it with more calls first if needed.

## Host passwords

Each registered host's password is encrypted to the user's SSH public
key (the same `age`/`pyrage` mechanism as the JumpCloud API key, see
`core/settings.py`'s `encrypt_glinet_password`/`decrypt_glinet_password`)
and stored alongside the rest of that host's record in
`glinet_hosts.json` — never in plaintext. Decryption only happens right
before a dashboard is opened, not when the host list is loaded, so
browsing the tree never triggers a passphrase prompt.
