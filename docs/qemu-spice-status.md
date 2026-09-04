# QEMU/libvirt hosts + embedded SPICE client — status and handoff

Branch: `feature/qemu-spice-connections`. Read this file first if you're
picking this work up in a new session (e.g. on a different machine) —
it's written so a fresh session with no prior conversation history can
get oriented from the repo alone. Milestones 1-4 (below) are done and
verified against a real libvirt/QEMU host; the rest is still the
original plan.

## What this branch is

Connection Manager currently supports one connection "family": GCP
(project → instances → RDP/SSH via IAP tunnel). This branch adds a
second, independent family: QEMU/libvirt hosts → VMs → an **embedded**
SPICE client (not an external `virt-viewer` launch — the point is
embedding, matching how RDP moved from external `mstsc.exe` to an
embedded `RdpWidget` on `feature/embedded-rdp-libfreerdp`).

**Linux-only, by explicit user decision.** SPICE has no native Qt
widget; the standard client library (`spice-gtk`/
`libspice-client-glib-2.0`) is GObject-based and normally driven from
Python via PyGObject/GObject-Introspection — well-supported on Linux
(same stack behind virt-manager/GNOME Boxes), but Windows support would
mean fighting an MSYS2/GTK runtime stack on top of what FreeRDP already
required. That fight was explicitly ruled out.

