<#
.SYNOPSIS
    Downloads the prebuilt FreeRDP3 Windows DLLs the embedded RDP client
    needs, unpacks them into a per-user app-data folder, and points
    IT_TOOLBOX_FREERDP_DIR at that folder - so a client machine doesn't
    need to build FreeRDP itself via vcpkg (see
    docs/windows-freerdp-setup.md for that path, which is how these DLLs
    were originally produced).

.DESCRIPTION
    1. Downloads the DLL bundle zip from $Source.
    2. Extracts it to a temp folder, then flattens every *.dll found
       (recursively, in case the zip has a subfolder) into
       %LOCALAPPDATA%\it-toolbox\freerdp - matching the app's own
       platformdirs.user_data_dir("it-toolbox") convention for local
       state (see core/settings.py).
    3. Sets IT_TOOLBOX_FREERDP_DIR to that folder as a persistent
       per-user environment variable (takes effect in new terminals/
       processes), and also in the current session so it works
       immediately without reopening PowerShell.

.PARAMETER Source
    URL to download the DLL bundle zip from.

.PARAMETER Force
    Re-download and overwrite even if the destination folder already
    looks populated.

.EXAMPLE
    .\scripts\fetch_freerdp_windows.ps1
#>

param(
    [string]$Source = "https://edmi.app/public.php/dav/files/Disf3pj2CbZsHnp/?accept=zip",
    [switch]$Force
)

$ErrorActionPreference = "Stop"

$DestDir = Join-Path $env:LOCALAPPDATA "it-toolbox\freerdp"
# The set actually required by core/rdp/freerdp_client.py's DLL loader -
# used only to warn if the bundle looks incomplete, not to block on it.
$RequiredDlls = @(
    "freerdp3.dll", "freerdp-client3.dll", "winpr3.dll",
    "libcrypto-3-x64.dll", "libssl-3-x64.dll", "legacy.dll",
    "cjson.dll", "z.dll"
)

if (-not $Force -and (Test-Path (Join-Path $DestDir "freerdp3.dll"))) {
    Write-Output "Already present at $DestDir (use -Force to re-download). Just (re)pointing IT_TOOLBOX_FREERDP_DIR at it."
} else {
    $TempDir = Join-Path $env:TEMP "it-toolbox-freerdp-fetch"
    $ZipPath = Join-Path $env:TEMP "it-toolbox-freerdp.zip"
    if (Test-Path $TempDir) { Remove-Item -Recurse -Force $TempDir }
    New-Item -ItemType Directory -Force -Path $TempDir | Out-Null

    Write-Output "Downloading $Source ..."
    Invoke-WebRequest -Uri $Source -OutFile $ZipPath -UseBasicParsing

    Write-Output "Extracting..."
    Expand-Archive -Path $ZipPath -DestinationPath $TempDir -Force

    $DllFiles = Get-ChildItem -Path $TempDir -Filter "*.dll" -Recurse
    if ($DllFiles.Count -eq 0) {
        Remove-Item -Force $ZipPath -ErrorAction SilentlyContinue
        Remove-Item -Recurse -Force $TempDir -ErrorAction SilentlyContinue
        throw "No .dll files found in the downloaded archive - check that $Source still points at the right bundle."
    }

    New-Item -ItemType Directory -Force -Path $DestDir | Out-Null
    foreach ($dll in $DllFiles) {
        Copy-Item -Path $dll.FullName -Destination (Join-Path $DestDir $dll.Name) -Force
    }

    Remove-Item -Force $ZipPath -ErrorAction SilentlyContinue
    Remove-Item -Recurse -Force $TempDir -ErrorAction SilentlyContinue

    Write-Output "Placed $($DllFiles.Count) DLL(s) in $DestDir"

    $missing = $RequiredDlls | Where-Object { -not (Test-Path (Join-Path $DestDir $_)) }
    if ($missing.Count -gt 0) {
        Write-Warning "Bundle is missing expected file(s): $($missing -join ', ') - the app may still fail to load FreeRDP."
    }
}

[Environment]::SetEnvironmentVariable("IT_TOOLBOX_FREERDP_DIR", $DestDir, "User")
$env:IT_TOOLBOX_FREERDP_DIR = $DestDir

Write-Output "IT_TOOLBOX_FREERDP_DIR set to $DestDir (persisted for this user; new terminals will pick it up automatically)."
