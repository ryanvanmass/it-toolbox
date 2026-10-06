#!/usr/bin/env bash
# Builds an it-toolbox macOS .dmg for Apple Silicon (arm64), bundling a
# relocatable python-build-standalone CPython with it-toolbox and its
# dependencies pip-installed into it at build time -- the macOS equivalent
# of packaging/windows/build.ps1's embeddable Python (same philosophy, see
# docs/releasing.md: deterministic, built once, no network needed at
# install time; deliberately not a PyInstaller/py2app freeze). A plain
# venv can't be used here as on Linux: it only symlinks a system Python,
# which a drag-to-/Applications .app can't depend on.
#
# Requires: macOS on arm64, python3 (>=3.11, for building the wheel --
# separate from the standalone one this script downloads for the actual
# shipped app), curl, codesign, hdiutil (the last three ship with macOS).
# Runnable standalone, same convention as packaging/linux/build.sh, and is
# exactly what .github/workflows/package-macos.yml runs in CI.
set -euo pipefail
cd "$(dirname "$0")/../.."  # repo root

VERSION=$(python3 -c "import tomllib; print(tomllib.load(open('pyproject.toml','rb'))['project']['version'])")
# CFBundleShortVersionString must be plain dotted integers -- "0.3.9-beta.2"
# becomes "0.3.9" there; the full string still goes in CFBundleGetInfoString.
SHORT_VERSION="${VERSION%%-*}"

# Standalone Python -- bump deliberately, independent of it-toolbox's own
# version (kept in step with build.ps1's $PyVersion). The checksum is from
# the release's SHA256SUMS file.
PY_VERSION="3.12.8"
PY_MINOR="${PY_VERSION%.*}"
PBS_RELEASE="20241206"
PBS_TARBALL="cpython-${PY_VERSION}+${PBS_RELEASE}-aarch64-apple-darwin-install_only.tar.gz"
PBS_SHA256="e3c4aa607717b23903ca2650d5c3ee24f89b97543e2db2b0f463bddc7a9e92f3"
PBS_URL="https://github.com/astral-sh/python-build-standalone/releases/download/${PBS_RELEASE}/${PBS_TARBALL}"

APP_NAME="IT Toolbox"
BUILD_DIR=build/macos
APP="$BUILD_DIR/$APP_NAME.app"
DMG="dist/packages/IT-Toolbox-${VERSION}-arm64.dmg"

if [[ "$(uname -s)" != Darwin || "$(uname -m)" != arm64 ]]; then
    echo "This script builds an Apple Silicon .app and must run on arm64 macOS." >&2
    exit 1
fi

echo "Building it-toolbox $VERSION for macOS (arm64)..."

# 1. Build a wheel of it-toolbox itself, in a throwaway venv for the
#    `build` tool (same reasoning as packaging/linux/build.sh).
BUILD_TOOL_VENV=$(mktemp -d)
python3 -m venv "$BUILD_TOOL_VENV"
"$BUILD_TOOL_VENV/bin/pip" install --upgrade build
rm -f dist/it_toolbox-*.whl
"$BUILD_TOOL_VENV/bin/python" -m build --wheel
# A glob -- see packaging/linux/build.sh for why (PEP 440 normalization).
WHEEL=(dist/it_toolbox-*-py3-none-any.whl)
if [[ ! -f "${WHEEL[0]}" ]]; then
    echo "No wheel found in dist/ matching it_toolbox-*-py3-none-any.whl" >&2
    exit 1
fi

# 2. Download, verify and unpack the standalone Python straight into the
#    bundle's Resources. The tarball's top-level dir is python/.
rm -rf "$BUILD_DIR"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
curl -fsSL -o "$BUILD_DIR/python.tar.gz" "$PBS_URL"
echo "$PBS_SHA256  $BUILD_DIR/python.tar.gz" | shasum -a 256 -c -
tar -xzf "$BUILD_DIR/python.tar.gz" -C "$APP/Contents/Resources"
PY="$APP/Contents/Resources/python/bin/python3"
# Some python-build-standalone releases mark themselves PEP 668 "externally
# managed"; this interpreter is ours alone, so pip installing into it is
# exactly what's intended.
rm -f "$APP/Contents/Resources/python/lib/python${PY_MINOR}/EXTERNALLY-MANAGED"