**Reuse source**: [ryanvanmass/virt-connect](https://github.com/ryanvanmass/virt-connect)
(PyQt6, external `virt-viewer` launcher) already solves VM *discovery*
— `virsh_client.py`'s `list_vms()`/`power_action()` shell out to
`virsh -c {uri} ...` and regex-parse the output; `config.py` stores
hosts as `{"name": ..., "uri": ...}` JSON. That logic ports over almost
directly (adapted to this project's dataclass/error conventions, not
copy-pasted as-is — different UI framework and module layout). What it
does **not** have, because it delegates the whole connection to
`virt-viewer`, is anything for actually rendering a SPICE session —
that's the new work here, and it mirrors the embedded-RDP architecture
closely enough to use as a template throughout.

## What's done and verified (Milestones 1-4)

All of this has been tested against a real local libvirt/QEMU host
(`qemu:///system`, a running VM called "WorkPC") — not mocked, not just
checked against docs:

1. **VM discovery** (`modules/connection_manager/qemu_client.py`:
   `list_vms`/`get_vm_spice_port`/`power_action`, all via `virsh`).
   Confirmed listing a real running VM and parsing its SPICE port
   straight out of `dumpxml`, matching the raw XML.
2. **SSH tunnel** (`core/qemu_tunnel.py`: `QemuTunnel`). Verified against
   a real (throwaway, non-privileged, no sudo) local `sshd` instance: a
   real `ssh -L` subprocess forwarding a real TCP connection end-to-end.
3. **SPICE connect/disconnect** (`core/spice/spice_session.py`:
   `SpiceSession.connect`/`disconnect`). Verified against the real VM's
   SPICE server: a real connect + main-channel-open + clean disconnect,
   and a real connect-failure path against a closed port.
4. **Frame capture** (`SpiceSession.get_frame`/`on_frame`,
   `capture_one_frame`). Pixel format confirmed empirically, not
   assumed: SPICE surface format 32 is BGRX byte order, byte-for-byte
   matching `QImage.Format_RGB32` (same as FreeRDP) — confirmed by
   diffing a captured frame against `virsh screenshot`'s independent
   capture, 0 pixels different across a full-frame sample with real
   (non-black) content. Two binding quirks found the hard way, not from
   docs: (a) both `Session` and every `Channel` subclass have native
   `connect()`/`disconnect()` methods that shadow GObject's signal
   `.connect()` — signals must be wired via
   `GObject.Object.connect(obj, signal, cb)` instead; (b)
   `DisplayChannel.display_channel_get_primary()` (the "pull" API)
   returns garbage/misaligned fields through this binding, so frame data
   is cached from the `display-primary-create` *signal* instead. Also
   found: capturing on the very first `on_frame` call can grab a
   still-blank/stale surface before the guest's display has actually
   woken up — fixed with the same "wait for a settle period with no new
   frames" approach `freerdp_client.capture_one_frame` already used.

See the git log on this branch for the full detail behind each of these.

## Environment note — updated

The original plan (below) was written on a Windows dev machine with no
Linux box, no libvirt/QEMU host, and no way to install PyGObject/
spice-glib to test against. That gap is now closed: PyGObject/spice-glib
were already present as system (rpm) packages, made importable in the
project's venv via `include-system-site-packages = true` in
`.venv/pyvenv.cfg` (see the README's Requirements section) rather than a
from-source pip build, since the devel headers for that aren't installed
and there's no need to fight that when the distro package already works.
Milestones 5-7 below still need the same "verify against a real target"
treatment as 1-4 got.

## Architecture — mirrors the embedded-RDP three-layer split

| RDP (existing, reference — see `docs/embedded-rdp-status.md`) | QEMU/SPICE (new, this branch) |
|---|---|
| `core/rdp/freerdp_client.py` (Qt-free, ctypes) | `core/spice/spice_session.py` (Qt-free, PyGObject) |
| `core/rdp/rdp_session_worker.py` (thread + Qt signal bridge) | `core/spice/spice_session_worker.py` (same shape) |
| `widgets/rdp_widget.py` (paints `QImage` from raw GDI buffer) | `widgets/spice_widget.py` (paints `QImage` from raw SPICE buffer) |
| `core/iap_tunnel.py` + `tunnel_session.py` (tunnel before connecting) | `core/qemu_tunnel.py` (SSH local port-forward before connecting) |
| `modules/connection_manager/gcp_client.py` | `modules/connection_manager/qemu_client.py` |

### Why this shape works for SPICE specifically

Verified via the actual `SpiceClientGLib` GObject-Introspection docs
(not just recalled from memory — see
<https://lazka.github.io/pgi-docs/SpiceClientGLib-2.0/>):

- `DisplayChannel` signals `display-primary-create` (format/width/
  height/stride/imgdata) and `display-invalidate` (x/y/w/h region
  updates) give raw pixel-buffer access directly — no GTK widget needed
  at all. This is a closer match to `QImage`-painting than FreeRDP's
  GDI hook was; `SpiceClientGtk.Display` (the GTK *widget*) can be
  skipped entirely, sidestepping the X11-XID-embedding-in-Qt /
  Wayland-breakage problem completely.
- `InputsChannel` methods (`motion`, `position`, `button_press`/
  `release`, `key_press`/`release`, `key_press_and_release`) are a
  near-exact match for what `FreeRdpSession.send_mouse_*`/`send_key_*`
  already do — scancode-based like RDP's `scancodes.py` table (PC/AT
  set 1; 0xe0-prefixed codes drop the prefix and OR `0x100` instead of
  a separate extended flag).
- PyGObject's signal callbacks fire on whatever thread runs the GLib
  main loop — so `spice_session_worker.py` just runs
  `GLib.MainLoop().run()` on its own background thread (own loop, not
  integrated into Qt's), exactly parallel to how
  `RdpSessionWorker._run()` drives `pump_once()` on its own thread. No
  GTK/Qt event-loop integration needed anywhere.

### The one genuinely new piece: an SSH tunnel before connecting

libvirt-managed VMs conventionally bind their SPICE server to
`127.0.0.1` on the host (secure default) — `virt-viewer`/`virsh` reach
it because *they* set up the tunnel transparently as part of the
`qemu+ssh://` connection dance. Since this project's embedded client
connects to the SPICE port directly (bypassing virt-viewer entirely),
it needs to open that tunnel itself: `ssh -L
<local_port>:127.0.0.1:<remote_spice_port> <user>@<host> -N`, spawned
as a subprocess — the same "spawn `ssh`, respect the user's existing
keys/agent" pattern `session_launcher.py` already uses for the SSH
connection type, just held open as a tunnel instead of an interactive
session (closer in spirit to `BackgroundTunnel`, but subprocess-based,
not asyncio/websocket-based like the IAP tunnel is).

Note: discovery/management calls (`virsh -c qemu+ssh://... list --all`,
`dumpxml`, power actions) do **not** need this tunnel — `virsh` itself
shells out to `ssh` transparently as part of libvirt's own `qemu+ssh`
transport. The tunnel is only needed for the actual SPICE pixel/input
stream, which our own PyGObject client drives directly.

## Concrete file plan

**New:**
- `modules/connection_manager/qemu_client.py` — `list_vms(host) ->
  list[QemuVm]` (port of virt-connect's `virsh -c {uri} list --all` +
  regex parse), `get_vm_spice_port(host, vm_name) -> int | None`
  (**new**, not in virt-connect since it never needed raw port info —
  `virsh -c {uri} dumpxml {vm}`, parse the `<graphics type='spice'
  port='...'>` element via `xml.etree.ElementTree`),
  `power_action(host, vm_name, action)` (port of virt-connect's
  pause/resume/start/shutdown). All via `subprocess.run(["virsh", "-c",
  uri, ...], timeout=8, ...)`, raising a new `QemuApiError`, following
  `gcp_client.py`'s per-function conventions.
- `core/qemu_tunnel.py` — Qt-free SSH local-port-forward tunnel,
  parsing the target user@host out of a `qemu+ssh://` URI.
- `core/spice/spice_session.py` — Qt-free `SpiceSession`:
  `connect(host, port, password)`, `on_frame` callback + `get_frame()`,
  `send_mouse_move/button/wheel`, `send_key_press/release`. PyGObject
  (`gi.repository.SpiceClientGLib`), not ctypes — much gentler FFI than
  the FreeRDP work since GObject introspection handles
  marshaling/signal-connection for us.
- `core/spice/spice_session_worker.py` — thread + `QObject`/`Signal`
  bridge, same shape as `core/rdp/rdp_session_worker.py`.
- `widgets/spice_widget.py` — `QWidget` mirroring `RdpWidget`:
  `paintEvent` draws a `QImage` from the raw buffer (pixel format needs
  empirical confirmation once testable — likely a BGRX/ARGB variant,
  same kind of "pick a format that lines up byte-for-byte with
  `QImage.Format_RGB32`" step FreeRDP needed), mouse/key handlers call
  the worker, same `finished`/`close_session()` convention.
- `modules/connection_manager/ui/manage_hosts_dialog.py` — CRUD dialog
  (name + URI, add/edit/remove), unlike `ProjectSelectionDialog`'s
  checkbox-filter-over-pre-fetched-list shape — mirrors virt-connect's
  "Add host" flow since there's no account-based discovery of QEMU
  hosts, the user just registers them.

**Modified:**
- `modules/connection_manager/models.py` — add `QemuHost(name: str,
  uri: str)`, `QemuVm(id: str, name: str, state: str)`.
- `core/settings.py` — add `qemu_hosts_path()` / `load_qemu_hosts()` /
  `save_qemu_hosts()`, same flat-JSON convention as
  `selected_projects.json`.
- `modules/connection_manager/ui/main_view.py` — generalize the tree
  from its current single hardcoded `"GCP"` root to support a second
  `"QEMU"` root (new `IS_QEMU_ROOT_ROLE`/`HOST_ID_ROLE`/`VM_ROLE`
  item-data roles alongside the existing ones); host nodes with
  lazy-loaded VM children (mirrors `CATEGORY_VMS`'s lazy-expand
  pattern); context menu additions ("Connect via SPICE", and — since
  virt-connect treats this as core functionality and the reuse ask
  implies matching scope — Pause/Resume/Start/Shutdown via
  `qemu_client.power_action`); a "Manage Hosts…" entry opening the new
  dialog; connect flow `_connect_qemu(...)` → `QemuTunnel` →
  `_embed_spice(...)`, registered in the same `_active_sessions`/
  `_session_tab_widgets` dicts as RDP/SSH so it participates in the
  existing teardown sweep (`_on_disconnect_requested`,
  `_stop_all_sessions`) without new bookkeeping.
- `pyproject.toml` — add `PyGObject; sys_platform == 'linux'` (mirrors
  the existing `pywinpty; sys_platform == 'win32'` / `ptyprocess;
  sys_platform != 'win32'` conditional-dependency pattern). Document
  the system packages needed too (`python3-gi`, the distro's
  `spice-glib`/`gir1.2-spice-client-glib-2.0` package) — there's no
  PyPI-installable equivalent, same "not everything is pip install"
  situation FreeRDP was, but far less severe (no vcpkg/compiler saga
  expected — these are normal, commonly-packaged Linux libraries, not
  something needing a from-source build).

## Suggested milestones

Mirrors how the RDP branch's commit history was structured — that
worked well: small, independently-verifiable steps, each committed once
proven against a real target, not a single giant unverified change.

1. `qemu_client.py` — list/dumpxml/power-action via `virsh`, verified
   against a real libvirt host. Qt-free, CLI-testable, no
   PyGObject/SPICE involved yet.
2. `core/qemu_tunnel.py` — verify a local SSH port-forward actually
   reaches a VM's SPICE port.
3. `spice_session.py` connect/disconnect smoke test (mirrors
   `connect_and_disconnect`) against the real VM.
4. Frame capture — raw pixels via `display-primary-create`/
   `display-invalidate`, saved to a test image (mirrors
   `capture_one_frame`), confirms the pixel format hypothesis.
5. `SpiceWidget` rendering live in Qt (mirrors RDP Milestone 3).
6. Input — mouse/keyboard via `InputsChannel` (mirrors RDP Milestone 4).
7. `main_view.py` wiring: tree UI, manage-hosts dialog, connect flow,
   session lifecycle, power actions.

## How to pick this up

1. `git checkout feature/qemu-spice-connections`, `git pull`.
2. Confirm PyGObject + the SPICE GObject-Introspection typelib are
   installed (`python3 -c "import gi; gi.require_version('SpiceClientGLib',
   '2.0'); from gi.repository import SpiceClientGLib"` should succeed) —
   package names vary by distro (Fedora: `python3-gobject` +
   `spice-glib`; Debian/Ubuntu: `python3-gi` +
   `gir1.2-spice-client-glib-2.0`).
3. Confirm `virsh` can reach a real libvirt host:
   `virsh -c qemu+ssh://<user>@<host>/system list --all`.
4. Start at Milestone 1 above.

## Verification

No automated test can cover the SPICE protocol/rendering pieces (same
as `core/rdp/` — needs a live target); `qemu_client.py`'s `virsh`
wrapping is more testable in isolation. End-to-end: a real libvirt host
reachable via `qemu+ssh://`, with at least one VM running, to connect
the embedded client to and visually confirm rendering + input
round-trip (same methodology as the RDP work: screenshot the widget,
drive real input, verify the *server* actually reacted — not just that
a local call returned success, which is exactly the class of
false-positive the RDP work hit more than once).
