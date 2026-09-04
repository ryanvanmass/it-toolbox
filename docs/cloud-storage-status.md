# Cloud Storage module — status and handoff

Branch: `feature/cloud-storage`. Read this file first if you're picking
this work up in a new session — it's written so a fresh session with no
prior conversation history can get oriented from the repo alone.

## What this branch is

A new, third top-level module (alongside Connection Manager's gcloud
tree and Shell Launcher's local shells) that configures and browses
rclone remotes — a graphical wrapper around the `rclone` CLI, the same
way Connection Manager wraps `gcloud`/`virsh`. Remote *creation* is
generic across all ~50 rclone backend types (S3, SFTP, WebDAV, Drive,
local, etc.) via a form rendered straight from rclone's own
`config providers` schema, rather than hand-built forms per backend.

rclone was not installed on the dev machine this was built on — it was
installed locally (`~/.local/bin/rclone`, v1.75.0, via the static
binary from downloads.rclone.org, no sudo needed) specifically to
verify every milestone below end-to-end against a real local-filesystem
remote (no real cloud credentials were used or needed).

## What's done and verified (Milestones 1-4, all complete)

1. **`core/rclone_client.py`** — subprocess wrapper (`is_available`,
   `list_remotes`, `list_providers`, `start_create_remote`,
   `continue_config_step`, `delete_remote`, `list_directory`,
   `download`), same style as `core/auth/gcp_auth.py`/
   `modules/connection_manager/qemu_client.py`. Remote creation uses
   rclone's documented non-interactive GUI-wrapper protocol: supply
   every known field as `key=value` up front; if the backend needs one
   more piece of interactive input beyond plain fields (OAuth token
   backends, mainly — confirmed live against Drive's real setup flow,
   without completing the OAuth itself), rclone responds with exactly
   one more question instead of finishing, which `continue_config_step`
   answers, looping until done. Fully unit-tested
   (`tests/core/test_rclone_client.py`) with `subprocess.run` mocked, so
   the suite itself has no real rclone dependency.
2. **Module skeleton** (`modules/cloud_storage/module.py` +
   `ui/main_view.py`, registered third in `modules/registry.py`). A
   single "Remotes" root in the sidebar tree (only one connection
   family here, unlike Connection Manager's GCP/QEMU/Manual), populated
   from `list_remotes()`. Falls back to a placeholder row (not an
   error) when rclone isn't on PATH. Constructor takes the shared
   `tabs: QTabWidget` from `MainWindow` (see below) from day one.
3. **`ui/add_remote_dialog.py`** — the generic "Add Remote" form: name +
   filterable provider-type list, then a form built from that
   provider's `Options` (`Exclusive`+`Examples` → combo box,
   `IsPassword` → masked field, `bool` → checkbox, else → line edit;
   advanced fields hidden behind a checkbox). Falls into a one-question
   loop only when a backend actually needs it. Verified live: real
   69-backend provider list loaded, a live "webdav" remote created with
   real field values via the actual `rclone` binary.
4. **`widgets/rclone_browser_widget.py`** — near-identical to
   `widgets/bucket_browser_widget.py` (breadcrumb, Up, a folders+files
   table), generalized to any remote+path via `lsjson`/`copyto`. Opens
   as a tab in the shared session-tab pane (double-click a remote, or
   its "Browse" context action) using the same ownership-tracking +
   `try_close_tab` pattern Connection Manager/Shell Launcher's tabs
   already use (see `app.py`'s `_session_tabs`/`_on_session_tab_close_requested`).
   Verified live: real directory listing (a file + a subfolder) on a
   real local-filesystem remote, navigated into the subfolder, and
   downloaded a real file — all through the actual rclone binary.

Full `pytest` suite passes (174 tests as of the last milestone commit).

## What's NOT verified — real cloud backends and Windows

Everything above was verified against a **local-filesystem rclone
remote** on Linux — that's what "real infrastructure" meant here, since
no real cloud credentials (S3, SFTP host, Google account, etc.) were
available. Specifically unverified:

- **Any actual network backend** (S3, SFTP, WebDAV against a real
  server, Backblaze B2, etc.) — the generic form mechanics are proven
  (a `webdav` remote was created with real field values), but nothing
  has actually *connected* to a non-local backend yet. If you have real
  credentials for any backend, creating a remote and browsing it for
  real is the highest-value next check.
- **A real OAuth completion** (Google Drive, Dropbox, OneDrive, etc.) —
  confirmed the multi-step JSON protocol progresses correctly through
  Drive's first couple of setup questions (`client_id_warning` →
  `client_id_set`), but the flow was never carried through to an actual
  browser authorization with a real account. If `rclone config create
  --non-interactive` eventually needs to launch a real browser and wait
  on it, that call happens via the same `async_utils.run_in_background`
  path everything else uses, so the dialog *should* stay responsive
  while it blocks in the background thread — but this is unverified.
- **Windows** — this whole module was built and tested on Linux. Nothing
  in `rclone_client.py` is platform-specific (it's a thin subprocess
  wrapper around `rclone`, which itself is cross-platform), so it's
  expected to work as-is, but hasn't been run on a real Windows machine.
  Follow the same verification discipline as `docs/shell-launcher-status.md`
  did for its Windows gap: install rclone, launch the app, add a remote,
  browse it, confirm a real listing/download.

## How to pick this up

1. `git checkout feature/cloud-storage`, `git pull`.
2. If you have real cloud credentials for any backend: open Cloud
   Storage's sidebar, right-click "Remotes" → "Add Remote…", pick that
   backend type, fill in the real fields, and confirm it connects and
   browses for real. This is the most valuable remaining check — local
   filesystem was the only backend verified so far.
3. If picking this up on Windows: confirm `rclone` is installed and on
   PATH, then run through the same add/browse/download flow there.
4. No further milestones are planned beyond configure+browse+download
   unless new requirements come up (e.g. upload, delete, rename inside
   a remote — deliberately out of scope for now, matching
   `bucket_browser_widget.py`'s same read-only-for-now scope note).
