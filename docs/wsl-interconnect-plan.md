# WSL interconnect — plan

Status: **planning only, nothing built yet.** Written against `main` at
`b72db35` (v0.3.9-beta.2). Read this first if you're picking the work up
in a new session; it follows the same handoff convention as the other
`docs/*-status.md` files.

## Goal

Let the Windows build use the features that are Linux-only today by
running the Linux half inside a WSL2 distro on the same machine, while
the Qt UI stays a normal Windows app. The user should see the same QEMU
tree, context menus and embedded SPICE tab they get on Linux, with a
one-time "pick a WSL distro" setup step in Settings.

## What's Linux-only today

Everything below lives in Connection Manager's QEMU/libvirt family. The
rest of the app (GCP/IAP, SSH, embedded RDP, Cloud Storage/rclone, FTP,
GL.iNet, JumpCloud, Shell Launcher) already runs natively on Windows.

| Feature | Why it's Linux-only | Where |
|---|---|---|
| QEMU host/VM discovery + power actions | Shells out to `virsh`, which has no maintained Windows build | `modules/connection_manager/qemu_client.py` (`is_available`, `run_virsh`) |
| Deploy VM / Configure VM | Needs `virt-install` (Python + libosinfo, Linux packaging only) plus `virsh` | `modules/connection_manager/qemu_provisioning.py` |
| Embedded SPICE viewer | `spice-glib` via PyGObject/GI; `pyproject.toml` only installs `PyGObject` on Linux, and the GTK/MSYS2 stack on Windows was ruled out (`docs/qemu-spice-status.md`) | `core/spice/spice_session.py`, `core/spice/spice_session_worker.py`, `widgets/spice_widget.py` |
| Settings > "QEMU / libvirt" section | Hard-gated on `platform.system() != "Linux"` → "Not applicable on this platform." | `modules/settings/ui/main_view.py` `_build_qemu_section` |

`core/qemu_tunnel.py` (the `ssh -L` for `qemu+ssh://` SPICE ports) is
not itself Linux-only, since Windows ships OpenSSH, but it only exists
to feed the SPICE client, so it moves with SPICE (see below).

Things that are *not* in scope: `session_launcher._launch_rdp_linux`
(`xfreerdp` fallback, Windows already has its own path) and the Shell
Launcher's WSL entries (already work, via `wsl.exe -d <distro>`).

## Design overview

Two layers, because the two kinds of Linux-only code need very different
bridges:

1. **Command bridge** for `virsh`/`virt-install`. These are one-shot CLI
   calls that already go through a single subprocess chokepoint each, so
   on Windows they just get prefixed with `wsl.exe -d <distro> --exec`.
   Cheap, and it unlocks discovery, power actions, Deploy VM and
   Configure VM with no UI changes.
2. **SPICE helper** for the viewer. A small headless Python process runs
   *inside* WSL, drives the existing `SpiceSession` (which has no Qt
   import), and streams dirty-band frames out / input events in over a
   local socket. On Windows a drop-in replacement for `SpiceSessionWorker`
   speaks that protocol, so `SpiceWidget` itself doesn't change.

```
 Windows (native Qt app)                      WSL2 distro
 ─────────────────────────                    ───────────────────────────
 qemu_client.run_virsh ──► LinuxBackend ──►   wsl.exe --exec virsh -c URI …
 qemu_provisioning     ──►   (WslBackend)     wsl.exe --exec virt-install …

 SpiceWidget                                  it_toolbox_wsl_helper (python3)
   └─ RemoteSpiceWorker ◄── TCP 127.0.0.1 ──►   ├─ QemuTunnel (ssh -L, qemu+ssh)
        same signals as                         └─ SpiceSession (spice-glib)
        SpiceSessionWorker                            ▲
                                                      └─ VM's SPICE server
```

### 1. `LinuxBackend` abstraction (command bridge)

New module `core/linux_backend.py`:

- `LinuxBackend` protocol: `run(argv, *, timeout, input=None) ->
  CompletedProcess`, `which(cmd) -> bool`, `description` (for Settings).
- `NativeBackend`: today's behavior (`subprocess.run` / `shutil.which`).
  Used on Linux, so the Linux build is unchanged.
- `WslBackend(distro)`: `run` becomes
  `["wsl.exe", "-d", distro, "--exec", *argv]` with
  `creationflags=CREATE_NO_WINDOW` (no console flash from a GUI-subsystem
  app); `which` runs `wsl.exe -d distro --exec sh -c 'command -v "$1"' sh cmd`.
  `--exec` (not a shell string) so VM names/URIs never need quoting.
