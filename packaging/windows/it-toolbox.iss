; Inno Setup script for it-toolbox. Version is injected at compile time
; via /DMyAppVersion=X.Y.Z (see packaging/windows/build.ps1) -- keeps
; pyproject.toml as the single source of truth for the version number.
#define MyAppName "IT Toolbox"
#define MyAppExeName "it-toolbox.exe"

[Setup]
; Fixed GUID -- must never change across releases. Inno Setup uses this
; to detect and replace a prior install on upgrade rather than treating
; every version as a separate, side-by-side app.
AppId={{B1B6F0F0-3B0E-4F3E-9F0F-9C6B3B6E4E10}}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher=IT Toolbox
AppPublisherURL=https://github.com/ryanvanmass/it-toolbox
DefaultDirName={autopf}\IT Toolbox
DefaultGroupName=IT Toolbox
UninstallDisplayIcon={app}\Scripts\{#MyAppExeName}
OutputDir=dist\packages
OutputBaseFilename=it-toolbox-{#MyAppVersion}-setup
Compression=lzma2
SolidCompression=yes
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64
SetupIconFile=packaging\windows\icons\it-toolbox.ico

[Files]
; The embeddable Python distribution, with it-toolbox and its
; dependencies pip-installed into it at build time -- see build.ps1.
; Not a frozen/PyInstaller-style single binary: still a plain,
; unmodified interpreter running normal .py files.
Source: "build\pyembed\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\Scripts\{#MyAppExeName}"; IconFilename: "{app}\Scripts\{#MyAppExeName}"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"

[Run]
Filename: "{app}\Scripts\{#MyAppExeName}"; Description: "Launch IT Toolbox"; Flags: nowait postinstall skipifsilent
