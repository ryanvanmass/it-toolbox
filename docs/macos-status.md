# macOS (Apple Silicon) support — status and handoff

Branch: `feature/macos-arm64`. Read this file first if you're picking
this work up in a new session. It's written so a fresh session with no
prior conversation history can get oriented from the repo alone.

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
     and the app falls back to external RDP clients.
   - `core/session_launcher.py`: external RDP writes a temp `.rdp` file
     and runs `open -a "Windows App"` (or "Microsoft Remote Desktop").
     Without either, it falls back to Homebrew `sdl-freerdp`/`xfreerdp`,
     else raises `SessionLaunchError` with an install hint. SSH opens a
     Terminal.app window via `osascript` (`do script`).
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

## What's unverified (needs a person on an Apple Silicon Mac)

CI proves the bundle builds, is validly signed, and starts headless.
Nothing below has been exercised yet. Use a `vX.Y.Z-beta.N` cut from the
branch (`docs/releasing.md`, "Before merging a PR"):

- [ ] The `.dmg` opens, drags to Applications, and launches after
      right-click > Open. Check that the **Dock shows "IT Toolbox" and its
      icon**, not "python". The `Contents/MacOS/python` symlink is meant
      to ensure that. If it doesn't, the fallback is a small compiled stub
      as `CFBundleExecutable`.
- [ ] gcloud/rclone installed via Homebrew or the Cloud SDK installer are
      found when launched from Finder (the launcher's login-shell `PATH`).
- [ ] SSH opens Terminal.app. Expect a one-time "IT Toolbox wants to
      control Terminal" Automation prompt (`NSAppleEventsUsageDescription`).
- [ ] With `brew install freerdp`: embedded RDP connects, renders, takes
      keyboard/mouse input, resizes, and the clipboard works. The Qt
      scancode mapping (`core/rdp/scancodes.py`) has never been tested
      against macOS key events, and the Cmd/Option keys especially may
      need mapping.
- [ ] Without FreeRDP: the app still starts, and RDP opens in Windows App
      (or shows the install hint).
- [ ] In-app update: from an installed beta, update to a newer beta.
      Confirm the app quits, the bundle is replaced, and the new version
      relaunches without a Gatekeeper prompt.
- [ ] Shell Launcher lists zsh/bash from `/etc/shells`, and the embedded
      terminal works (`ptyprocess`).

## Out of scope

Intel/universal builds, bundling FreeRDP dylibs, Developer ID
signing/notarization, SPICE/QEMU on macOS (those settings stay gated to
Linux).