# 3. Install our wheel + its dependencies into that interpreter, then
#    precompile every .py so nothing writes into the signed bundle at
#    runtime (the launcher also sets PYTHONDONTWRITEBYTECODE).
"$PY" -m pip install --no-warn-script-location --upgrade pip
"$PY" -m pip install --no-warn-script-location "${WHEEL[0]}"

# 3b. Slim PySide6 down to what the app uses: QtCore, QtGui and QtWidgets
#     (plus the platform/style/imageformat/iconengine plugins they load --
#     the app icon is an .svg here, so qsvg/qsvgicon stay). Linux and
#     Windows install the full PySide6 unchanged; only the .dmg, which would
#     otherwise ship ~1GB of Qt it never loads, is pruned. PySide6-Addons
#     (WebEngine, 3D, Multimedia, Charts...) goes entirely; from
#     PySide6-Essentials the unused Python bindings, the QML/Quick stack and
#     the developer tools (Designer, Linguist, qmlls...) are removed. Then
#     only the Qt frameworks the remaining Mach-O files actually link
#     (transitively, per `otool -L`) are kept, and every universal2 file is
#     thinned to its arm64 slice -- the .app is arm64-only anyway.
"$PY" -m pip uninstall -y PySide6_Addons
PYSIDE_DIR=$("$PY" -c "import PySide6, os; print(os.path.dirname(PySide6.__file__))")
python3 - "$PYSIDE_DIR" <<'PYEOF'
import glob, os, re, shutil, subprocess, sys
pyside = sys.argv[1]
qt = os.path.join(pyside, "Qt")

def rm(path):
    if os.path.isdir(path) and not os.path.islink(path):
        shutil.rmtree(path)
    elif os.path.lexists(path):
        os.remove(path)

KEEP_BINDINGS = {"QtCore", "QtGui", "QtWidgets"}
for so in glob.glob(os.path.join(pyside, "Qt*.abi3.so")):
    if os.path.basename(so).split(".")[0] not in KEEP_BINDINGS:
        rm(so)
for pattern in ("libpyside6qml.*", "*.app", "lrelease", "lupdate", "qmlformat",
                "qmllint", "qmlls", "svgtoqml", "Qt/libexec", "Qt/qml",
                "Qt/metatypes", "Qt/plugins/designer", "Qt/plugins/qmltooling",
                "Qt/plugins/qmllint", "Qt/plugins/sqldrivers",
                "Qt/plugins/vectorimageformats", "Qt/plugins/tls",
                "Qt/plugins/networkinformation",
                "Qt/plugins/platforminputcontexts"):
    for path in glob.glob(os.path.join(pyside, pattern)):
        rm(path)
# Only Qt's own base translations (standard dialogs/buttons) are relevant.
for qm in glob.glob(os.path.join(qt, "translations", "*.qm")):
    if not os.path.basename(qm).startswith("qtbase_"):
        rm(qm)

MAGICS = {bytes.fromhex(m) for m in ("feedfacf", "cffaedfe", "cafebabe", "bebafeca")}
def macho_files(top):
    for root, dirs, files in os.walk(top):
        for name in files:
            path = os.path.join(root, name)
            if not os.path.islink(path):
                with open(path, "rb") as f:
                    if f.read(4) in MAGICS:
                        yield path

FRAMEWORK_REF = re.compile(r"@rpath/(Qt\w+)\.framework/")
def linked_frameworks(path):
    out = subprocess.run(["otool", "-L", path], check=True,
                         capture_output=True, text=True).stdout
    return set(FRAMEWORK_REF.findall(out))

lib = os.path.join(qt, "lib")
frameworks = {f[:-len(".framework")] for f in os.listdir(lib) if f.endswith(".framework")}
needed, queue = set(), []
for path in macho_files(pyside):
    if not path.startswith(lib + os.sep):
        queue += linked_frameworks(path)
while queue:
    name = queue.pop()
    if name in needed:
        continue
    if name not in frameworks:
        sys.exit(f"Qt framework {name} is linked but not in the bundle")
    needed.add(name)
    queue += linked_frameworks(os.path.join(lib, f"{name}.framework", name))
