# Windows troubleshooting

Working notes for testing/debugging the Windows build and the in-app
updater on a real Windows machine — this repo's own dev work happens on
Linux, so nothing here has ever been verified end-to-end until the
`v0.3.0-beta.*` series. Update this file as you find more.

## What to test right now

As of `v0.3.0-beta.9` (<https://github.com/ryanvanmass/it-toolbox/releases/tag/v0.3.0-beta.9>),
every item below has been confirmed working end to end on a real
Windows machine, including the in-app update loop itself. Keep using
this checklist on every future beta — regressions are cheap to catch
here and expensive to catch any other way (see
[Testing a packaging change without cutting a real release](#testing-a-packaging-change-without-cutting-a-real-release)).

1. **Install it** (`it-toolbox-X.Y.Z-setup.exe`, double-click, accept UAC).
2. **Launch it** from the Start Menu. If this fails with "Fatal Error in
   Launcher" / "Unable to create process using ...pythonw.exe...", see
   [Launcher pointed at a build-time-only path](#launcher-pointed-at-a-build-time-only-path)
   — fixed since beta.3.
3. **Check the icon** — title bar and taskbar should show the real IT
   Toolbox logo, not a generic placeholder. Fixed since beta.5.
4. **Check the version** in Settings > App Updates matches what you just
   installed. See [Stale version after an update](#stale-version-after-an-update)
   if it doesn't — fixed since beta.6.
5. **Exercise the in-app update loop itself**, not just a fresh install:
   - Settings > App Updates > check "Include pre-release (beta) updates".
   - Click "Check for Updates" — should say an update's available once a
     newer beta exists (ask if one hasn't been cut yet for this).
   - Click "Download && Install" — confirm the dialog, watch the
     download progress bar move, expect a UAC prompt when the silent
     install kicks off. The app closes almost immediately after that,
     Inno Setup's own small progress window should appear while it swaps
     files, then the new version launches on its own. See
     [Update never relaunches after installing](#update-never-relaunches-after-installing)
     for the history here — fixed since beta.8, but only if the
     *currently running* app is beta.8 or later; updating from beta.6 or
     beta.7 still runs their own broken update code and will reproduce
     the original failure.

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

**How to check for yourself** if version confusion shows up again:

```powershell
# Look for more than one dist-info dir -- there should only ever be one.
Get-ChildItem -Recurse -Filter "it_toolbox-*.dist-info" "C:\Program Files\IT Toolbox"

# What importlib.metadata actually resolves to:
& "C:\Program Files\IT Toolbox\python.exe" -c "from importlib import metadata; print(metadata.version('it-toolbox'))"
```

### Update never relaunches after installing

**Symptom**: click "Download && Install" in Settings > App Updates,
the progress bar finishes, UAC prompt appears and gets accepted, the
app window closes — then nothing. No new window ever opens, no error
message anywhere, and `C:\Program Files\IT Toolbox` still contains the
*old* version (confirmed via the dist-info check above — timestamps on
`Lib`/`Scripts` matched the original install, untouched by the update
attempt).

**Cause**: `download_and_install_windows_update()` used to spawn the
installer and `proc.wait()` on it from inside the very process being
replaced — the running `pythonw.exe`/`python312.dll` are files inside
`{app}`. Inno Setup 6's default `CloseApplications=yes` uses Windows
Restart Manager to silently find and kill (no prompt — this is a silent
install) any process holding a handle into files it's about to touch,
*before* it does anything else. That killed the very process that was
`wait()`-ing on it, so the relaunch code after that call never ran —
and no error surfaced anywhere, because the process that would have
reported it was already dead. This was the exact risk flagged as
"nobody's confirmed this works" in earlier revisions of this doc; it
does not.

**Fix** (PR #58, in `main` since beta.8): the old process no longer
waits for the installer or relaunches the app itself. It launches the
installer detached and quits immediately — freeing its own file handles
*before* Inno ever reaches `[InstallDelete]`, so there's nothing left
for Restart Manager to kill. `packaging/windows/it-toolbox.iss`'s
`[Run]` entry (`skipifsilent` removed) now does the relaunch instead,
since Inno itself is still running after the old app is gone. Trade-off:
the app can no longer show an inline "install failed" message for a
failure that happens after it quits — the "you can still install it
manually via View Release" fallback text is the safety net for that
now.

**Confirmed working on a real machine**: beta.8 (running the fixed
code) updating in-app to beta.9 — app closed right after the UAC
prompt, brief gap with no window at all (this was before the `/SILENT`
fix below — see
[No feedback between the app closing and the new one opening](#no-feedback-between-the-app-closing-and-the-new-one-opening)),
then the new version launched on its own, `importlib.metadata.version()`
correctly showing `0.3.0b9` afterward.
Note this specifically requires the *installed, running* app to already
have the fix — updating *from* beta.6 or beta.7 (which still run the
old, broken code) reproduces the original failure, since the process
doing the updating is what matters, not the version being installed.

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

## Known-fixed issues (continued)

### No feedback between the app closing and the new one opening

**Symptom**: the download has a real progress bar
(`_update_download_progress_bar` in `modules/settings/ui/main_view.py`),
but the moment the installer was launched, the app quit immediately (see
[Update never relaunches after installing](#update-never-relaunches-after-installing)
for why it has to) — leaving a stretch with no IT Toolbox window at all
while Inno Setup did the actual file replacement, indistinguishable from
a real hang.

**Fix**: `download_and_install_windows_update()` now launches the
installer with `/SILENT` instead of `/VERYSILENT`. Both skip the wizard
and need no interaction (`/SUPPRESSMSGBOXES` still suppresses error
message boxes), but `/SILENT` still shows Inno Setup's own small
installation progress window — closing the gap for free, without this
process needing to stick around to show anything itself.

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