- `get_backend()` picks: Linux → native; Windows → WSL if a distro is
  configured in settings and reachable; otherwise `None` (feature hidden,
  exactly as when `virsh` is missing today). macOS → `None`.

Changes to existing code are small:

- `qemu_client.run_virsh` and `qemu_provisioning._run_virt_install` call
  `get_backend().run(...)` instead of `subprocess.run`.
- `qemu_client.is_available()` / `qemu_provisioning.is_available()` ask
  the backend.
- `VIRSH_TIMEOUT_SEC` (8 s) needs a first-call allowance: a stopped WSL
  distro takes a few seconds to boot. Pre-warm the distro in a worker
  thread at startup when the backend is WSL, and give the first call a
  longer timeout.

What this gets on Windows, with no other changes: the QEMU tree, VM
power actions, Reset, Deploy VM… (ISO picker, pools, networks,
`--osinfo` list), Configure… (resize, add disk).

### 2. SPICE helper (viewer bridge)

**Helper process.** `it_toolbox/wsl_helper/` — a Qt-free entry point
(`python3 -m it_toolbox.wsl_helper spice --uri … --vm … --port …`). It
imports only `core/spice/spice_session.py`, `core/qemu_tunnel.py` and
`core/ssh_tunnel.py` (all Qt-free already; verify that stays true with
a test that imports the helper with PySide6 blocked).

It runs under the distro's own `python3` with apt/dnf-provided
`python3-gi` + `gir1.2-spiceclientglib-2.0` (no pip, no venv), loading
the package straight from the Windows install via
`PYTHONPATH=/mnt/c/Program Files/IT Toolbox/Lib/site-packages`
(translated with `wslpath`). No copy step, so the helper can never drift
from the installed app version.

The helper owns the `qemu+ssh://` tunnel too. Running the tunnel on the
Windows side would mean the WSL helper has to reach Windows' loopback,
which only works in WSL's mirrored networking mode; doing it inside WSL
works in both NAT and mirrored mode.

**Transport.** TCP on `127.0.0.1`, helper listens on an ephemeral port
and prints `{"port": N, "token": "…"}` on stdout as its first line; the
Windows side connects and sends the token first. WSL2's default
`localhostForwarding` makes a WSL-side `127.0.0.1` listener reachable
from Windows. Why not the alternatives:

- `wsl.exe` stdio pipe: workable for control messages, but frame
  throughput through the `wsl.exe` relay is the bottleneck on a 1080p
  desktop. Keep stdio only for the handshake line and stderr logging.
- AF_UNIX across the boundary: only works for WSL1.
- Shared memory: no cross-VM shared memory with WSL2.

**Protocol.** Length-prefixed binary frames, one message type per signal
`SpiceSessionWorker` already has, so the Windows side is a mechanical
port:

| Direction | Message | Mirrors |
|---|---|---|
| helper → app | `FRAME(band_top, band_height, canvas_w, canvas_h, stride, pixels)` | `frame_ready` (already dirty-band based via `get_dirty_band`) |
| helper → app | `CONNECTED`, `AGENT_CONNECTED`, `DISCONNECTED`, `ERROR(msg)` | same-named signals |
| app → helper | `MOUSE_MOVE`, `MOUSE_BUTTON`, `MOUSE_WHEEL`, `KEY_SCANCODE`, `RESIZE`, `STOP` | `send_*` methods |

Pixels stay raw BGRX (already `QImage.Format_RGB32`-compatible, see
`docs/qemu-spice-status.md` milestone 4). Over loopback, a full 1080p
repaint is ~8 MB; that's fine at desktop-update rates. Add optional
`zlib`/LZ4 per band later only if measurement says so. Mouse-move
coalescing already exists in the worker; keep it on the Windows side so
the socket never carries more than the worker would have sent.

**Windows side.** `core/spice/remote_spice_worker.py`:
`RemoteSpiceWorker(QObject)` with the exact signal/method surface of
`SpiceSessionWorker`. It spawns the helper through `WslBackend`, reads
the handshake, connects, and runs a reader thread that turns messages
into signals. `SpiceWidget` gets its worker from a small factory
(`make_spice_worker(...)`), and `connection_manager/ui/main_view.py`'s
`SpiceWidget = None` import guard is relaxed. Two concrete changes:
`widgets/spice_widget.py` imports `SpiceSessionWorker` (and so `gi`) at
module level and constructs it with `(host, port, password)` at line
~101, so the import moves into the factory; and on Windows `main_view`
must not open its own `QemuTunnel` first, since the helper owns the
tunnel, so the factory takes the host URI + SPICE port and decides
where the tunnel lives.

