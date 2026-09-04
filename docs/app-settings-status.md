# Settings module — status and handoff

Branch: `feature/app-settings`. Read this file first if you're picking
this work up in a new session — it's written so a fresh session with no
prior conversation history can get oriented from the repo alone.

## What this branch is

A new, fourth top-level module — a plain scrollable settings page, not
tab/session-based like the other three modules, so it never touches the
shared `MainWindow._session_tabs` pane. Consolidates status/setup for
everything the app depends on into one place: app updates, rclone,
gcloud, QEMU/libvirt, and FreeRDP (Windows).

App updates required adding real release infrastructure first (a
tag-triggered GitHub Release workflow + a local version-bump script) —
there was none before this branch, and the app stays pip-install-based
(no `.deb`/`.rpm` packaging; that's a deliberately separate, later
project if it happens).

## What's done and verified (Milestones 1-5, all complete)

1. **Release infrastructure** — `.github/workflows/release.yml` (tag
   push → GitHub Release via `softprops/action-gh-release`, auto-
   generated notes), `scripts/release.sh` (bumps `pyproject.toml`,
   commits, tags — deliberately does *not* push; see `docs/releasing.md`).
   I never ran the script or pushed a tag myself — cutting the first
   real release is your call, whenever you're ready.
2. **`core/update_checker.py`** — compares `importlib.metadata.version
   ("it-toolbox")` against `GET /repos/ryanvanmass/it-toolbox/releases/
   latest`. Verified live against the real GitHub API (currently 404 —
   no releases published yet — which the code treats as a normal,
   expected state, not an error) and the real installed package version.
3. **rclone section** — status (found/not found + resolved path),
   "Set/Change rclone Location…" / "Use rclone from PATH" (the same
   logic Cloud Storage's sidebar menu had, extracted into
   `widgets/rclone_location_picker.py` so both write to the same
   `settings.rclone_path` override), and a "Download rclone…" button
   (`rclone_client.download_latest()`, fetches the platform build from
   `downloads.rclone.org`). Verified live: downloaded a real build on
   this dev machine, confirmed it runs (`rclone version`), confirmed the
   override gets set and can be cleared.
4. **gcloud section** — status + Sign In/Out, reusing
   `gcp_auth.sign_in()`/`sign_out()`/`get_active_account()` via the same
   `run_in_background` pattern `ConnectionManagerView`'s own sign-in
   button already uses. Verified live (read-only): this dev machine has
   a real, already-signed-in gcloud session, and the section correctly
   showed "Signed in as ryanvanmassenhoven@gmail.com". Sign-in/out
   themselves were **not** exercised live, deliberately — doing so would
   touch the real gcloud credentials on this machine.
5. **QEMU/libvirt + FreeRDP sections**:
   - QEMU: `qemu_client.is_available()` (new, mirrors `gcp_auth`/
     `rclone_client`'s own `is_available()`) — verified live, this dev
     machine has real `virsh` installed and the section correctly
     reports it found. Off Linux, or when missing, shows apt/dnf install
     text — no download button, it's a system package.
   - FreeRDP: guarded import of `core.rdp.freerdp_client` (that module
     loads DLLs as an import-time side effect and raises `OSError` if
     they're missing — same reasoning as the `SpiceWidget`/PyGObject
     guard already in `connection_manager/ui/main_view.py`). Off
     Windows, shows "Not applicable". On Windows, a "Fetch FreeRDP DLLs"
     button runs the existing `scripts/fetch_freerdp_windows.ps1` via
     `subprocess`, then re-sets `IT_TOOLBOX_FREERDP_DIR` in-process and
     retries the import — no restart needed if it works, since the
     module wasn't successfully imported before (Python doesn't leave a
     failed import cached in `sys.modules`).

Full `pytest` suite passes (245 tests as of the last milestone commit).

## What's NOT verified — anything Windows-only

Everything Windows-specific in this branch is logic-level only:

- **The FreeRDP fetch button** — `_run_freerdp_fetch_script`'s
  `subprocess.run(["powershell", ...])` invocation and the env-var/
  re-import handling were verified by unit test (mocking `subprocess.run`
  and, since this dev machine happens to have real libfreerdp3 installed
  from the earlier embedded-RDP work, a genuine successful re-import of
  the real module) — but the actual PowerShell script has never been run
  from inside the app on a real Windows machine. If picking this up on
  Windows: delete/rename `%LOCALAPPDATA%\it-toolbox\freerdp` first (so
  the fetch has something real to do), open Settings, click "Fetch
  FreeRDP DLLs", confirm it downloads and the status flips to "loaded"
  without restarting the app.
- **`_FREERDP_FETCH_SCRIPT`'s path resolution** — walks up from
  `main_view.py` to the repo root and appends `scripts/…ps1`. This only
  resolves to a real file for an editable/source install (the app's
  current only real deployment shape); a future non-editable `pip
  install` of a built wheel would not carry `scripts/` along, and the
  button correctly reports "Fetch script not found" rather than
  crashing — but that not-found path itself was only unit-tested, not
  observed against a real non-editable install.
- **App updates end-to-end** — the 404 (no-releases-yet) path is
  genuinely verified; the "update available" / "up to date" comparison
  logic is unit-tested with fake data but has never been checked against
  a *real* published GitHub Release, since none exists yet. Once you cut
  a first real release (`scripts/release.sh` + push the tag), checking
  for updates from an older installed version for real would be the
  last real-world gap to close.

## How to pick this up

1. `git checkout feature/app-settings`, `git pull`.
2. If picking this up on Windows: confirm the FreeRDP fetch button
   actually downloads and loads the DLLs, per the note above.
3. Once ready to cut a first real release: `scripts/release.sh X.Y.Z`,
   review, then `git push origin main && git push origin vX.Y.Z` — that
   exercises the release workflow and the update-checker's "update
   available" path for real, for the first time.