for name in frameworks - needed:
    rm(os.path.join(lib, f"{name}.framework"))
print("Kept Qt frameworks:", " ".join(sorted(needed)))
PYEOF
# Thin every universal2 Mach-O in the interpreter tree to arm64.
python3 - "$APP/Contents/Resources/python" <<'PYEOF'
import os, subprocess, sys
for root, dirs, files in os.walk(sys.argv[1]):
    for name in files:
        path = os.path.join(root, name)
        if os.path.islink(path):
            continue
        with open(path, "rb") as f:
            if f.read(4) != bytes.fromhex("cafebabe"):
                continue
        archs = subprocess.run(["lipo", "-archs", path], capture_output=True,
                               text=True).stdout.split()
        if "arm64" in archs and len(archs) > 1:
            subprocess.run(["lipo", "-thin", "arm64", path, "-output", path], check=True)
PYEOF
du -sh "$APP/Contents/Resources/python"

"$PY" -m compileall -q -j 0 "$APP/Contents/Resources/python/lib" >/dev/null || true

# 4. The bundle skeleton: launcher, interpreter symlink, Info.plist, icon.
install -m 755 packaging/macos/launcher.sh "$APP/Contents/MacOS/it-toolbox"
ln -s "../Resources/python/bin/python${PY_MINOR}" "$APP/Contents/MacOS/python"
sed -e "s/@VERSION@/$VERSION/g" -e "s/@SHORT_VERSION@/$SHORT_VERSION/g" \
    packaging/macos/Info.plist.in > "$APP/Contents/Info.plist"
plutil -lint "$APP/Contents/Info.plist"
# Same single canonical icon source the app loads at runtime (app.py).
cp src/it_toolbox/resources/icons/it-toolbox.icns "$APP/Contents/Resources/"

# 5. Ad-hoc sign. Apple Silicon refuses to run unsigned arm64 code at all,
#    and `codesign --deep` only descends into the standard nested-code
#    locations (Frameworks/, PlugIns/...), not a Python tree under
#    Resources/ -- so every Mach-O file (the interpreter, libpython, Qt's
#    frameworks/plugins, compiled extension modules) and every nested
#    bundle (Qt's .frameworks) is signed explicitly first, then the bundle
#    itself. Deepest paths go first: signing a
#    bundle requires everything nested inside it to be signed already.
#    Mach-O files are found by magic number rather than `file`, whose
#    output for any universal2 binary left after 3b is one line per
#    architecture. Ad-hoc only: no Developer ID, so a browser-downloaded
#    .dmg still needs right-click > Open on first launch (see
#    docs/releasing.md).
python3 - "$APP/Contents/Resources/python" <<'PYEOF' | xargs -0 -n 50 codesign --force --sign -
import os, sys
MAGICS = {bytes.fromhex(m) for m in ("feedfacf", "cffaedfe", "cafebabe", "bebafeca")}
targets = []
for root, dirs, files in os.walk(sys.argv[1]):
    targets += [os.path.join(root, d) for d in dirs if d.endswith((".app", ".framework"))]
    for name in files:
        path = os.path.join(root, name)
        if os.path.islink(path):
            continue
        with open(path, "rb") as f:
            if f.read(4) in MAGICS:
                targets.append(path)
# Ties (same depth) are fine in any order -- only nesting matters.
for path in sorted(targets, key=lambda p: p.count(os.sep), reverse=True):
    sys.stdout.write(path + "\0")
PYEOF
codesign --force --sign - "$APP"
codesign --verify --deep --strict --verbose=2 "$APP"

# 6. Wrap it in a compressed .dmg with the usual drag-to-Applications
#    symlink next to the app.
DMG_STAGE="$BUILD_DIR/dmg"
mkdir -p "$DMG_STAGE" dist/packages
cp -R "$APP" "$DMG_STAGE/"
ln -s /Applications "$DMG_STAGE/Applications"
rm -f "$DMG"
hdiutil create -volname "$APP_NAME" -srcfolder "$DMG_STAGE" -ov -format UDZO "$DMG"

echo "Built:"
ls -la dist/packages/
