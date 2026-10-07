#!/usr/bin/env bash
# Builds the it-toolbox WSL rootfs tarball + .sha256 into dist/wsl/.
#
#   packaging/wsl/build.sh <rootfs-version>
#
# The version must match core/wsl_distro.ROOTFS_VERSION for the app to
# accept it. Uses $CONTAINER_ENGINE if set, else podman if present, else
# docker.
set -euo pipefail

VERSION="${1:?usage: build.sh <rootfs-version>}"
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
OUT_DIR="$REPO_ROOT/dist/wsl"
NAME="it-toolbox-wsl-rootfs-$VERSION"
ENGINE="${CONTAINER_ENGINE:-$(command -v podman || command -v docker)}"

expected="$(sed -n 's/^ROOTFS_VERSION = \([0-9]\+\)$/\1/p' "$REPO_ROOT/src/it_toolbox/core/wsl_distro.py")"
if [[ "$VERSION" != "$expected" ]]; then
    echo "build.sh: version $VERSION doesn't match wsl_distro.ROOTFS_VERSION ($expected)" >&2
    exit 1
fi

PACKAGES="$(python3 -I "$REPO_ROOT/src/it_toolbox/core/linux_tools.py" | tr '\n' ' ')"
echo "Packages: $PACKAGES"

"$ENGINE" build \
    --build-arg "PACKAGES=$PACKAGES" \
    --build-arg "ROOTFS_VERSION=$VERSION" \
    -f "$REPO_ROOT/packaging/wsl/Containerfile" \
    -t "$NAME" "$REPO_ROOT/packaging/wsl"

mkdir -p "$OUT_DIR"
container="$("$ENGINE" create "$NAME")"
trap '"$ENGINE" rm -f "$container" >/dev/null' EXIT
"$ENGINE" export "$container" | gzip -9 > "$OUT_DIR/$NAME.tar.gz"

(cd "$OUT_DIR" && sha256sum "$NAME.tar.gz" > "$NAME.tar.gz.sha256")
ls -lh "$OUT_DIR"
