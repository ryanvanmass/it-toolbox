# macOS (Apple Silicon) support — status and handoff

Merged to `main` in PR #86 (2026-10-10) from `feature/macos-arm64`, and
tested on a real Apple Silicon Mac with v0.3.11-beta.3. Read this file
first if you're picking up macOS work in a new session. It's written so a
fresh session with no prior conversation history can get oriented from
the repo alone.

## What this branch is

Native Apple Silicon support plus a CI-built `.dmg` on every release,
following the existing packagers' philosophy (un-frozen vendored Python
with the wheel pip-installed into it, a standalone build script that CI
just calls). Decisions made up front:

- **FreeRDP is a Homebrew runtime dependency** (`brew install freerdp`),
  not bundled.
- **Ad-hoc signing only.** No Developer ID or notarization, since that
  needs Apple account secrets in CI.
- **arm64 only**, built on `macos-14`. No Intel or universal build.
- **The `.dmg` is attached to Releases**, with full in-app updater
  support.

## What's done

1. **App runs on macOS** (code):
   - `core/rdp/freerdp_client.py`: `_library_candidates()` tries
     Homebrew's `/opt/homebrew/lib` and `/usr/local/lib` by absolute path
     (`lib<name>.3.dylib`, then unversioned) before bare names. A
     Finder-launched app gets no `DYLD_*` variables and no Homebrew
     `PATH`. Missing libraries still raise `OSError`, so `RdpWidget = None`
     and Connection Manager shows "RDP unavailable", the same as on the
     other platforms.
   - `core/session_launcher.py`: external RDP writes a temp `.rdp` file
     and runs `open -a "Windows App"` (or "Microsoft Remote Desktop").
     Without either, it falls back to Homebrew `sdl-freerdp`/`xfreerdp`,
     else raises `SessionLaunchError` with an install hint. SSH opens a
     Terminal.app window via `osascript` (`do script`). **Nothing in the
     UI calls `session_launcher` yet** (on any platform). RDP and SSH
     always open embedded, so these external launchers are unused code
     until something wires them up.
   - Settings > Remote Desktop: the FreeRDP section reports Homebrew
     status on macOS (no fetch button).
   - `resources/icons/it-toolbox.icns`, rendered from the `.svg` and
     shipped in the wheel.
2. **Packaging**: `packaging/macos/build.sh`, `launcher.sh`,
   `Info.plist.in`, `smoke_test.sh`. See `docs/releasing.md` ("macOS
   packages") for how the bundle is laid out and why.
3. **CI**: `.github/workflows/package-macos.yml` builds the app, then
   smoke-tests it: signature check, native-extension imports, and a
   headless launch that must still be running after 10s. It's wired into
   `release.yml`, and also runs on PRs touching `packaging/macos/`.
4. **In-app updater**: `update_checker.ReleaseInfo.macos_dmg_url`
   prefers the `-arm64.dmg` asset. `download_and_install_macos_update()`
   downloads, mounts and stages the new bundle, and starts a detached
   swap-and-relaunch helper. The settings button is only offered when
   `running_app_bundle()` finds an enclosing `.app`.
5. **Tests**: Darwin cases for library candidates, the RDP/SSH launchers,
   the Settings FreeRDP section, `.dmg` asset selection, the macOS update
   flow (with `hdiutil`/`ditto` faked), and the swap helper script itself
   (run for real under `/bin/sh`, including the restore-on-failure path).

## Real-Mac verification

On 2026-10-10 the maintainer installed v0.3.11-beta.3, cut from `main`
right after PR #86 merged, on an Apple Silicon Mac and reported that
everything worked. That covered installing from the `.dmg`, first launch
and general use of the app. The results weren't recorded item by item.
So if a specific behaviour below turns out wrong, treat it as a fresh bug
rather than a regression:

- The `.dmg` opens, drags to Applications, and launches after
  right-click > Open. The Dock should show "IT Toolbox" and its icon,
  not "python". If it ever doesn't, the fallback is a small compiled
  stub as `CFBundleExecutable`.
- gcloud/rclone installed via Homebrew are found when launched from
  Finder (the launcher's login-shell `PATH`).
- With `brew install freerdp`, embedded RDP connects, renders, and takes
  keyboard/mouse input. The Qt scancode mapping (`core/rdp/scancodes.py`)
  was written without macOS key events in mind, so the Cmd/Option keys
  are the most likely to need mapping.
- Embedded SSH and Shell Launcher (zsh/bash from `/etc/shells`,
  `ptyprocess`) work.

Still not exercised on a Mac:

- [ ] **In-app update from one `.dmg` build to a newer one** (quit,
      bundle swap, relaunch, no Gatekeeper prompt). It needs two
      published builds, so the first chance is the next release after
      v0.3.11-beta.3. The swap script itself is tested under `/bin/sh` in
      CI.
- [ ] **Cloud Storage → Mount Locally** with macFUSE or FUSE-T.
- [ ] The **external launchers** in `session_launcher.py` (Windows App,
      `sdl-freerdp`, Terminal.app). They're unreachable from the UI today,
      see above.

## Out of scope

Intel/universal builds, bundling FreeRDP dylibs, Developer ID
signing/notarization, SPICE/QEMU on macOS (those settings stay gated to
Linux).
