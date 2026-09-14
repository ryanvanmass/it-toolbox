# QEMU VM deployment + configuration — status and handoff

Branch: `feature/qemu-vm-provisioning`. Read this file first if you're
picking this work up in a new session — written so a fresh session with
no prior conversation history can get oriented from the repo alone.
Both milestones are done, verified against a real libvirt/QEMU host,
and wired into the real app.

## What this branch is

Connection Manager's existing QEMU/libvirt support
(`feature/qemu-spice-connections`, see `docs/qemu-spice-status.md`) only
lets you *view* a VM that already exists: discover it (`virsh list`),
control its power state, and connect via an embedded SPICE viewer.
There was no way to actually create a VM, or change one's resources
afterward — every VM had to already exist, made by something outside
this app. This branch adds that:

- **Deploy a VM** ("Deploy VM…" on a QEMU host's context menu) —
  provisions a new VM's disk/RAM/vCPUs/network on that host and
  optionally attaches an existing ISO (from that host's own storage) as
  install media.
- **Configure a VM** ("Configure…" on a stopped VM's context menu) —
  resize vCPUs/memory and/or add a new disk.

**Deliberately does not automate the OS install.** A newly deployed VM
either boots straight into its attached ISO's installer, or (with no
ISO chosen) boots its own fresh, empty disk directly — either way, the
user finishes the install (or just uses the VM, if it booted something
already usable) through the *existing* embedded SPICE viewer. No
cloud-init/unattended-install pipeline was built here — see "Deferred"
below.

## What's done and verified (both milestones)

All of this was tested against a real, disposable local libvirt/QEMU
host (nested KVM, `qemu:///system`, on the project's own dev VM) — not
mocked-only, not just checked against `virt-install --help`/man pages.

1. **Backend** (`modules/connection_manager/qemu_provisioning.py`,
   sibling to the existing `qemu_client.py`, which keeps its original
   discovery/power scope untouched — `qemu_client._run_virsh` was
   renamed to the now-public `run_virsh` so both files share the same
   subprocess chokepoint). `list_storage_pools`/`list_networks`/
   `list_volumes` (all `virsh`), `create_vm` (`virt-install`),
   `resize_vm`/`add_disk`/`get_vm_resources` (all `virsh`). Every
   output-parsing regex is grounded in real captured `pool-list`/
   `net-list`/`vol-list`/`domblklist`/`dumpxml` output, not assumed.

   Two real findings from that verification, both load-bearing (the
   original plan got them wrong before testing corrected it):
   - **`virt-install` refuses to create a domain at all without an
     explicit install method** — `"An install method must be
     specified (--location URL, --cdrom CD/ISO, --pxe, --import, --boot
     hd|cdrom|...)"`. There is no "just create a blank VM" option. A
     spec with no ISO chosen passes `--import` (boot the fresh disk
     directly) rather than simply omitting `--cdrom`.
   - **Disk target naming (`hda`/`hdb` vs `vda`/`vdb`) is whatever
     virt-install/the guest defaulted to**, not something this project
     picks. `add_disk` reads the VM's current targets via
     `domblklist` and continues whatever scheme is already there
     (increments the trailing letter of the existing prefix) rather
     than assuming one.

   Also confirmed live: `setvcpus --config --maximum` *and*
   `--config` are both required to actually change the current vCPU
   allocation (`--maximum` alone doesn't); `setmaxmem --config` +
   `setmem --config` likewise for memory; `virsh dumpxml`'s
   `<currentMemory>` always normalizes to KiB regardless of how a VM
   was originally defined.

2. **Full real end-to-end run, twice** — once interactively while
   designing the backend (a real `virt-install` VM creation with an
   attached ISO, confirmed it starts installing and is reachable via
   the existing SPICE viewer's own `get_vm_spice_port`; a real
   `resize_vm`+`add_disk` cycle against a stopped VM, confirmed via
   `dumpxml`/`domblklist`), and again at the very end running the
   *actual shipped* `qemu_provisioning.py` module's own functions
   directly (not hand-typed `virsh`/`virt-install` commands) against
   the same real host: `create_vm` → `qemu_client.list_vms` sees it →
   `get_vm_resources` → `resize_vm` → `add_disk` → `domblklist` shows
   both disks. All real, all cleaned up afterward.

3. **UI** (`ui/create_vm_dialog.py`'s `CreateVmDialog`, `ui/
   configure_vm_dialog.py`'s `ConfigureVmDialog`, wired into
   `ui/main_view.py`). `CreateVmDialog` async-loads pools/networks/
   ISO-suffixed volumes the same way the tree's own lazy VM loading
   already does, disabling its OK button until the pool/network lists
   land. The VM's own disk and its ISO install media each get their
   *own* storage-pool combo (added per feedback after the first cut) --
   changing the ISO pool only reloads the ISO volume list, it has no
   effect on where the disk itself is created. Both the ISO and OS
   variant combos are searchable (`QComboBox` + `QCompleter`,
   `MatchContains` so typing matches anywhere in the string, not just a
   prefix -- factored into one shared `_make_searchable` helper) with a
   widened popup and a full-path tooltip per ISO entry, since a real
   ISO library turned out to make a plain non-searchable dropdown
   genuinely unusable (found from an actual screenshot of a real,
   populated library -- truncated, un-searchable names in a long list
   with many similar entries). Both fields also start genuinely blank
   (placeholder text only, no item pre-selected) rather than defaulting
   to a specific entry -- confirmed live that an editable combo with no
   exact-matching text reports `currentIndex() == -1` and
   `currentData() == None`, which already means exactly the right thing
   for both fields (an empty OS variant falls back to `"generic"` at
   submit time; an empty ISO choice already means "no media"), so this
   needed no extra state to track, just not pre-selecting anything.
   OS variant is backed by a new `qemu_provisioning.list_os_variants()`
   -- confirmed live this is a purely local `virt-install --osinfo
   list` lookup (~940 entries, `"generic"` included), not something
   that varies per libvirt host,
   so it takes no `QemuHost`/`--connect` and loads once regardless of
   which host is being deployed to. `ConfigureVmDialog` pre-fills
   vCPU/memory from a fresh
   `get_vm_resources` call and only calls `resize_vm`/`add_disk` for
   whichever fields actually changed. Found and fixed a real, pre-
   existing gap in `main_view.py` while wiring this in: right-clicking
   a bare QEMU *host* node (not the "QEMU" root, not a VM) previously
   showed no context menu at all — that's exactly where "Deploy VM…"
   belongs, so this branch's own host-node context-menu branch fixes
   it rather than adding a separate workaround. "Configure…" is only
   offered on a VM whose state isn't `"running"` — `resize_vm`'s own
   `--config`-only calls are the backend's defense in depth for that
   same rule, the menu gating is the first line of it.

   **Per-host defaults** (added per feedback): `QemuHost` gained seven
   new optional fields (memory/vCPUs/disk size/disk pool/network/ISO
   pool/OS variant), all `None` by default -- editable from "Manage
   Hosts…"'s existing edit dialog (plain number/text fields, matching
   that dialog's own always-synchronous, no-live-discovery style rather
   than adding an async pool/network fetch just to edit a host's saved
   config) and persisted in the same `qemu_hosts.json` shape
   `settings.load_qemu_hosts`/`save_qemu_hosts` already used.
   `CreateVmDialog` seeds its spinboxes and OS-variant field directly
   from whatever the host has configured (falling back to the original
   plain hardcoded values -- 2048 MiB/2 vCPUs/20 GiB/blank -- for a host
   with nothing set), and selects the matching disk/ISO-pool/network
   combo entries by name once the real lists load. A stale or typo'd
   default (the named pool got renamed or removed since it was
   configured) is matched via `QComboBox.findData()`, which just
   returns -1 and leaves the combo on its normal first-item default --
   no error, no special-casing needed for that case.

   **Editing an existing VM's config** (added per feedback --
   `ConfigureVmDialog` now covers disks, CD-ROM media, and network, not
   just vCPU/memory/add-disk): a Disks section lists every disk via the
   new `list_disks` (`domblklist --details`, which is what actually
   distinguishes a `disk` device from a `cdrom` one -- plain
   `domblklist` doesn't have a type column at all) with a "Remove
   Selected Disk" action (`QMessageBox.question` confirm, matching this
   project's existing GCP power-action convention) that calls the new
   `remove_disk` -- `detach-disk --config --persistent`, confirmed live
   this only drops the disk from the VM's config and leaves the
   underlying volume file alone (checked via `vol-list` before/after,
   so the file isn't silently deleted). A CD-ROM section (shown only if
   the VM actually has a cdrom device -- a VM created via the `--import`
   path with no ISO at deploy time has none at all) lets the admin swap
   or eject media via the new `change_cdrom_media`. A Network section
   (shown only for a VM with exactly one interface -- multi-NIC VMs are
   deferred, see below) lets the admin pick a different virtual network
   via the new `change_network`, skipping the detach/reattach entirely
   when the chosen network is unchanged from the VM's current one.
   Every section is built as its own `QGroupBox`, shown/hidden wholesale
   rather than just disabling fields, so an inapplicable section doesn't
   clutter the dialog. Nothing is sent to the backend until "OK" --
   vCPU/memory changes, disk removals, add-disk, media changes, and
   network changes are all computed first and only executed inside one
   background-thread closure on accept, the same "edit in memory, only
   persist on close" shape `ManageHostsDialog` already uses.

   Two more real findings from live testing, both load-bearing:
   - **A VM's CD-ROM media can get auto-ejected as a side effect of the
     VM being stopped/destroyed** (confirmed live, reproducible) --
     `ConfigureVmDialog` always reads the VM's current CD-ROM state
     fresh when it opens rather than assuming it matches whatever was
     last set.
   - **`change-media --insert` fails ("already has media") if the drive
     already has something in it, and `--eject` fails ("doesn't have
     media") if it's already empty** -- there's no single "just replace
     it" command. `change_cdrom_media` always ejects first, tolerating
     specifically the "doesn't have media" error as a no-op, then
     inserts the new path only if one was requested:
     ```python
     def change_cdrom_media(host, vm_name, target, iso_path):
         try:
             run_virsh(host, "change-media", vm_name, target, "--eject", "--config")
         except QemuApiError as e:
             if "doesn't have media" not in str(e):
                 raise
         if iso_path is not None:
             run_virsh(host, "change-media", vm_name, target, "--insert", iso_path, "--config")
     ```

   **A more significant bug, found by this dialog's own test suite, not
   by inspection**: `QComboBox.currentData()` does *not* reflect an
   exact typed match unless the item was actually chosen via the
   completer's popup, or via an explicit `setCurrentIndex()` call.
   Typing an exact, valid name by hand and just moving on (or, in a
   test, calling `setCurrentText()`) leaves `currentIndex()`/
   `currentData()` completely unchanged -- confirmed with a standalone
   offscreen-Qt script, not just asserted from a failing test. This
   silently treats a real user's typed choice as "nothing selected."
   **It affected both dialogs that use a searchable combo for a
   data-backed choice** -- `ConfigureVmDialog`'s new CD-ROM ISO field,
   and `CreateVmDialog`'s existing ISO field (already shipped in this
   same PR before this bug was found -- the OS-variant field is
   unaffected, since it already uses `.currentText()` directly, valid
   for any typed string). Fixed by extracting the searchable-combo
   wiring out of `create_vm_dialog.py`'s old private `_make_searchable`
   into a new shared module, `ui/searchable_combo.py`, adding
   `resolve_data(combo)` there (`findText` + `itemData`, an exact-text
   lookup rather than trusting `currentData()`), and switching both
   dialogs' ISO fields to call it. Regression-tested directly in a new
   `test_searchable_combo.py` (asserts `currentData()` really does stay
   `None` after `setCurrentText()`, and that `resolve_data()` still
   finds the right value) plus a new case in `test_create_vm_dialog.py`.

4. **Settings** (`modules/settings/ui/main_view.py`'s QEMU/libvirt
   section) now separately reports `virt-install`'s own availability,
   since a `virsh`-only install (just `libvirt-clients`, no
   `virtinst`/`virt-install`) leaves VM discovery/power control working
   fine while "Deploy VM…" still needs the separate package.

5. **Tests**: `test_qemu_provisioning.py` (27 tests, real captured
   output as fixtures — parsers, argv construction, the `--import`-
   vs-`--cdrom` branching, the real `"An install method must be
   specified"` error text, and the `change_cdrom_media` eject-first/
   tolerate-already-empty/reraise-unrelated-errors logic),
   `test_create_vm_dialog.py` (including the per-host-defaults cases and
   a `resolve_data` regression case), `test_configure_vm_dialog.py`
   (rewritten for the disk/CD-ROM/network sections — visibility gating,
   defaults, remove-disk confirm/decline, change-media insert/eject,
   change-network actual-change-vs-no-op), `test_manage_hosts_dialog.py`
   (3, the defaults form), `test_searchable_combo.py` (new — 4 tests,
   including the `resolve_data`/`currentData()` regression case), plus
   context-menu-wiring tests in `test_main_view_sessions.py` and two
   new Settings-section tests. Dialogs are tested directly (constructed
   + `qtbot.addWidget` + `.show()`, not `.exec()`'d modally) — the same
   pattern already established by `test_add_remote_dialog.py`/
   `test_api_key_dialog.py` for this project's other async-loading
   dialogs. One real bug caught immediately by this: `QWidget.isVisible()`
   is always `False` for a widget inside a `QDialog` that was never
   actually shown on screen, regardless of what `setVisible()` was last
   called with — fixed by calling `dialog.show()` in the test fixture,
   not by changing the dialog code (the code was already correct; the
   *test* was checking the wrong thing). Full suite: 573 passed, the
   same 8 pre-existing,
   unrelated (headless-environment focus/clipboard) failures already
   present on the base branch, confirmed by running them there too.

6. **Embedded SPICE viewer performance** (picked up in this branch on
   request, not part of the original deploy/configure scope --
   `core/spice/spice_session_worker.py` predates this branch, from the
   already-merged `feature/qemu-spice-connections`): fixed a real
   choppy-display cause. `SpiceSession.get_frame()` does a full
   `ctypes.string_at()` copy of the *entire* framebuffer, and
   `spice_session_worker.py`'s `_on_frame` used to call it on every
   single `display-invalidate` signal with no throttling at all --
   `display-invalidate`'s own `x`/`y`/`width`/`height` args (the actual
   dirty rect) were never even used. A busy guest desktop (video,
   scrolling, animation) can fire that signal far faster than any
   display needs, each one forcing a full multi-megabyte copy plus a
   full Qt repaint downstream -- confirmed by reading `get_frame()`'s
   implementation directly, not assumed from a symptom report alone.

   **First pass — a capture-rate throttle.** Added a trailing-edge
   throttle in `SpiceSessionWorker._on_frame`, capped to a target
   framerate (`_TARGET_FRAME_INTERVAL_SEC`) -- an invalidate within the
   current interval just schedules one `GLib.timeout_add` for whenever
   the interval actually elapses (further invalidates before it fires
   are free, guarded by `_frame_timeout_pending`) rather than capturing
   again immediately. Because everything runs on the same GLib loop
   thread there's no locking needed. `_emit_frame` also tolerates
   `SpiceError` from the capture call (the primary surface can be torn
   down between the invalidate that scheduled a timeout and the timeout
   actually firing, e.g. a guest resolution change or disconnect
   mid-burst) rather than letting an unhandled exception reach the GLib
   loop.

   **This wasn't enough** -- reported still choppy specifically when
   dragging a window, which pointed at the other half of the same root
   cause the throttle didn't touch: every *accepted* capture was still
   re-copying and re-painting the **entire** display, even though a
   window drag only ever changes a limited band of the screen. Fixed
   properly with dirty-row tracking: `SpiceSession` now accumulates the
   union of every `display-invalidate`'s row range (not the full
   x/y/width/height rect -- the framebuffer is row-major/stride-
   contiguous, so clipping columns too would need per-row slicing for a
   much smaller extra win than clipping rows already gives) via a new
   `get_dirty_band()`, returning only the rows that actually changed
   since the last call instead of `get_frame()`'s always-everything copy.
   `SpiceSessionWorker` calls this instead, and `frame_ready` now
   carries `(pixels, band_top, band_height, canvas_width, canvas_height,
   stride)` rather than a full frame every time. `SpiceWidget` was
   restructured around this: instead of wrapping each incoming frame's
   bytes directly as a fresh `QImage` (only possible when every delivery
   was the whole picture), it now keeps a persistent `_canvas` `QImage`
   and composites each incoming band onto it at the right y-offset via
   `QPainter.drawImage(0, band_top, band_image)`, then calls
   `self.update(rect)` with only the corresponding (scaled)
   widget-space rect -- and `paintEvent` now respects `event.rect()`
   instead of unconditionally blitting the whole widget, so Qt's own
   compositor does proportionally less work the smaller the change was.
   With this in place, a higher target framerate became affordable too
   (bumped `_TARGET_FRAME_INTERVAL_SEC` from 30fps to 60fps) since each
   individual frame is now cheap when only a small area changed, instead
   of the throttle being load-bearing on its own to keep the full-frame
   cost down.

   **Verification** (this module has never had, and still doesn't have,
   automated pytest coverage -- see `qemu-spice-status.md`'s own
   "no automated test can cover the SPICE protocol/rendering pieces"
   note, still true here): verified live on the dev VM in three ways.
   First, a standalone script drove the throttle logic against the
   *real* `gi.repository.GLib.MainLoop`/`GLib.timeout_add` (the actual
   dependency this code relies on, not a mock) with a simulated ~450/sec
   invalidate burst — collapsed to 17 real captures over the burst
   window, with the final captured value confirmed to be the *last*
   one generated (proving the trailing invalidate is never dropped), and
   a second scenario confirmed a torn-down primary surface during a
   pending timeout raises no exception. Second, an actual end-to-end run
   against a real running VM's real SPICE server (before the dirty-row
   work) confirmed the throttle alone is a no-op under normal/idle
   usage — a real low-frequency invalidate stream (a boot-screen blink)
   passed through 1:1 with zero added latency. Third, after the
   dirty-row rework: connected to a real VM early during its UEFI boot
   (`--boot uefi`, the `edk2`/`UefiShell.iso` already on the host) to
   catch its genuinely scrolling boot text -- captured 69 real bands
   over 4 seconds, 68 of them partial-height (ranging from a
   full-frame's 800 rows down to bands as small as 11-15 rows), then
   composited them exactly the way `SpiceWidget` now does and compared
   the result **pixel-for-pixel against `virsh screenshot`'s
   independent capture** once the display settled -- 0 mismatches
   across a full sampled sweep, confirming the row-range copy/offset/
   stride math (and the widget's compositing) is correct, not just
   crash-free. (Getting a genuinely busy real *desktop* -- actual
   window-drag/video content, not boot text -- to stress-test against
   directly wasn't set up, given the effort a full guest OS install
   would take vs. the mechanism already being proven correct against
   real partial-row invalidates of varying, genuinely small sizes; the
   compositing code has no notion of "a window" vs. "boot text", only
   rows.)

   **A real crash found only by actually connecting** (this sandbox has
   no libvirt/spice-glib, so the dirty-band work above was verified
   without ever going through `SpiceWidget`'s own real Qt paint cycle --
   this is exactly the gap that let it through): `paintEvent`'s
   `painter.drawImage(dest, self._canvas, src)` passed a `QRect` target
   (`event.rect()`) alongside a `QRectF` source -- PySide6's overload
   resolution rejects that *mixed* pairing with a `ValueError` even
   though `QRectF | QRect` is individually a documented-acceptable type
   for each parameter on its own. Because nothing then called
   `painter.end()` on the widget's own `QPainter` (the exception skipped
   right past it), Qt's backing store was left with an active painter,
   and the whole process **segfaulted** the moment Qt tried to end the
   paint cycle itself -- not just a caught exception, a hard crash.
   Fixed by promoting `dest` to `QRectF` before the call (matching
   source and target types) and wrapping both this and the equivalent
   `_on_frame_ready` compositing call in `try/finally: painter.end()`,
   so a future mistake here fails as a normal Python exception instead
   of taking the whole app down. Verified two ways since this sandbox
   still can't run a real SPICE session: reproduced the *exact* original
   `ValueError` (byte-for-byte identical message) in a standalone
   `QPainter`/`QImage` script, confirmed the fix resolves it, then drove
   the real `SpiceWidget._on_frame_ready` (worker mocked out, everything
   else real) through both a full-frame and a small partial-band update
   under offscreen Qt (`QT_QPA_PLATFORM=offscreen`) with no crash.

   **The choppiness itself turned out to have nothing to do with any of
   the above.** After the crash fix, reported still choppy specifically
   while dragging a window. Diagnostic back-and-forth ruled out several
   plausible causes one at a time, each backed by a real check rather
   than assumption: CPU usage on both the it-toolbox process and
   qemu-kvm stayed flat during a drag (rules out a compute-bound cost on
   either side); the cursor itself stayed smooth while only the display
   *content* stuttered (rules out a general input/tunnel-latency
   problem, since the cursor needs no network round trip); and,
   decisively, `virt-viewer` against the exact same VM over the exact
   same network path was reported "crystal clear" and smooth, which
   rules out the SSH tunnel/network being bandwidth- or latency-bound
   (a real client on the identical path wouldn't be unaffected by that).
   That last fact also ruled out a client-side compression/color-depth
   tweak that was investigated and measured (0% bandwidth difference
   for a `color-depth=16` hint on real captured traffic -- see git
   history for that dead end) and a speculative mouse-move-forwarding
   GIL-contention fix (also shipped as a real, low-risk improvement,
   but never confirmed to be the actual cause).

   The real cause, once "crystal clear in virt-viewer" was reported: a
   report that the SPICE view looked visibly *blurry* on completely
   static content pointed away from a timing/performance bug entirely
   and toward a rendering-quality one. `SpiceWidget`'s `paintEvent`
   stretched `self._canvas` to fill `self.rect()` outright -- and
   `main_view.py` embeds this widget straight into a `QTabWidget`, which
   stretches it to whatever size the tab area happens to be, unrelated
   to the guest's actual resolution/aspect ratio (confirmed: the tab
   size and the VM's resolution were confirmed mismatched). Stretching a
   mismatched-aspect-ratio image outright distorts it, and `drawImage()`
   defaults to nearest-neighbor scaling, which looks blocky/aliased for
   any non-exact-pixel-match scale. `virt-viewer` doesn't hit either
   problem because it sizes its own window to the guest instead of the
   reverse. **`RdpWidget` had already solved this exact problem** (see
   its own `paintEvent`/`_scaled_image_rect`/`_remote_pos`, predating
   this branch) -- ported the identical pattern to `SpiceWidget`:
   `_scaled_canvas_rect()` computes the largest centered rect that fits
   the canvas at its native aspect ratio (letterboxed with black bars
   rather than stretched), `paintEvent` fills the letterbox bars and
   only enables `QPainter.RenderHint.SmoothPixmapTransform` when actually
   scaling (skipped for an exact 1:1 draw, matching `RdpWidget`'s own
   "only worth the cost when actually scaling" reasoning), and
   `_remote_pos` maps and clamps pointer coordinates through the same
   letterboxed rect so a click in the bars doesn't map to a
   nonsensical remote position. `_dirty_widget_rect` was updated the
   same way so partial-band updates still map to the correct letterboxed
   sub-rect. Verified offscreen: full-frame and partial-band paints both
   still succeed with no crash, the letterboxed rect's aspect ratio
   matches the canvas's to within rounding, and pointer mapping at the
   widget center and at a letterboxed corner both land in-bounds and in
   the expected place.

   This is worth flagging explicitly for whoever picks this up next:
   several real, verified, low-risk improvements shipped in this round
   (the capture throttle, the dirty-row/partial-repaint rework, the
   mouse-move coalescing) and none of them were the actual fix for what
   was reported -- the actual fix was a rendering-quality bug, not a
   performance one, and it only became findable once "blurry, not just
   slow" was reported and "crystal clear in virt-viewer" ruled out the
   network/tunnel entirely. The earlier throttle/dirty-row work isn't
   wasted (it's still a real fix for the real inefficiency it targeted,
   e.g. a genuinely busy guest desktop would still benefit), but it
   evidently wasn't what was making this specific VM's session feel
   choppy.

   **Closed out**: after the letterbox fix, a follow-up report of "still
   a little off" (both blurry text and visible distortion) needed real
   numbers rather than another guess, since aspect-ratio-preserving
   letterboxing should make geometric distortion mathematically
   impossible. Added a temporary on-screen diagnostic HUD (widget size,
   canvas size, computed letterbox target, `devicePixelRatio`) rather
   than asking for an external measurement tool, got back real numbers
   (`widget=1564x930 canvas=1920x1080 target=1564x879 @ (0,25)
   devicePixelRatio=1.00`), and checked them by hand: target aspect
   ratio 1564/879 = 1.7793 vs. canvas's 1920/1080 = 1.7778, a ~0.08%
   difference from integer rounding, and the letterbox y-offset
   (930-879)//2 = 25 matches exactly -- confirming the scaling math has
   no bug at all. The remaining softness is the unavoidable cost of
   *downscaling* a 1920x1080 desktop into a smaller (1564x930) display
   area (~0.81x) -- any interpolation method loses real pixel
   information at that ratio; it's not something more code can fix.
   `virt-viewer`'s crispness on the same VM comes specifically from not
   doing this at all (it resizes its own window to the guest's actual
   resolution instead of shrinking the guest into a fixed window). Given
   the choice between lowering the VM's resolution, enlarging the
   it-toolbox window, or accepting the current tradeoff, the answer was
   to leave it as-is -- this is a real, understood, and accepted
   limitation, not an open bug. The diagnostic HUD was removed once this
   was confirmed.

7. **Guest auto-resize via spice-vdagent** (a real enhancement, not a
   fix for anything broken -- suggested once the downscaling tradeoff
   above was understood): `SpiceWidget` now asks the guest to resize its
   own display to match the widget whenever a resize settles, the same
   mechanism `virt-viewer` itself uses to avoid needing to scale at all.
   New `SpiceSession.request_resize(width, height)` calls
   `MainChannel.update_display(0, 0, 0, width, height, True)` then
   `MainChannel.send_monitor_config()` -- but only after
   `MainChannel.agent_test_capability(_VD_AGENT_CAP_MONITORS_CONFIG)`
   confirms the connected agent actually supports it, silently doing
   nothing otherwise (most guests without `spice-vdagent` installed) --
   this is purely additive, the letterbox/scale path above keeps working
   unchanged for any guest that doesn't support resize.
   `_VD_AGENT_CAP_MONITORS_CONFIG = 1` is the raw bit position from
   spice-protocol's `spice/vd_agent.h` `enum { VD_AGENT_CAP_MOUSE_STATE =
   0, VD_AGENT_CAP_MONITORS_CONFIG, ... }` -- confirmed against the real
   installed header (`dnf install spice-protocol` on the dev VM), not
   recalled from memory, since spice-glib's own GObject-Introspection
   typelib doesn't expose these as a proper enum (they're plain C
   constants, not GEnum values). `SpiceWidget.resizeEvent` debounces
   (500ms of quiet before actually calling `send_resize`) so a live
   window/tab resize drag doesn't flood the agent with a request per
   pixel; `_on_connected` also (re)starts the same debounce, since this
   widget is constructed *before* being added to its tab (see
   `main_view._embed_spice`) and so may still be sitting at a default,
   not-yet-real size whenever the connection itself happens to complete
   -- whichever settles last (the tab layout or the connection) is what
   actually gets requested.

   **Verification**: the exact real spice-glib method signatures
   (`update_display` takes 6 args beyond `self` -- id, x, y, width,
   height, update; `send_monitor_config` takes none;
   `agent_test_capability` takes one, the capability bit) were confirmed
   by deliberately calling each with zero arguments against the real
   typelib and reading the resulting `TypeError`'s reported argument
   count -- the same technique that found the `QPainter.drawImage`
   overload bug earlier in this branch, applied here to avoid guessing
   at a C API's Python argument order from memory. The debounce/
   coalescing logic was verified via an offscreen-Qt test: three rapid
   resizes collapsed into exactly one `send_resize` call, using the
   *final* settled size, not an intermediate one. `request_resize()`
   was also run against a real connection to a real (agent-less) VM to
   confirm the `agent_test_capability` call itself doesn't raise and
   correctly no-ops rather than crashing. **Not verified**: whether a
   real guest with `spice-vdagent` actually installed resizes in
   response to this -- that needs a full graphical OS install (not the
   bare `--import`/UEFI-shell throwaway VMs used elsewhere in this
   branch), which wasn't done given the size of that lift relative to
   this feature; the API surface and argument correctness are confirmed,
   but the very last link (does a real vdagent actually act on it) is
   not.

8. **Fixed: couldn't connect to a QEMU host running on the same machine
   as it-toolbox** -- a real bug report, not a follow-on enhancement.
   `_connect_qemu` unconditionally built a `QemuTunnel`, and
   `QemuTunnel`/`_parse_ssh_target` unconditionally require a
   `qemu+ssh://` URI, raising `"not an SSH-transport libvirt URI"` for
   anything else -- including a perfectly valid local libvirt connection
   (`qemu:///system`), which every single test/verification in this
   branch so far had sidestepped by always using a *remote* dev VM
   reached over `qemu+ssh://`. A `QemuHost` pointed at the same machine
   running it-toolbox -- a completely normal, real setup, just never
   exercised -- could never connect via SPICE at all.

   Fixed with a new `qemu_tunnel.is_local_uri(uri)` (true for a bare
   `qemu:///system`/`qemu:///session`, no host component at all) and a
   restructured `_prepare_qemu_spice_connection(host, vm)` (renamed from
   `_start_qemu_tunnel`) that returns `(tunnel, port)` -- `tunnel` is
   `None` for a local URI, since libvirt already runs on this same
   machine and its SPICE port (bound to `127.0.0.1` same as ever) is
   therefore already directly reachable with no SSH forwarding needed at
   all. `_on_qemu_spice_connection_ready` (renamed from
   `_on_qemu_tunnel_ready`) only registers an `_active_sessions` entry
   when there actually is a tunnel to stop later -- a local session's
   disconnect has nothing to tear down beyond the `SpiceWidget` itself,
   and the existing disconnect/stop-all paths already tolerate a missing
   entry, so no other change was needed there.

   **Verified live**, reproducing the exact reported scenario: rather
   than treating the dev VM as a remote host again, this time its *own*
   local libvirt was the target -- `qemu:///system` from a script running
   *on* that machine, exactly mirroring "libvirt and it-toolbox on the
   same box". Confirmed `is_local_uri("qemu:///system")` is `True`,
   confirmed the real (unmodified) `get_vm_spice_port()` still resolves a
   real VM's port fine over a local URI, and confirmed a real
   `SpiceSession` connects successfully straight to `127.0.0.1:<port>`
   with zero tunnel involved -- exactly the code path
   `_prepare_qemu_spice_connection`'s `(None, port)` result leads to.

9. **Fixed a real race in guest auto-resize (section 7 above)**: reported
   that a VM with a working agent (auto-resize confirmed working for the
   same VM in `virt-viewer`) still wasn't resizing through this app.
   First ruled out the obvious mix-up -- `qemu-guest-agent` (host/guest
   management commands) and `spice-vdagent`/"SPICE Guest Tools" (SPICE
   display/clipboard/cursor integration) are two entirely separate
   packages despite the easily-confused names -- but the VM in question
   turned out to have something resize-capable actually connected
   (confirmed indirectly: `virt-viewer` resizing it at all requires that),
   which pointed at a real bug in this code, not a missing guest package.

   The bug: `request_resize()`'s `agent_test_capability()` check was only
   ever attempted *once* -- whenever a resize settled (500ms after the
   widget resizes, or once after connecting) -- with no way to retry.
   Confirmed live that `MainChannel`'s own `agent-connected` property
   starts `False` and only flips `True` once the agent's handshake with
   the server actually completes, which is a real, separate, *later*
   event than the SPICE connection itself coming up -- the guest OS has
   to start the agent service, which doesn't happen instantly on boot.
   A resize attempted before that flip (entirely plausible given the
   500ms window) would see `agent_test_capability()` return `False`
   (correctly, at that moment) and never be retried once the agent
   actually finished connecting moments later -- exactly matching
   "works in virt-viewer" (which reacts to this properly) vs. "doesn't
   work here" (which didn't retry at all).

   Fixed by hooking `notify::agent-connected` on the main channel (a new
   `SpiceSession.on_agent_connected` callback, threaded through
   `SpiceSessionWorker`'s new `agent_connected` signal to a new
   `SpiceWidget._on_agent_connected`), which re-sends a resize request
   using the widget's current size the moment the agent actually becomes
   ready -- not tied to a resize event at all, so it catches the case
   where the widget's size was already settled well before the agent
   finished connecting.

   **Verified live**: confirmed `MainChannel` really does expose an
   `agent-connected` boolean property (`list_properties()` against the
   real typelib) and that `notify::agent-connected` hooks and fires
   without error against a real connection (0 times for a real VM with
   no agent at all -- correctly never spuriously fired). Could not
   reproduce the actual becomes-connected transition itself without a
   full agent-equipped guest OS (same limitation as section 7's own
   verification gap), but the offscreen widget-level wiring was verified
   directly: calling `_on_agent_connected()` sends exactly one resize
   request using the widget's current size, independent of any resize
   event having fired at all.

10. **Configure… now works for a running VM too, not just a stopped
    one** -- reported as a bug ("running VMs have no configure option"),
    but the real answer turned out to need real, per-operation
    verification, not just removing the menu's `vm.state != "running"`
    check. Confirmed live, on a real running VM, what each operation
    actually does:
    - **vCPU/memory resize**: always `--config`-only, unconditionally --
      confirmed live that a real vCPU *reduction* is flatly rejected as
      a live change for a normally-provisioned VM ("failed to find
      appropriate hotpluggable vcpus"), and that `--config` alone on a
      running VM succeeds but has zero live effect (confirmed via
      `vcpucount`). `ConfigureVmDialog` shows a plain note ("applies the
      next time this VM restarts") rather than pretending otherwise.
    - **Add disk**: hot-attaches reliably when running, but only because
      `add_disk(live=True)` forces the new disk onto an explicit virtio
      target/bus (`--targetbus virtio`) -- a real, load-bearing
      correction to an earlier, incomplete finding in this same round:
      continuing whatever scheme the VM's *existing* disks use (the
      original, still-default behavior when not live) produces another
      IDE target for a VM whose boot disk is IDE, which is virt-install's
      own default for a plain `"generic"` os-variant -- i.e. this app's
      own common case. IDE disks flatly refuse to hotplug at all, and
      the *entire* `attach-disk` call then fails outright, not just its
      live half (nothing gets persisted either). Forcing virtio for the
      new disk specifically works regardless of the boot disk's own bus
      (mixing an IDE boot disk with virtio data disks is a normal, valid,
      confirmed-working QEMU/libvirt configuration) -- no UI caveat
      needed, since the fix is unconditional inside `add_disk` itself.
    - **Remove disk / change network**: `live=True` adds an explicit
      `--live` flag, but confirmed live this is genuinely unreliable --
      `virsh` reports success immediately (`"Disk detached
      successfully"` / `"Interface detached successfully"`) while the
      old device was still fully present several seconds later, since
      hot-*removal* (unlike hot-*add*) needs the guest OS to actually
      acknowledge releasing the device, which a real driver may or may
      not do promptly. The *new* interface in a network change still
      attaches immediately and reliably either way. `ConfigureVmDialog`
      shows an explicit warning for both rather than promising immediate
      completion.
    - **CD-ROM media**: reliably immediate when running, via the same
      `--live` flag added to `change_cdrom_media` -- confirmed live that
      eject and insert both take effect right away with no guest
      cooperation needed (a much simpler operation than a full PCI
      device hot-unplug). No caveat needed.

    The "Configure…" context-menu action is now always offered,
    regardless of `vm.state`.

    **Verification**: every finding above came from live testing against
    real running VMs on the dev VM, in the exact sequence discovered
    (including a real self-correction mid-round: `add_disk` was first
    reported as "already works live, no change needed" based on a test
    that manually forced a virtio target rather than exercising the
    actual `_next_disk_target` scheme-continuation logic a real
    `create_vm()`-created VM would produce -- re-tested against an
    actual `create_vm()`-created VM with its real IDE boot disk once
    that gap was noticed, which is what surfaced the real bug). 20 new/
    updated tests across `test_qemu_provisioning.py` (new
    `_next_virtio_disk_target` tests, `add_disk(live=True)`'s forced
    virtio target/bus) and `test_configure_vm_dialog.py` (every backend
    call site updated for its new `live` kwarg, plus new running-VM
    tests confirming `live=True` is passed through correctly for each
    operation).

## Deferred (explicitly out of scope for this branch)

Cloud-init/unattended install, uploading local media from the
it-toolbox machine to the libvirt host (media has to already be on the
host, discovered via `list_volumes`), multi-NIC network editing
(`ConfigureVmDialog`'s Network section only shows for a VM with exactly
one interface — adding/removing NICs, or picking which one to change on
a multi-NIC VM, is deferred), boot-order changes, snapshot support, and
*automatic* OS-variant detection from the chosen ISO/image (the OS
variant combo is a full, real, searchable list of every valid value —
added after the first cut, see above — but nothing inspects the
attached media to guess which one applies; the admin still picks it,
defaulting to `generic`). Disk removal, CD-ROM media management, and
single-NIC network changes on an existing VM — originally deferred here
— were added in a later round (see `ConfigureVmDialog` above), and
editing a *running* VM's resources (also originally deferred here) was
added in a further round after that (see section 10 below) — all real,
natural follow-ups picked up once this core deploy/configure path had
actually been used for a while, not silently half-built from the
start.

## Environment note

Verification happened on the project's own dev VM (192.168.2.234,
AlmaLinux 10.2) rather than the actual sandbox this session otherwise
runs in, which has `/dev/kvm` but no root access to install `libvirt`/
`qemu-kvm`/`virt-install` in the first place. `libvirtd` was installed
and enabled there for this work (nested KVM confirmed already enabled
on that VM), a `default` storage pool and the standard `default`
network were created since neither existed yet, and the `claude` user
was added to the `libvirt` group for passwordless `virsh`/`virt-install`
access (matching how a real end user would normally be set up, not a
one-off for this session). All test VMs/volumes were destroyed and
undefined afterward — the host was left with libvirtd running, the
`default` pool/network, and nothing else.
