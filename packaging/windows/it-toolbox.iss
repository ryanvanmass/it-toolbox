; Inno Setup script for it-toolbox. Version is injected at compile time
; via /DMyAppVersion=X.Y.Z (see packaging/windows/build.ps1) -- keeps
; pyproject.toml as the single source of truth for the version number.
#define MyAppName "IT Toolbox"
#define MyAppExeName "it-toolbox.exe"

[Setup]
; Relative paths below (Source:, SetupIconFile, OutputDir) are otherwise
; resolved relative to this .iss file's own directory (packaging\windows),
; not wherever iscc was invoked from -- SourceDir repoints that at the
; repo root, matching where build.ps1 actually puts build\pyembed and
; where the GitHub Actions artifact glob (dist/packages/*.exe) expects
; the output to land. Confirmed necessary the hard way: a real
; windows-latest run failed on the [Files] Source line with "The system
; cannot find the path specified" before this was added.
SourceDir=..\..
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
UninstallDisplayIcon={app}\it-toolbox.ico
OutputDir=dist\packages
OutputBaseFilename=it-toolbox-{#MyAppVersion}-setup
Compression=lzma2
SolidCompression=yes
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64
SetupIconFile=src\it_toolbox\resources\icons\it-toolbox.ico

[Files]
; The embeddable Python distribution, with it-toolbox and its
; dependencies pip-installed into it at build time -- see build.ps1.
; Not a frozen/PyInstaller-style single binary: still a plain,
; unmodified interpreter running normal .py files.
Source: "build\pyembed\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs
; Not referenced by [Files] anywhere above -- pip's own console/gui-script
; launcher stubs don't carry a custom icon, and {app}\Scripts\it-toolbox.exe
; (see the [Icons]/[Run] comment below for why that launcher is avoided
; entirely) isn't used for anything else that would've brought this in.
; The single canonical copy lives inside the package itself so the
; *running app* can also load it at runtime for its own window icon
; (app.py) -- not duplicated, just reused for this installer too.
Source: "src\it_toolbox\resources\icons\it-toolbox.ico"; DestDir: "{app}"

[Icons]
; Deliberately {app}\pythonw.exe -m it_toolbox, not
; {app}\Scripts\{#MyAppExeName} (the [project.gui-scripts] launcher pip
; generated at build time) -- that launcher is a small stub with the
; *absolute* interpreter path used at `pip install` time hardcoded
; inside it (pip/distlib's console/gui-script format is not
; relocatable). build.ps1 installs into build\pyembed on the CI runner,
; then this installer copies that whole tree to wherever the user
; chooses (this .iss doesn't disable the destination-picker page, so
; that's not even always the same DefaultDirName) -- the stub keeps
; pointing at the original, now-nonexistent CI path, which is exactly
; what "Unable to create process using ...build\pyembed\pythonw.exe"
; turned out to mean on a real install. `-m it_toolbox` has no baked-in
; path at all: it resolves the module fresh, every launch, against
; whatever python(w).exe actually ran it.
Name: "{group}\{#MyAppName}"; Filename: "{app}\pythonw.exe"; Parameters: "-m it_toolbox"; IconFilename: "{app}\it-toolbox.ico"; WorkingDir: "{app}"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"

[Run]
Filename: "{app}\pythonw.exe"; Parameters: "-m it_toolbox"; Description: "Launch IT Toolbox"; Flags: nowait postinstall skipifsilent
