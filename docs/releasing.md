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
   and publishes a GitHub Release for `vX.Y.Z` with auto-generated
   release notes (from commits since the previous tag) plus those two
   packages attached as downloadable assets.

## Windows packages

`packaging/windows/build.ps1` builds a Windows installer the same way
`packaging/linux/build.sh` builds the `.deb`/`.rpm`: bundles Python's
official "embeddable" distribution (not a frozen/PyInstaller-style
binary — still a plain, unmodified interpreter) with it-toolbox and its
dependencies `pip install`'d into it at build time, then wraps it with
[Inno Setup](https://jrsoftware.org/isinfo.php) into a `setup.exe`.
`.github/workflows/package-windows.yml` runs the exact same script, and
can be triggered manually (`workflow_dispatch`, no release side effect)
— **not yet wired into `release.yml`**, since none of this has been
verified against a real Windows environment yet (this project's own dev
work happens on Linux). Wire it in once a `workflow_dispatch` run has
actually been inspected and the installer confirmed to work.

## Linux packages

`packaging/linux/build.sh` builds both packages by vendoring a full venv
(`pip install`'d packages, not a from-scratch Python interpreter — a
system `python3 (>= 3.11)` is still a real dependency) at its actual
final install path (`/usr/share/it-toolbox/venv`), then wraps it with
[`fpm`](https://github.com/jordansissel/fpm) plus a `.desktop` entry and
icon from `packaging/linux/`. It's runnable standalone (needs `python3`,
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
