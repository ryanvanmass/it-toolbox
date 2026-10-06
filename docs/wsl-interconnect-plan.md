# WSL interconnect — plan

Status: **planning only, nothing built yet.** Written against `main` at
`b72db35` (v0.3.9-beta.2). Read this first if you're picking the work up
in a new session; it follows the same handoff convention as the other
`docs/*-status.md` files.

## Goal

Let the Windows build use the features that are Linux-only today by
running the Linux half inside a WSL2 distro on the same machine, while
the Qt UI stays a normal Windows app. The user should see the same QEMU
tree, context menus and embedded SPICE tab they get on Linux, after a
one-time "Set up Linux tools" step in Settings.

The first consumer is QEMU/libvirt + SPICE, but more Linux-only tools
are planned, so the bridge is built as reusable infrastructure rather
than QEMU-specific glue.

## Decisions (2026-10-06)

1. **Dedicated, app-managed distro.** The app imports and owns its own
   WSL distro (`it-toolbox`) with every dependency preinstalled, built
   in CI. Users don't pick a distro or install packages.
2. **No stopgap viewer.** SPICE ships on Windows only once it's embedded.
   No WSLg `remote-viewer` window in between.
3. **Reusable first, QEMU/SPICE first.** The backend, distro and helper
   are generic, with a tool registry so future Linux tools plug in by
   adding a manifest entry (and, if they need a live stream, a helper
   service). QEMU/SPICE is the only consumer built in this plan.

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

Not in scope: `session_launcher._launch_rdp_linux` (`xfreerdp`
fallback, Windows already has its own path) and the Shell Launcher's
WSL entries (already work, via `wsl.exe -d <distro>`).

## Design overview

Four pieces, all generic, with QEMU/SPICE as the first user:

1. **Tool registry.** A declarative list of Linux tools (binaries,
   packages, which app features they gate). Drives the distro build, the
   availability checks, and Settings.
2. **`LinuxBackend`** (command bridge). One-shot CLI calls such as
   `virsh`/`virt-install` run natively on Linux and through
   `wsl.exe -d it-toolbox --exec` on Windows.
3. **Managed distro.** A minimal rootfs built in CI, downloaded and
   imported by the app on demand, versioned and replaceable.
4. **Helper services.** A headless Python process inside WSL hosting
   long-lived services that stream data to the Windows UI. The SPICE
   viewer is the first service; `SpiceWidget` itself doesn't change.

```
 Windows (native Qt app)                      WSL2 distro "it-toolbox"
 ─────────────────────────                    ───────────────────────────
 qemu_client.run_virsh ──► LinuxBackend ──►   wsl.exe --exec virsh -c URI …
 qemu_provisioning     ──►   (WslBackend)     wsl.exe --exec virt-install …

 SpiceWidget                                  python3 -m it_toolbox.wsl_helper
   └─ RemoteSpiceWorker ◄── TCP 127.0.0.1 ──►   └─ service "spice"
        same signals as                             ├─ QemuTunnel (ssh -L)
        SpiceSessionWorker                          └─ SpiceSession (spice-glib)
                                                          ▲
                                                          └─ VM's SPICE server
```

### 1. Tool registry

New module `core/linux_tools.py`:

```python
@dataclass(frozen=True)
class LinuxTool:
    id: str                    # "virsh", "virt-install", "spice"
    probe: tuple[str, ...]     # argv that must exit 0, e.g. ("virsh", "--version")
    packages: tuple[str, ...]  # Debian package names baked into the rootfs
    native_hint: str           # install hint shown on native Linux (today's text)
```

Initial entries: `virsh` (`libvirt-clients`), `virt-install`
(`virtinst`), `spice` (`python3-gi`, `gir1.2-spiceclientglib-2.0`,
probe `python3 -c "import gi; gi.require_version('SpiceClientGLib','2.0')"`),
`ssh` (`openssh-client`).

Uses:
- `is_tool_available(tool_id)` replaces the ad-hoc `shutil.which`
  checks in `qemu_client.is_available()` / `qemu_provisioning.is_available()`.
- The rootfs build (see 3) installs the union of every entry's
  `packages`, so adding a future tool is one entry plus a rebuild.
- Settings lists each tool's status from the same registry.

### 2. `LinuxBackend` (command bridge)

New module `core/linux_backend.py`:

- `LinuxBackend` protocol: `run(argv, *, timeout, input=None) ->
  CompletedProcess`, `probe(tool) -> bool`, `spawn(argv) -> Popen`
  (for helper services), `to_linux_path(windows_path)`, `description`.
- `NativeBackend`: today's behavior (`subprocess.run` / `shutil.which`).
  Used on Linux, so the Linux build is unchanged.
