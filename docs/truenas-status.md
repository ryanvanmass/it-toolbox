# TrueNAS dashboard — status and setup

The first product in the Infrastructure module: a TrueNAS host's
dashboard tab, with Overview, Storage, Datasets, Data protection,
Shares, Apps and VMs sub-tabs. Phases 1 (read-only) and 2 (safe
actions) are built; Phase 3 (creating and configuring things) is not.

## Requirements

- TrueNAS Community Edition (SCALE) **25.04 or later**. Older releases
  have no `/api/current` endpoint and show "needs 25.04 or later".
  TrueNAS CORE isn't supported.
- An API key, created in the TrueNAS web UI from the user menu (top
  right) > API Keys, ideally for a dedicated user. A read-only admin can
  view everything; the actions need a full admin, or a sharing/storage
  admin for those areas. A permission error names the missing role.
- HTTPS. TrueNAS revokes a key that is ever sent over plain HTTP, so
  `http://` URLs are refused before the key leaves the app.

## How it talks to the NAS

`core/truenas_client.py` is a small JSON-RPC 2.0 client over a websocket
(`wss://<host>/api/current`, using the `websockets` package the app
already depends on). The REST API is deprecated since 25.04 and due to
be removed, so it isn't used at all.

- **Login:** `auth.login_with_api_key`, in one function (`_login`) so a
  newer login method is a small change when TrueNAS retires this one.
- **Certificates:** the self-signed certificate is pinned the same way
  as `core/pinned_tls` does for requests: its SHA-256 is compared with
  the fingerprint trusted in the add-host dialog before the key is sent.
- **Concurrency:** one reader thread routes replies by JSON-RPC id and
  events by collection, so a dashboard's background calls share one
  socket.
- **Jobs** (scrub, app start/stop/update, VM shutdown, service restart)
  are polled through `core.get_jobs` and drive the status bar's progress
  bar.
- **Events:** `reporting.realtime` feeds the Overview's Live box, and
  `app.container_log_follow` streams an app container's log.

`core/truenas_api.py` wraps each call the dashboard makes, and
`core/truenas_models.py` parses the results forgivingly: a field missing
on one release leaves a blank cell instead of breaking the tab.

## What's in each area

| Area | Shows | Actions |
| --- | --- | --- |
| Overview | System info, live CPU/memory/ARC/network/disk, alerts | Dismiss alert |
| Storage | Pools, topology with error counts, disks with temperatures | Start scrub, short/long SMART test |
| Datasets | Dataset tree with quota, compression, lock state; snapshots per dataset | Take, roll back, clone, delete snapshot |
| Data protection | Snapshot, replication, cloud sync, TrueCloud backup, rsync, scrub and SMART tasks; SSH and cloud credentials and which tasks use them | Run now, enable/disable, view last job log, test a credential |
| Shares | SMB and NFS shares, service state | Enable/disable, open in file manager, restart SMB/NFS |
| Apps | Apps, state, version, update, ports | Start, stop, restart, update, live logs, open web UI |
| VMs | VMs, state, vCPUs, memory | Start, shut down, power off |

Every change asks first and names what it touches. Credentials are
shown by name and type only; testing a cloud credential sends the NAS
its own stored record back to `cloudsync.credentials.verify`, so the
secret never reaches the app's UI.

## Field-mapping caveat

Like the GL.iNet dashboard was at first, the JSON shapes here come from
the TrueNAS 25.04 API documentation and the middleware source, and the
tests run against a fake websocket server built from them
(`tests/truenas_fake.py`) -- **not yet against a real NAS**. Expect a
few fields to need correcting after the first real test, most likely:

- `reporting.realtime` field names (the Live box shows "—" for any it
  can't find).
- `app.container_log_follow`'s event collection name, which the client
  matches by prefix.
- Snapshot methods: `pool.snapshot.*` is tried first, falling back to
  `zfs.snapshot.*` if the NAS says the method doesn't exist.
- `service.control` (25.04+) falls back to `service.restart`.

## Not yet

- Phase 3: dataset create/edit/delete and lock/unlock, share and task
  create/edit, SSH connection/keypair/cloud credential add/edit/delete,
  app install from the catalog, VM SPICE console, system update,
  reboot and shutdown.
- A lab TrueNAS VM for testing actions before a real NAS.
