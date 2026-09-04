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
- **Shell Launcher** — a separate module (no GCP account needed) that
  finds shells installed on the local machine (bash/zsh/fish/etc. on
  Linux/macOS; cmd, PowerShell, Git Bash, and installed WSL distros on
  Windows) and launches any of them in the same embedded terminal used
  for SSH.
- **Cloud Storage** — a separate module (no GCP account needed) that
  configures and browses `rclone` remotes: any of rclone's ~50 backend
  types (S3, SFTP, WebDAV, Google Drive, local, etc.), via a generic
  form built from rclone's own config schema rather than one form per
  backend. See `docs/cloud-storage-status.md` for its current
  verification status.

## Requirements

- Python 3.11+
- A GCP project with IAP configured for the instances you want to reach
- **Windows only, for embedded RDP**: FreeRDP3 isn't available as an
  official prebuilt package there, so its DLLs need to be built once
  (via vcpkg) and made available to the app — see
  `docs/windows-freerdp-setup.md` for the full walkthrough. Everything
  else (GCP browsing, SSH, GCS) works without this.
- **Cloud Storage module**: needs the `rclone` CLI on PATH — see
  [rclone.org/downloads](https://rclone.org/downloads/). Every other
  module works without it.
- **Linux only, for embedded QEMU/SPICE**: needs your distro's
  GObject-Introspection SPICE client library — there's no PyPI-installable
  equivalent, so it has to come from the system package manager (Fedora:
  `python3-gobject` + `spice-glib`; Debian/Ubuntu: `python3-gi` +
  `gir1.2-spice-client-glib-2.0`). Since that's a system package, your
  venv needs `include-system-site-packages = true` in its `pyvenv.cfg` to
  see it — either create the venv with `python -m venv --system-site-packages
  .venv`, or flip that line in an existing `.venv/pyvenv.cfg`. See
  `docs/qemu-spice-status.md` for the full plan and status.

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
- `modules/` — top-level app features (Connection Manager, Shell
  Launcher, Cloud Storage), each registered with the app shell in
  `modules/registry.py`.

See `docs/` for deeper write-ups of specific subsystems (currently:
the embedded RDP client's status and the Windows FreeRDP build steps).

## License

Apache License 2.0 — see [LICENSE](LICENSE).

The embedded RDP client links against FreeRDP, OpenSSL, zlib, and cJSON
at runtime; none of their licenses are copyleft or impose requirements
on this project's own licensing. See
[THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md) for the full attribution.