- `WslBackend`: `run` becomes
  `["wsl.exe", "-d", "it-toolbox", "--exec", *argv]` with
  `creationflags=CREATE_NO_WINDOW` (no console flash from a GUI-subsystem
  app). `--exec` (not a shell string) so VM names/URIs never need
  quoting.
- `get_backend()` picks: Linux → native; Windows → WSL if the managed
  distro is installed and at the expected version; otherwise `None`
  (features hidden, exactly as when `virsh` is missing today). macOS →
  `None` for now, but nothing here rules out a future Lima/VM backend.

Changes to existing code are small:

- `qemu_client.run_virsh` and `qemu_provisioning._run_virt_install` call
  `get_backend().run(...)` instead of `subprocess.run`.
- `VIRSH_TIMEOUT_SEC` (8 s) needs a first-call allowance: a stopped WSL
  distro takes a few seconds to boot. The backend pre-warms the distro
  in a worker thread at startup and gives the first call a longer
  timeout.

What the command bridge alone gets on Windows: the QEMU tree, VM power
actions, Reset, Deploy VM… (ISO picker, pools, networks, `--osinfo`
list), Configure… (resize, add disk).

### 3. Managed distro

**Build (CI).** `packaging/wsl/Containerfile` from `debian:trixie-slim`
(smallest image with every package we need in the main archive):

- `apt install` the union of the registry's `packages`, generated into
  the build from `core/linux_tools.py` so the two can't drift (a test
  asserts every registry package is in the image manifest).
- Unprivileged default user `toolbox`.
- `/etc/wsl.conf`: `[user] default=toolbox`, `[boot] systemd=false`
  (nothing here needs it, and it boots faster),
  `[interop] appendWindowsPath=false` (so a Windows `ssh.exe` or
  `python.exe` on PATH can never shadow the Linux one).
- `docker export` → `it-toolbox-wsl-<rootfs-version>.tar.gz`, plus a
  `.sha256`, published as a release asset by a new
  `.github/workflows/package-wsl.yml`. Rootfs versions are independent
  of app versions (`rootfs-N`), since the image only changes when the
  registry or base image does.

Expected size is roughly 100–200 MB compressed; measure in milestone 2.

**Install (app).** Downloaded on demand, not bundled in the installer
(same pattern as Settings' "Fetch FreeRDP DLLs"), so users who never
touch QEMU don't pay for it:

1. Check WSL itself (`wsl.exe --status`). If WSL isn't installed, say
   so and offer to run `wsl --install --no-distribution`, which needs
   admin and usually a reboot. Ask first; never run it silently.
2. Download the pinned rootfs (`WSL_ROOTFS_VERSION` constant in the app),
   verify the sha256.
3. `wsl --import it-toolbox "%LOCALAPPDATA%\IT Toolbox\wsl" <tarball> --version 2`.
4. Run every registry probe to confirm.

**Versioning.** The distro records its rootfs version in
`/etc/it-toolbox-rootfs`. If it doesn't match what the app expects
(app updated to one needing a new tool), Settings offers "Update Linux
tools", which unregisters and re-imports. That's safe because the
distro holds no user state the app can't regenerate (SSH material is
re-synced, see 5).

**Uninstall.** Inno Setup `[UninstallRun]`:
`wsl.exe --unregister it-toolbox`, and remove the `wsl` folder.

### 4. Helper services (viewer bridge)

**Helper process.** `it_toolbox/wsl_helper/` — a Qt-free entry point,
`python3 -m it_toolbox.wsl_helper <service> [args]`, with a small
service registry so future tools add a service module rather than a new
process type. The shared parts (handshake, framing, lifecycle) live in
`core/wsl/transport.py` and are used by both ends.

It runs under the distro's own `python3`, loading the package straight
from the Windows install via
`PYTHONPATH=<to_linux_path(install dir)>/Lib/site-packages`, so the
helper can never drift from the installed app version and the rootfs
never needs rebuilding for app-only changes. A test imports
`it_toolbox.wsl_helper` with PySide6 blocked, so a stray Qt import
fails CI rather than failing on a user's machine.

**Transport.** TCP on `127.0.0.1`. The helper listens on an ephemeral
port and prints `{"port": N, "token": "…"}` on stdout as its first line;
the Windows side connects and sends the token first. WSL2's default
`localhostForwarding` makes a WSL-side `127.0.0.1` listener reachable
from Windows. Why not the alternatives:

- `wsl.exe` stdio pipe: workable for control messages, but frame
  throughput through the `wsl.exe` relay is the bottleneck on a 1080p
  desktop. Keep stdio only for the handshake line and stderr logging.
- AF_UNIX across the boundary: only works for WSL1.
- Shared memory: no cross-VM shared memory with WSL2.

**Framing.** Length-prefixed messages: `u32 length, u8 type, payload`.
Message type numbers are per-service; the transport doesn't care what
they mean.

