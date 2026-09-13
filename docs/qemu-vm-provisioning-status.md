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
   land; `ConfigureVmDialog` pre-fills vCPU/memory from a fresh
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

4. **Settings** (`modules/settings/ui/main_view.py`'s QEMU/libvirt
   section) now separately reports `virt-install`'s own availability,
   since a `virsh`-only install (just `libvirt-clients`, no
   `virtinst`/`virt-install`) leaves VM discovery/power control working
   fine while "Deploy VM…" still needs the separate package.

5. **Tests**: `test_qemu_provisioning.py` (17 tests, real captured
   output as fixtures — parsers, argv construction, the `--import`-
   vs-`--cdrom` branching, the real `"An install method must be
   specified"` error text), `test_create_vm_dialog.py` (7),
   `test_configure_vm_dialog.py` (7), plus context-menu-wiring tests in
   `test_main_view_sessions.py` and two new Settings-section tests.
   Dialogs are tested directly (constructed + `qtbot.addWidget` +
   `.show()`, not `.exec()`'d modally) — the same pattern already
   established by `test_add_remote_dialog.py`/`test_api_key_dialog.py`
   for this project's other async-loading dialogs. One real bug caught
   immediately by this: `QWidget.isVisible()` is always `False` for a
   widget inside a `QDialog` that was never actually shown on screen,
   regardless of what `setVisible()` was last called with — fixed by
   calling `dialog.show()` in the test fixture, not by changing the
   dialog code (the code was already correct; the *test* was checking
   the wrong thing). Full suite: 530 passed, the same 8 pre-existing,
   unrelated (headless-environment focus/clipboard) failures already
   present on the base branch, confirmed by running them there too.

## Deferred (explicitly out of scope for this branch)

Cloud-init/unattended install, uploading local media from the
it-toolbox machine to the libvirt host (media has to already be on the
host, discovered via `list_volumes`), editing a *running* VM's
resources (live hotplug — `resize_vm` is `--config`-only, by design),
network interface add/remove, disk detach/removal, boot-order changes,
snapshot support, and OS-variant auto-detection (`osinfo-query` — the
dialog just has a free-text field defaulting to `generic`, which
`virt-install` always accepts). All real, natural follow-ups once this
core deploy/configure path has been used for a while — not silently
half-built here.

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
