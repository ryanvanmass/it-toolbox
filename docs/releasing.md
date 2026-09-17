# Cutting a release

it-toolbox is distributed as source (`pip install` from a git checkout)
on Windows/macOS, plus a `.deb`/`.rpm` on Linux (amd64 only — see
"Linux packages" below). A "release" here is a version bump plus a
GitHub Release, which exists so the app's Settings page (App Updates
section) has something to compare the installed version against.

## Steps

1. Make sure `main` is up to date and your working tree is clean.
2. Bump the version and create a local commit + tag:

   ```
   scripts/release.sh X.Y.Z
   ```

   This edits `pyproject.toml`'s `version`, commits, and tags `vX.Y.Z` —
   but does **not** push anything.

3. Review the commit/tag, then publish:

   ```
   git push origin main
   git push origin vX.Y.Z
   ```

   Pushing the tag triggers `.github/workflows/release.yml`, which builds
   the Linux `.deb`/`.rpm` (via `.github/workflows/package-linux.yml`)
   and the Windows installer (via `.github/workflows/package-windows.yml`)
   and publishes a GitHub Release for `vX.Y.Z` with auto-generated
   release notes (from commits since the previous tag) plus those
   packages attached as downloadable assets.

## Pre-releases

`scripts/release.sh` also accepts a pre-release suffix:
`scripts/release.sh X.Y.Z-beta.N` (or `-alpha`/`-rc`/`-pre`/`-preview`,
each with an optional trailing number). The steps are otherwise
identical — push `main` and `vX.Y.Z-beta.N` the same way. `release.yml`
detects the `-` in the pushed tag and marks the published Release as a
pre-release, so it still builds and uploads real packages, but the
result won't show up through GitHub's `/releases/latest` API — which is
what `core/update_checker.py`'s `get_latest_release()` reads, so a
pre-release never gets offered to users through the in-app updater. The
`-` separator specifically (not `.` or nothing, both of which the
version string itself would also tolerate) is required so that
substring check in `release.yml` stays reliable.

## Before merging a PR

Standing practice now, not just for packaging-specific changes: cut the
next pre-release beta *from the PR's own branch*, before merging it into
`main` — `scripts/release.sh` doesn't care what branch it's run from,
and `release.yml` triggers on the tag regardless of which branch the
tagged commit lives on, so this needs no special setup:

```
git checkout <pr-branch>
scripts/release.sh X.Y.Z-beta.N+1
git push origin <pr-branch>
git push origin vX.Y.Z-beta.N+1
```

Confirm the resulting build — and, for anything Windows/Linux-packaging-
or launch-relevant, an actual install — *before* merging the PR. Only
merge once that's confirmed working.

This used to happen the other way around (cut the beta right after
merging), which meant a change could sit in `main` broken until someone
got around to installing it — that's exactly what happened with the
Windows in-app updater silently failing to relaunch: it merged, then the
next beta's real-install test caught it, requiring a second PR and a
second beta cycle to actually fix. Testing on the PR branch first means
`main` never carries a version that hasn't already been confirmed to
work — if the beta fails, fix it and cut another beta from the same
branch; `main` stays clean either way.

In one session this caught two real, previously invisible bugs that
`pytest` alone had no way to catch, because neither is exercised by the
test suite, only by an actual build-and-install: a wheel-filename
mismatch that broke every pre-release build, and a Windows installer
that produced a completely unlaunchable app (every Windows release
shipped before that fix was affected). Use judgment for changes with no
possible packaging/runtime-launch impact (e.g. a docs-only PR) — the
point is catching what tests structurally can't, not cutting a beta on
reflex for every single PR.

## Windows packages

`packaging/windows/build.ps1` builds a Windows installer the same way
`packaging/linux/build.sh` builds the `.deb`/`.rpm`: bundles Python's
official "embeddable" distribution (not a frozen/PyInstaller-style
binary — still a plain, unmodified interpreter) with it-toolbox and its
dependencies `pip install`'d into it at build time, then wraps it with
[Inno Setup](https://jrsoftware.org/isinfo.php) into a `setup.exe`.
`.github/workflows/package-windows.yml` runs the exact same script, and
can also be triggered manually (`workflow_dispatch`, no release side
effect) to test packaging changes before they touch a real release. It's
wired into `release.yml` and has shipped real installers since v0.2.6,
confirmed working against a real Windows environment.

## Linux packages

`packaging/linux/build.sh` builds both packages by vendoring a full venv
(`pip install`'d packages, not a from-scratch Python interpreter — a
system `python3 (>= 3.11)` is still a real dependency) at its actual
final install path (`/usr/share/it-toolbox/venv`), then wraps it with
[`fpm`](https://github.com/jordansissel/fpm) plus a `.desktop` entry
(`packaging/linux/it-toolbox.desktop`) and the app's own icon
(`src/it_toolbox/resources/icons/` — bundled in the wheel so the
*running app* can also load it for its own window icon, not just this
packaging step). It's runnable standalone (needs `python3`,
`fpm`, and `rpm` on `PATH`, plus `sudo` — it writes to real `/usr/share`
on the build host, which is fine on a CI runner or anything else you're
treating as disposable for the build) — useful for iterating on the
packaging itself without needing a real tag push;
`.github/workflows/package-linux.yml` runs the exact same script and can
be triggered manually (`workflow_dispatch`, no release side effect) to
test changes in CI before they ever touch `release.yml`.

## Why the script doesn't push

Pushing a version tag is a real, world-visible publish action — same
category as merging a PR. The script does the mechanical, reversible part
(edit + local commit + local tag); pushing is a deliberate, separate step
you take when you're actually ready to publish.
