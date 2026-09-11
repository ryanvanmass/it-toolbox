# Windows troubleshooting

Working notes for testing/debugging the Windows build and the in-app
updater on a real Windows machine — this repo's own dev work happens on
Linux, so nothing here has ever been verified end-to-end until the
`v0.3.0-beta.*` series. Update this file as you find more.

## What to test right now

`v0.3.0-beta.6` (<https://github.com/ryanvanmass/it-toolbox/releases/tag/v0.3.0-beta.6>)
bundles everything fixed so far. Checklist:

1. **Install it** (`it-toolbox-0.3.0-beta.6-setup.exe`, double-click, accept UAC).
2. **Launch it** from the Start Menu. If this fails with "Fatal Error in
   Launcher" / "Unable to create process using ...pythonw.exe...", see
   [Launcher pointed at a build-time-only path](#launcher-pointed-at-a-build-time-only-path)
   below — that specific error should be gone as of beta.3, but confirm.
3. **Check the icon** — title bar and taskbar should show the real IT
   Toolbox logo, not a generic placeholder. Fixed in beta.5.
4. **Check the version** in Settings > App Updates matches what you just
   installed (`0.3.0-beta.6`). This is the one most worth being careful
   about — see [Stale version after an update](#stale-version-after-an-update).
5. **Exercise the in-app update loop itself**, not just a fresh install:
   - Settings > App Updates > check "Include pre-release (beta) updates".
   - Click "Check for Updates" — should say an update's available once a
     newer beta exists (ask if one hasn't been cut yet for this).
   - Click "Download && Install" — confirm the dialog, watch the new
     progress bar move, expect a UAC prompt when the silent install
     actually kicks off, then the app should close and reopen on its own.
   - **This is the scenario nobody's confirmed works yet**: the currently
     *running* `pythonw.exe` is inside the exact directory
     (`{app}` = `C:\Program Files\IT Toolbox`) that gets wiped and
     recreated as part of the fix in
     [Stale version after an update](#stale-version-after-an-update). If
     this hangs, fails partway, or the relaunch doesn't happen, that's
     the thing to report back with full details (see
     [Capturing debug logs](#capturing-debug-logs)).

## Known-fixed issues (for reference if you see them again)

### Launcher pointed at a build-time-only path

**Symptom**: `Fatal Error in Launcher` — `Unable to create process using
"D:\a\it-toolbox\it-toolbox\build\pyembed\pythonw.exe" "...\Scripts\it-toolbox.exe"`.

**Cause**: `{app}\Scripts\it-toolbox.exe` is a pip-generated launcher stub
that hardcodes the *absolute* interpreter path used at `pip install`
time (a CI-runner-only path) — those stubs aren't relocatable, and
Inno Setup copies the whole build tree to wherever the user's machine
actually installs it. Affected every Windows release before this fix.

**Fix** (PR #53, in `main` since beta.3): the Start Menu shortcut and
post-install launch now run `{app}\pythonw.exe -m it_toolbox` instead —
no baked-in path, resolves the module fresh every launch.
`packaging/windows/it-toolbox.iss`'s `[Icons]`/`[Run]` sections.

### Stale version after an update

**Symptom**: Settings > App Updates still shows the *previous* version
number after installing an update and relaunching.

**Cause**: pip creates a *versioned* dist-info folder per install
(`it_toolbox-X.Y.Zb.dist-info`). Inno Setup's `[Files]` section only
ever adds/overwrites files present in the new payload — it never
deletes anything an older version left behind. So upgrading in place
left both the old and new version's dist-info sitting side by side in
site-packages, and `importlib.metadata.version()` (what Settings
displays, and what `update_checker.is_update_available()` is built on)
has no guaranteed preference for the newer one when duplicates exist.

**Fix** (PR #56, in `main` since beta.6): `[InstallDelete] Type:
filesandordirs; Name: "{app}"` wipes the whole install directory before
`[Files]` extracts, so there's never more than one version's files
present. Matches `packaging/linux/build.sh`'s own `sudo rm -rf
"$PREFIX"` before every rebuild.

**Not yet independently confirmed**: whether this wipe-and-recreate
works cleanly when it's the *running* app's own update triggering it
(see the checklist above). Inno Setup is built to support replacing a
running app's files via delete-sharing, so it should be fine — but
nobody's watched it happen on a real machine yet.

**How to check for yourself** if version confusion shows up again:

```powershell
# Look for more than one dist-info dir -- there should only ever be one.
Get-ChildItem -Recurse -Filter "it_toolbox-*.dist-info" "C:\Program Files\IT Toolbox"

# What importlib.metadata actually resolves to:
& "C:\Program Files\IT Toolbox\python.exe" -c "from importlib import metadata; print(metadata.version('it-toolbox'))"
```

### Missing/generic window icon

**Symptom**: title bar and taskbar show a blank/generic icon instead of
the IT Toolbox logo.

**Cause**: `MainWindow` never called `setWindowIcon` at all, and the
real icon assets lived only under `packaging/{linux,windows}/icons/` —
packaging-time-only paths, never bundled into the actual installed
package, so nothing at runtime could have loaded them on any platform.

**Fix** (PR #55, in `main` since beta.5): icons moved into
`src/it_toolbox/resources/icons/` (a real package, wired into
`pyproject.toml`'s `[tool.setuptools.package-data]` so they actually
ship in the wheel), `app.py` loads the platform-appropriate one
(`.ico` on Windows) and calls `setWindowIcon`.

### Pre-release build failures (fixed before any of the above shipped)

Not something you should hit anymore, but if a *future* pre-release
build fails in CI: `python -m build` normalizes a version like
`0.3.0-beta.1` to PEP 440's `0.3.0b1` for the actual wheel filename,
and RPM's `Version` field outright rejects `-`. Both
`packaging/windows/build.ps1` and `packaging/linux/build.sh` now handle
this correctly (PR #52) — glob for the actual wheel filename instead of
assuming it, and substitute `~` for `-` specifically for the `.deb`/`.rpm`
version field. If you see either class of failure again, that's the
file to check first.

## Capturing debug logs

```powershell
$env:IT_TOOLBOX_LOG_LEVEL = "DEBUG"
& "C:\Program Files\IT Toolbox\pythonw.exe" -m it_toolbox
```

`pythonw.exe` has no console of its own to print to, so redirect it, or
use `python.exe` (not `pythonw.exe`) instead for a visible console
window:

```powershell
$env:IT_TOOLBOX_LOG_LEVEL = "DEBUG"
& "C:\Program Files\IT Toolbox\python.exe" -m it_toolbox
```

If you want the log in a file to paste back:

```powershell
$env:IT_TOOLBOX_LOG_LEVEL = "DEBUG"
& "C:\Program Files\IT Toolbox\python.exe" -m it_toolbox 2>&1 | Tee-Object -FilePath "$env:TEMP\it-toolbox-debug.log"
```

When sharing a log back, prefer filtering to what's relevant rather
than pasting the whole thing (it gets huge fast, especially with an
active RDP/SSH session) — e.g. `findstr` for a specific module's logger
name if you know roughly where the issue is.

## Testing a packaging change without cutting a real release

`.github/workflows/package-windows.yml` can be triggered manually
against any branch, no release side effect:

```
gh workflow run package-windows.yml --ref <branch-name>
gh run list --branch <branch-name> --limit 1
```

Download the resulting `windows-installer` artifact from that run to
test a fix before it ever touches a real beta tag. See
`docs/releasing.md` for the full release/pre-release process, including
the "cut a beta after every merge" habit this project's settled into —
neither of the two most serious bugs above (the launcher, and the
stale-version issue) were catchable by the test suite; both only ever
surfaced from an actual install.

## Where things live, for reference

- Install directory: `C:\Program Files\IT Toolbox` (`{app}` in the
  `.iss` file) — the *whole app*, Python interpreter included. Gets
  wiped and recreated on every install/update as of beta.6.
- User data (settings, cached state — **not** touched by
  install/update): `%LOCALAPPDATA%\it-toolbox` (`platformdirs.user_data_dir`,
  see `core/settings.py`).
- Installer script: `packaging/windows/it-toolbox.iss`.
- Build script: `packaging/windows/build.ps1`.
- In-app updater logic: `core/update_checker.py`
  (`download_and_install_windows_update`).
- Update-related UI: `modules/settings/ui/main_view.py`'s
  `_build_updates_section` and everything below it.