**Lifecycle.** Helper exits on `STOP`, on socket close, or when its
stdin closes (so a crashed app never leaves orphan helpers). The app's
existing `aboutToQuit` teardown calls `stop()` as it does for the local
worker.

### 3. Setup and Settings

Replace the "Not applicable on this platform." branch of
`_build_qemu_section` on Windows with a "QEMU / libvirt (via WSL)"
section:

1. Distro picker, fed by `shell_discovery._discover_wsl_distros()`
   (already handles `wsl -l -q`'s UTF-16 output). Saved as
   `qemu_wsl_distro` in settings.
2. Dependency check, run inside the chosen distro: `virsh`,
   `virt-install`, `python3`, `python3 -c "import gi;
   gi.require_version('SpiceClientGLib', '2.0')"`, `ssh`. Each shows
   found / missing.
3. For anything missing, show the exact install command for the
   distro's package manager (detected from `/etc/os-release`), with a
   copy button, same tone as today's Linux hints:
   - Debian/Ubuntu: `sudo apt install libvirt-clients virtinst python3-gi gir1.2-spiceclientglib-2.0 openssh-client`
   - Fedora: `sudo dnf install libvirt-client virt-install python3-gobject spice-gtk`
   An "Open terminal in this distro" button reuses Shell Launcher's
   `wsl.exe -d <distro>` session so the user can paste it.

The app never runs `sudo`/root installs itself; that matches the
existing "it's a system package, not something this app can download"
stance.

### 4. SSH credentials inside WSL

`virsh -c qemu+ssh://…` and the helper's tunnel use WSL's `~/.ssh`, not
the Windows user's. Default: document it and add a Settings action
"Copy my Windows SSH key into WSL" that copies `%USERPROFILE%\.ssh\id_*`
into the distro's `~/.ssh` with `0600` perms (DrvFs mounts keys as
`0777`, which ssh refuses, so pointing at `/mnt/c/...` directly doesn't
work without the `metadata` mount option). Also copy `known_hosts`
entries for configured QEMU hosts so the first `virsh` call doesn't stall
on a host-key prompt it can't answer.

### 5. Local `qemu:///system` inside WSL

Works if the user runs libvirt inside WSL2 itself (nested KVM is
available on WSL2 with a recent kernel), but that's a power-user setup.
Treat `qemu+ssh://` to a real hypervisor as the main path and
`qemu:///system` in WSL as "supported if you set it up"; no
special-casing needed since `virsh` handles both.

## Milestones

Each one is shippable on its own; Linux behavior stays unchanged
throughout.

1. **`LinuxBackend` + command bridge.** Native + WSL backends, route
   `run_virsh`/`_run_virt_install` through it, unit tests with a fake
   `wsl.exe`. Linux tests must pass untouched.
2. **Settings section on Windows.** Distro picker, dependency check,
   install hints, SSH key copy. After this, the QEMU tree, power
   actions, Deploy VM and Configure VM work on Windows.
3. **Helper + protocol.** `it_toolbox.wsl_helper`, wire format, tests
   that run the helper against a fake `SpiceSession` over a real socket
   (Linux CI can run both ends).
4. **`RemoteSpiceWorker` + widget factory.** Embedded SPICE on Windows.
   Verify on a real Windows machine against a real `qemu+ssh://` host,
   same bar as the other status docs (real VM, `grab()` diff, input
   round-trip).
5. **Packaging + docs.** Installer ships nothing new for WSL (the helper
   is already in the wheel); add a section to
   `docs/windows-troubleshooting.md`, update README's feature/platform
   table.

## Open questions

- **Dedicated distro vs. the user's own.** This plan uses an existing
  distro the user picks. Alternative: ship a minimal rootfs built in CI
  and `wsl --import` it as `it-toolbox`, with every dependency
  preinstalled (zero setup, but a ~100–200 MB download and another
  release artifact). Recommendation: start with the user's distro; add
  the managed distro later only if setup friction shows up in practice.
- **WSLg as a fallback.** WSLg could show a Linux `remote-viewer`
  window with no helper at all. It isn't embedded, so it doesn't meet
  the original goal, but it would be a cheap stopgap between milestones
  2 and 4 if wanted.
- **Generalising the bridge.** Nothing else is Linux-only today, but
  the `LinuxBackend` seam is where any future Linux-only CLI tool
  (e.g. ZFS, cockpit-style system tooling) would plug in.