**SPICE service.** `wsl_helper/spice_service.py` imports only
`core/spice/spice_session.py`, `core/qemu_tunnel.py` and
`core/ssh_tunnel.py` (all Qt-free already). It owns the `qemu+ssh://`
tunnel too: running the tunnel on the Windows side would mean the WSL
helper has to reach Windows' loopback, which only works in WSL's
mirrored networking mode; doing it inside WSL works in both NAT and
mirrored mode.

One message type per signal `SpiceSessionWorker` already has, so the
Windows side is a mechanical port:

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
`SpiceSessionWorker`. It spawns the helper through
`LinuxBackend.spawn`, reads the handshake, connects, and runs a reader
thread that turns messages into signals. `SpiceWidget` gets its worker
from a small factory (`make_spice_worker(...)`), and
`connection_manager/ui/main_view.py`'s `SpiceWidget = None` import guard
is relaxed. Two concrete changes: `widgets/spice_widget.py` imports
`SpiceSessionWorker` (and so `gi`) at module level and constructs it
with `(host, port, password)` at line ~101, so the import moves into
the factory; and on Windows `main_view` must not open its own
`QemuTunnel` first, since the helper owns the tunnel, so the factory
takes the host URI + SPICE port and decides where the tunnel lives.

**Lifecycle.** Helper exits on `STOP`, on socket close, or when its
stdin closes (so a crashed app never leaves orphan helpers). The app's
existing `aboutToQuit` teardown calls `stop()` as it does for the local
worker.

### 5. SSH credentials inside the distro

`virsh -c qemu+ssh://…` and the helper's tunnel run inside the distro,
so they use the distro's `~/.ssh`, not the Windows user's. Since the app
owns the distro, it syncs this itself rather than asking the user: on
import and before each QEMU connection, copy `%USERPROFILE%\.ssh\id_*`
and `known_hosts` into `/home/toolbox/.ssh` with `0600` perms. (Pointing
at `/mnt/c/...` directly doesn't work, since DrvFs presents the keys as
`0777` and ssh refuses them.) Without `known_hosts`, the first `virsh`
call would stall on a host-key prompt it can't answer.

Keys held only in the Windows OpenSSH agent (no key file) aren't
covered by this. Bridging the agent (e.g. via `npiperelay`) is a later
add-on if it turns out to matter.

### 6. Settings

Replace the "Not applicable on this platform." branch of
`_build_qemu_section` on Windows with a generic **"Linux tools (WSL)"**
section, since it will serve more than QEMU:

- State: WSL missing / tools not installed / installed (rootfs-N) /
  update available.
- One button that does the right next step: "Install WSL…", "Set up
  Linux tools" (download + import, with a progress bar), or "Update
  Linux tools".
- Per-tool status from the registry (virsh, virt-install, SPICE, ssh).
- "Remove Linux tools" (unregister) for users who want the disk back.

The existing Linux-native QEMU section keeps its install hints, now
read from the registry's `native_hint`.

### 7. Local `qemu:///system` inside the distro

Not a target. The managed distro is a client environment; `qemu+ssh://`
to a real hypervisor is the supported path. A user running libvirtd on
the Windows machine itself is out of scope.

## Milestones

Each one is shippable on its own; Linux behavior stays unchanged
throughout.

1. **Tool registry + `LinuxBackend`.** Native + WSL backends, route
   `run_virsh`/`_run_virt_install` and the `is_available()` checks
   through them, unit tests with a fake `wsl.exe`. Linux tests must pass
   untouched.
2. **Rootfs build in CI.** `packaging/wsl/Containerfile`,
   `package-wsl.yml`, release asset + sha256, test that registry
   packages match the image.
3. **Distro manager + Settings section + SSH sync.** Download, verify,
   import, version check, update, remove. After this, the QEMU tree,
   power actions, Deploy VM and Configure VM work on Windows.
4. **Helper framework + SPICE service.** `core/wsl/transport.py`,
   `it_toolbox.wsl_helper`, tests that run the helper against a fake
   `SpiceSession` over a real socket (Linux CI can run both ends).
5. **`RemoteSpiceWorker` + widget factory.** Embedded SPICE on Windows.
   Verify on a real Windows machine against a real `qemu+ssh://` host,
   same bar as the other status docs (real VM, `grab()` diff, input
   round-trip).
6. **Packaging + docs.** Uninstaller unregisters the distro; add a
   section to `docs/windows-troubleshooting.md`; update README's
   feature/platform table; a short "adding a Linux tool" guide (registry
   entry, rebuild rootfs, optional helper service).

## Remaining open questions

- **Rootfs hosting.** GitHub release assets on `ryanvanmass/it-toolbox`
  are the default. If the image gets big or updates often, the Forgejo
  package registry is an alternative.
- **Agent-only SSH keys.** Only matters if keys live solely in the
  Windows agent; deferred until someone hits it.
