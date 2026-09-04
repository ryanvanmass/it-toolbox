# IT Toolbox

A cross-platform desktop app for connecting to Google Cloud infrastructure
without a public IP or VPN — starting with a GCP Identity-Aware Proxy (IAP)
connection manager for RDP, SSH, and Cloud Storage.

## Features

- **GCP project & instance browsing** — sign in with your Google account,
  pick which projects to show, and browse their Compute Engine instances
  in a sidebar tree.
- **RDP**, tunneled over IAP:
  - An embedded RDP client built on `libfreerdp3` via `ctypes` — renders
    the remote desktop directly in the app, with mouse/keyboard input and
    dynamic resolution resizing (resize the window, the remote desktop
    resizes with it). See `docs/embedded-rdp-status.md` for its current
    verification status.
  - Falls back to launching the OS's own client (`mstsc.exe`/`xfreerdp`)
    where the embedded path isn't available.
- **SSH**, tunneled over IAP, with an embedded terminal (`pyte` +
  `pywinpty`/`ptyprocess`).
- **GCS bucket browsing** per project, rclone-browser style.

## Requirements

- Python 3.11+
- A GCP project with IAP configured for the instances you want to reach
- **Windows only, for embedded RDP**: FreeRDP3 isn't available as an
  official prebuilt package there, so its DLLs need to be built once
  (via vcpkg) and made available to the app — see
  `docs/windows-freerdp-setup.md` for the full walkthrough. Everything
  else (GCP browsing, SSH, GCS) works without this.

## Getting started

```powershell
python -m venv .venv
.venv\Scripts\activate          # or: source .venv/bin/activate on Linux/macOS
pip install -e ".[dev]"
python -m it_toolbox
```

## Development

```bash
# Run the test suite (offscreen — no real window needed)
QT_QPA_PLATFORM=offscreen python -m pytest -q
```

Project layout:

- `core/` — Qt-free logic (IAP tunneling, session launching, the
  embedded RDP client's ctypes layer), independently testable/runnable
  without any UI.
- `widgets/` — the Qt-aware layer built on top of `core/`.
- `modules/` — top-level app features (currently: Connection Manager),
  each registered with the app shell in `modules/registry.py`.

See `docs/` for deeper write-ups of specific subsystems (currently:
the embedded RDP client's status and the Windows FreeRDP build steps).

## License

Apache License 2.0 — see [LICENSE](LICENSE).

The embedded RDP client links against FreeRDP, OpenSSL, zlib, and cJSON
at runtime; none of their licenses are copyleft or impose requirements
on this project's own licensing. See
[THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md) for the full attribution.
