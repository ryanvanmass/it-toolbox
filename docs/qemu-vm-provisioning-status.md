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

## Deferred (explicitly out of scope for this branch)

Cloud-init/unattended install, uploading local media from the
it-toolbox machine to the libvirt host (media has to already be on the
host, discovered via `list_volumes`), editing a *running* VM's
resources (live hotplug — `resize_vm` is `--config`-only, by design),
multi-NIC network editing (`ConfigureVmDialog`'s Network section only
shows for a VM with exactly one interface — adding/removing NICs, or
picking which one to change on a multi-NIC VM, is deferred), boot-order
changes, snapshot support, and *automatic* OS-variant detection from the
chosen ISO/image (the OS variant combo is a full, real, searchable list
of every valid value — added after the first cut, see above — but
nothing inspects the attached media to guess which one applies; the
admin still picks it, defaulting to `generic`). Disk removal, CD-ROM
media management, and single-NIC network changes on an existing VM —
originally deferred here — were added in a later round (see
`ConfigureVmDialog` above). All of the above are real, natural
follow-ups once this core deploy/configure path has been used for a
while — not silently half-built here.

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
