# Cutting a release

it-toolbox is distributed as source (`pip install` from a git checkout) —
there's no packaged build step yet. A "release" here is a version bump plus
a GitHub Release, which exists so the app's Settings page (App Updates
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

   Pushing the tag triggers `.github/workflows/release.yml`, which
   publishes a GitHub Release for `vX.Y.Z` with auto-generated release
   notes (from commits since the previous tag).

## Why the script doesn't push

Pushing a version tag is a real, world-visible publish action — same
category as merging a PR. The script does the mechanical, reversible part
(edit + local commit + local tag); pushing is a deliberate, separate step
you take when you're actually ready to publish.
