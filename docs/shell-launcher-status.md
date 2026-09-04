# Shell Launcher module — status and handoff

Branch: `feature/shell-launcher`. Read this file first if you're picking
this work up in a new session — it's written so a fresh session with no
prior conversation history can get oriented from the repo alone.

## What this branch is

A new, fourth top-level module (alongside Connection Manager's three
connection families) that's entirely local: it queries the current
machine for installed shells and lets the user launch any of them in an
embedded terminal tab. No accounts, no discovery hierarchy, no tunnels —
just "what shells does this box have, and let me open one."

It reuses two things unchanged: `widgets/terminal_widget.py`'s
`TerminalWidget` (already spawns arbitrary `argv`, not just `ssh` — only
ever used with `["ssh", ...]` in production before this branch, but nothing
about it is SSH-specific) and the `ToolModule` sidebar-registration
pattern (`modules/__init__.py`, `modules/registry.py`), so this module's
own code is almost entirely new discovery logic plus thin wiring.

## What's done and verified (Milestones 1-2)

1. **Discovery** (`core/shell_discovery.py`: `Shell`, `discover_shells()`).
   POSIX: parses `/etc/shells`, keeping only entries that exist and are
   executable, de-duplicated by *resolved* path — verified on this real
   dev machine, where `/bin` is a symlink to `/usr/bin`, so `/etc/shells`'
   four raw lines (`/bin/sh`, `/bin/bash`, `/usr/bin/sh`, `/usr/bin/bash`)
   collapse to the two real binaries (`bash`, `tmux` — yes, `tmux` is a
   genuine `/etc/shells` entry on Fedora). Supplemented with
   `shutil.which` for `zsh`/`fish`/`pwsh`/`nu`/`dash`/`tcsh`/`ksh` in case
   they're installed but not registered in `/etc/shells`.
   Windows: always lists `cmd.exe`/`powershell.exe`, adds `pwsh.exe` and
   Git Bash when found, and enumerates installed WSL distros via
   `wsl -l -q`. **Windows path is unverified on real Windows** — see
   below.
2. **Wired into the app** (`modules/shell_launcher/module.py` +
   `ui/main_view.py`, registered in `modules/registry.py`). Mirrors
   `ConnectionManagerModule`/`ConnectionManagerView`'s shape exactly: a
   `QListWidget` of discovered shells in the sidebar, a `QTabWidget` of
   embedded `TerminalWidget` sessions in the main view, a "Refresh"
   action to re-run discovery. `aboutToQuit` closes every open session on
   app exit, matching `ConnectionManagerView._stop_all_sessions` — without
   it, quitting would leave orphaned shell processes running.
   Verified end-to-end via the real `MainWindow`: the module appears in
   the sidebar, lists this machine's real shells, and launching one
   produces an actual working shell prompt in the embedded tab.

## What's NOT verified — Windows-specific discovery

This was all built and tested on Linux. Three things in
`_discover_windows_shells()`/`_discover_wsl_distros()` are written from
documented behavior, not confirmed against a real Windows machine:

- `wsl -l -q`'s output encoding (UTF-16LE, often with a leading BOM, when
  piped rather than written to a real console) — the decode step is
  believed correct but has never actually run against a real `wsl.exe`.
- Git Bash detection (`shutil.which("bash")` filtered to paths containing
  "git", plus the two conventional `Program Files` fallback paths) —
  needs checking against a real Git for Windows install.
- That `TerminalWidget`/`PtyHandle`'s Windows path (`pywinpty`) actually
  spawns `cmd.exe`/`powershell.exe`/`wsl.exe -d <distro>` correctly. Note
  `widgets/pty_backend.py`'s own docstring already flags its Windows path
  as unexercised on real Windows before this branch existed.

If you're picking this up on a real Windows machine, that's the gap to
close first: run `core/shell_discovery.py`'s `discover_shells()` there
directly, confirm the list matches what's actually installed, then launch
each kind from the real app and confirm a real prompt appears.

## How to pick this up

1. `git checkout feature/shell-launcher`, `git pull`.
2. If on Windows: confirm `python -m it_toolbox` runs, switch to the
   Shell Launcher module, and check the discovered list against what's
   actually installed (Command Prompt, PowerShell, `pwsh` if you have
   PowerShell 7, Git Bash if installed, one "WSL: `<distro>`" entry per
   `wsl -l -q` result) before trusting any of it.
3. Otherwise: the remaining plan (see `docs/qemu-spice-status.md` for the
   milestone-doc convention this follows) was just polish — README/docs,
   already done — so there's nothing else planned unless new requirements
   come up.
