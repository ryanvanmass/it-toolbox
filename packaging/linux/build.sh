#!/usr/bin/env bash
# Builds an it-toolbox .deb and .rpm, both vendoring a full venv (see
# docs/releasing.md for why). Requires: python3, python3-venv, fpm (gem
# install fpm), rpm (for the RPM output), and sudo (writes to real
# /usr/share on the build host -- see the comment below on why that's
# safe). Runnable standalone, same convention as scripts/release.sh, and
# is exactly what .github/workflows/package-linux.yml runs in CI.
set -euo pipefail
cd "$(dirname "$0")/../.."  # repo root

VERSION=$(python3 -c "import tomllib; print(tomllib.load(open('pyproject.toml','rb'))['project']['version'])")
PREFIX=/usr/share/it-toolbox

echo "Building it-toolbox $VERSION packages..."

# 1. Build a wheel of it-toolbox itself. Uses its own throwaway venv for
#    the `build` tool rather than the system Python -- keeps this script
#    working unmodified against a plain apt-installed python3 (which
#    refuses system-wide pip installs under PEP 668, "externally managed
#    environment") as well as against actions/setup-python in CI.
BUILD_TOOL_VENV=$(mktemp -d)
python3 -m venv "$BUILD_TOOL_VENV"
"$BUILD_TOOL_VENV/bin/pip" install --upgrade build
rm -f dist/it_toolbox-*.whl
"$BUILD_TOOL_VENV/bin/python" -m build --wheel

# 2. Build the venv AT its real final install path. The build host is
#    ephemeral (a CI runner, or deliberately treated as such if run
#    locally), so writing to real /usr/share here is safe -- and it means
#    every absolute path pip bakes into entry-point script shebangs is
#    already correct for the real install location. No relocation
#    tooling (fpm's --input-type virtualenv, virtualenv-tools3, ...)
#    needed at all. Confirmed directly: `head -1 venv/bin/it-toolbox`
#    after this step shows the real final path, not the build path.
# A glob, not "dist/it_toolbox-${VERSION}-py3-none-any.whl" -- `build`
# normalizes pyproject.toml's raw version string to PEP 440 canonical
# form for the actual wheel filename (e.g. "0.3.0-beta.1" -> "0.3.0b1"),
# so building that filename from $VERSION directly doesn't match what
# actually landed in dist/. Safe as a plain glob since the `rm -f
# dist/it_toolbox-*.whl` above guarantees at most one matches.
WHEEL=(dist/it_toolbox-*-py3-none-any.whl)
if [[ ! -f "${WHEEL[0]}" ]]; then
    echo "No wheel found in dist/ matching it_toolbox-*-py3-none-any.whl" >&2
    exit 1
fi

sudo rm -rf "$PREFIX"
sudo mkdir -p "$PREFIX"
sudo python3 -m venv "$PREFIX/venv"
sudo "$PREFIX/venv/bin/pip" install --upgrade pip
sudo "$PREFIX/venv/bin/pip" install "${WHEEL[0]}"
sudo find "$PREFIX/venv" -name "__pycache__" -exec rm -rf {} +

# 3. Stage the /usr/bin wrapper, .desktop entry, and icon.
STAGE=$(mktemp -d)
mkdir -p "$STAGE/usr/bin" "$STAGE/usr/share/applications" \
         "$STAGE/usr/share/icons/hicolor/scalable/apps"
cp packaging/linux/it-toolbox.desktop "$STAGE/usr/share/applications/"
# The single canonical copy lives inside the package itself (src/it_toolbox
# /resources/icons/) so the *running app* can also load it at runtime for
# its own window icon (app.py) -- not duplicated here, just reused.
cp src/it_toolbox/resources/icons/it-toolbox.svg "$STAGE/usr/share/icons/hicolor/scalable/apps/"
cat > "$STAGE/usr/bin/it-toolbox" <<'WRAPPER'
#!/bin/sh
exec /usr/share/it-toolbox/venv/bin/it-toolbox "$@"
WRAPPER
chmod +x "$STAGE/usr/bin/it-toolbox"

# 4. Wrap it all with fpm's plain `-s dir` mode -- deliberately not its
#    `-s virtualenv` input type, which builds its own venv from a PyPI
#    spec via the legacy `virtualenv` tool + a separate virtualenv-tools3
#    package, and has its own opinionated package-naming behavior. `-s
#    dir` just copies an already-correct directory tree, which step 2
#    above already produced.
#
#    These --depends lists are the base X11/EGL/GL/audio/DBus stack Qt
#    itself needs to start at all -- confirmed by actually hitting each
#    missing-library crash on a minimal Ubuntu 24.04 container and
#    resolving them one at a time, then cross-checking the RPM names via
#    `dnf provides` on a real Fedora host. On a normal desktop Linux
#    install these are already present via the desktop environment's own
#    graphics stack; declaring them here just protects a genuinely
#    minimal/server install from a confusing crash. Per-*feature*
#    optional tools (FreeRDP, spice-glib, virsh, rclone, gcloud) stay
#    documented-only, not package dependencies -- see the README.
mkdir -p dist/packages
DEB_DEPENDS=(
  --depends "python3 (>= 3.11)"
  --depends libgl1 --depends libxkbcommon0 --depends libegl1
  --depends libxcb-cursor0 --depends libxcomposite1 --depends libxi6
  --depends libxtst6 --depends libxrandr2 --depends libxdamage1
  --depends libnss3 --depends "libasound2t64 | libasound2"
  --depends libdbus-1-3 --depends libfontconfig1
)
RPM_DEPENDS=(
  --depends "python3 >= 3.11"
  --depends libglvnd-glx --depends libxkbcommon --depends libglvnd-egl
  --depends xcb-util-cursor --depends libXcomposite --depends libXi
  --depends libXtst --depends libXrandr --depends libXdamage
  --depends nss --depends alsa-lib --depends dbus-libs --depends fontconfig
)
# RPM's Version field flatly rejects "-" (it's the NVR separator), and
# both dpkg and rpm treat "~" as the portable, standard way to encode
# "this is a pre-release, sort it before the plain version" -- so
# "0.3.0-beta.1" (fine for pyproject.toml/PEP 440 and the wheel filename
# above) becomes "0.3.0~beta.1" specifically for the packages' own
# version field. A plain release version has no "-" to replace, so this
# is a no-op for those.
PACKAGE_VERSION="${VERSION//-/\~}"

COMMON_ARGS=(
  -s dir -n it-toolbox -v "$PACKAGE_VERSION"
  --license Apache-2.0
  --description "Cross-platform IT tooling desktop app"
  --url "https://github.com/ryanvanmass/it-toolbox"
  -p dist/packages/
  "$PREFIX/"=/usr/share/it-toolbox/
  "$STAGE/usr/"=/usr/
)
fpm -t deb -a amd64 "${DEB_DEPENDS[@]}" "${COMMON_ARGS[@]}"
# _build_id_links/debug_package: fpm's RPM output otherwise auto-generates
# thousands of debuginfo/build-id symlinks for every ELF binary in the
# vendored venv (Qt's bundled .so files, compiled extension modules) --
# confirmed via a real before/after `rpm -qlp` diff.
fpm -t rpm -a x86_64 \
  --rpm-rpmbuild-define '_build_id_links none' \
  --rpm-rpmbuild-define 'debug_package %{nil}' \
  "${RPM_DEPENDS[@]}" "${COMMON_ARGS[@]}"

echo "Built:"
ls -la dist/packages/
