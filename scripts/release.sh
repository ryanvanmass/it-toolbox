#!/usr/bin/env bash
# Bumps pyproject.toml's version, commits, and tags — the local half of
# cutting a release. Does NOT push. Pushing the tag is what triggers
# .github/workflows/release.yml to publish a real, world-visible GitHub
# Release, so that step is left as a deliberate manual
# `git push origin vX.Y.Z` — see docs/releasing.md.
#
# Usage: scripts/release.sh X.Y.Z
#        scripts/release.sh X.Y.Z-beta.N   (or -alpha/-rc/-pre/-preview/-a/-b/-c,
#        each with an optional trailing number) for a pre-release --
#        release.yml detects the "-" in the pushed tag and marks the
#        published GitHub Release as a pre-release, which keeps it out of
#        the /releases/latest API that update_checker.py's in-app updater
#        reads. The "-" is required (not "." or no separator, both of
#        which PEP 440 also tolerates) specifically so that tag-substring
#        check in release.yml stays reliable.

set -euo pipefail

if [[ $# -ne 1 ]]; then
    echo "Usage: $0 X.Y.Z[-{alpha,beta,rc,...}[.N]]" >&2
    exit 1
fi

new_version="$1"
if [[ ! "$new_version" =~ ^[0-9]+\.[0-9]+\.[0-9]+(-(alpha|beta|preview|pre|a|b|c|rc)\.?[0-9]*)?$ ]]; then
    echo "Error: version must look like X.Y.Z or X.Y.Z-beta.N (got '$new_version')" >&2
    exit 1
fi

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
pyproject="$repo_root/pyproject.toml"

current_version="$(grep -m1 -E '^version = "' "$pyproject" | sed -E 's/version = "(.*)"/\1/')"
if [[ -z "$current_version" ]]; then
    echo "Error: couldn't find a version line in $pyproject" >&2
    exit 1
fi

# A plain string/sort -V comparison gets pre-release ordering backwards
# (it thinks "0.3.0" < "0.3.0-beta.1", the opposite of PEP 440's actual
# precedence) -- packaging.version.Version (already a project dependency,
# used by core/update_checker.py) is the real thing to compare with.
if ! python3 -c "
import sys
from packaging.version import Version
sys.exit(0 if Version('$new_version') > Version('$current_version') else 1)
"; then
    echo "Error: new version ($new_version) must be greater than the current version ($current_version)" >&2
    exit 1
fi

if [[ -n "$(git -C "$repo_root" status --porcelain)" ]]; then
    echo "Error: working tree isn't clean — commit or stash first" >&2
    exit 1
fi

sed -i -E "0,/^version = \".*\"/s//version = \"$new_version\"/" "$pyproject"

git -C "$repo_root" add "$pyproject"
git -C "$repo_root" commit -m "Bump version to $new_version"
git -C "$repo_root" tag "v$new_version"

cat <<EOF

Bumped $current_version -> $new_version and created tag v$new_version.
Nothing has been pushed. When you're ready to actually publish this release:

    git push origin main
    git push origin v$new_version

Pushing the tag triggers the release workflow, which publishes a GitHub
Release for v$new_version.
EOF
