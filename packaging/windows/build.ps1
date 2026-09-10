# Builds an it-toolbox Windows installer, bundling Python's official
# "embeddable" distribution with it-toolbox and its dependencies
# pip-installed into it at build time -- see docs/releasing.md for why
# (same philosophy as the Linux vendored-venv: deterministic, built once,
# no network needed at install time; deliberately not a PyInstaller/
# Nuitka freeze). Requires: python (>=3.11, for building the wheel --
# separate from the embeddable one this script downloads for the actual
# shipped app), Inno Setup's iscc.exe on PATH. Runnable standalone, same
# convention as scripts/release.sh and packaging/linux/build.sh, and is
# exactly what .github/workflows/package-windows.yml runs in CI.
$ErrorActionPreference = "Stop"
Set-Location "$PSScriptRoot\..\.."  # repo root

$Version = (python -c "import tomllib; print(tomllib.load(open('pyproject.toml','rb'))['project']['version'])")
$PyVersion = "3.12.8"  # embeddable Python version -- bump deliberately, independent of it-toolbox's own version
$EmbedUrl = "https://www.python.org/ftp/python/$PyVersion/python-$PyVersion-embed-amd64.zip"
$GetPipUrl = "https://bootstrap.pypa.io/get-pip.py"
$PyEmbedDir = "build\pyembed"

Write-Host "Building it-toolbox $Version for Windows..."

# 1. Build a wheel of it-toolbox itself.
python -m pip install --upgrade build
Remove-Item -ErrorAction SilentlyContinue dist\it_toolbox-*.whl
python -m build --wheel

# 2. Download and unpack the embeddable Python distribution.
Remove-Item -Recurse -Force -ErrorAction SilentlyContinue $PyEmbedDir
New-Item -ItemType Directory -Force -Path $PyEmbedDir | Out-Null
Invoke-WebRequest -Uri $EmbedUrl -OutFile "build\python-embed.zip"
Expand-Archive -Path "build\python-embed.zip" -DestinationPath $PyEmbedDir

# 3. Enable site-packages -- embeddable distributions ship with it
#    commented out in the ._pth file by default, which would otherwise
#    make pip-installed packages invisible to the interpreter.
$PthFile = Get-ChildItem "$PyEmbedDir\python3*._pth" | Select-Object -First 1
if (-not $PthFile) {
    throw "Could not find the embeddable Python's ._pth file under $PyEmbedDir"
}
(Get-Content $PthFile.FullName) -replace '^#import site', 'import site' | Set-Content $PthFile.FullName

# 4. Bootstrap pip (embeddable distributions don't include it) and
#    install our wheel + its dependencies into this same tree.
Invoke-WebRequest -Uri $GetPipUrl -OutFile "build\get-pip.py"
& "$PyEmbedDir\python.exe" "build\get-pip.py"
$Wheel = Get-ChildItem "dist\it_toolbox-$Version-py3-none-any.whl"
& "$PyEmbedDir\python.exe" -m pip install $Wheel.FullName

# 5. Build the installer with Inno Setup.
New-Item -ItemType Directory -Force -Path "dist\packages" | Out-Null
iscc "packaging\windows\it-toolbox.iss" "/DMyAppVersion=$Version"

Write-Host "Built:"
Get-ChildItem "dist\packages"
