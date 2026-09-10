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
- **WiFi** — view and edit SSID/password/enabled per radio/interface via
  `wifi.get_config()`/`wifi.set_config()`.
- **VPN** — **read-only** WireGuard/OpenVPN client+server up/down status
  (from the same `get_status()` call). Adding or editing VPN tunnel
  configs is out of scope for v1.
- **Reboot** — immediate reboot with a confirmation prompt.

Not in scope for v1: VPN tunnel configuration, full WiFi parameter
coverage (channel/tx power/hwmode), and caching a live session per host
(every dashboard action opens and closes its own `GlInet` session —
`keep_alive=False` throughout, so there's no background keep-alive
thread to manage).

## Field-mapping caveat

Exact JSON field names in `glinet_client.py` (the nested shape of
`system.get_status()`, `wifi.get_config()`'s per-band/iface structure,
etc.) are best-effort from `python-glinet`'s own README and bundled
`api_description.json` example output — not verified against a live
router. If a field comes back missing or differently shaped than
expected, that's the file to check first; it exists specifically so a
correction stays isolated there rather than rippling into `models.py` or
the UI.

## Host passwords

Each registered host's password is encrypted to the user's SSH public
key (the same `age`/`pyrage` mechanism as the JumpCloud API key, see
`core/settings.py`'s `encrypt_glinet_password`/`decrypt_glinet_password`)
and stored alongside the rest of that host's record in
`glinet_hosts.json` — never in plaintext. Decryption only happens right
before a dashboard is opened, not when the host list is loaded, so
browsing the tree never triggers a passphrase prompt.
