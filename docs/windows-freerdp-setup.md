# Getting FreeRDP3 on Windows (for the embedded RDP client)

**Status: unverified.** Everything about the embedded RDP client
(`src/it_toolbox/core/rdp/`) has so far only been built and tested on
Linux, connecting *to* a Windows RDP server. This document is the
starting point for getting it running with Windows as the *client* —
nobody has run it there yet, so treat these steps as a best-effort
starting point to debug from, not a known-working recipe.

## Why there's no simple "just install it"

Unlike Linux, where `freerdp`/`libfreerdp3` is a normal distro package
(already a dependency of the external `xfreerdp` path in
`core/session_launcher.py`), FreeRDP does not publish official prebuilt
Windows DLL packages. The options are:

- **Build it yourself via vcpkg** — the most maintainable path, and
  what's documented below.
- Nightly CI builds from `ci.freerdp.com` — explicitly marked
  "only for testing, might break at any point," and its archived
  artifacts (as of this writing) are just the `.exe` command-line tools,
  not the standalone DLLs this project needs.
- Third-party portable builds (e.g. Cloudbase Solutions' nightly
  `wfreerdp.exe`) — old, and built as a statically-linked executable
  rather than shared DLLs, so there's nothing for `ctypes` to load.

## Building via vcpkg

1. Install a C++ toolchain: Visual Studio 2022 with the "Desktop
   development with C++" workload (Build Tools alone should also work).
2. Get vcpkg:
   ```powershell
   git clone https://github.com/microsoft/vcpkg
   .\vcpkg\bootstrap-vcpkg.bat
   ```
3. Build FreeRDP3 with the client feature, **dynamic** triplet:
   ```powershell
   .\vcpkg\vcpkg.exe install freerdp[client]:x64-windows
   ```
   The triplet matters — `x64-windows` links dynamically and produces the
   `.dll` files this project loads via `ctypes`; `x64-windows-static`
   bakes everything into a single archive with no DLL to load at all.
   Expect this to take a while (it's a real C++ build, not a download).

4. Once it finishes, the DLLs should be under:
   ```
   <vcpkg root>\installed\x64-windows\bin\
   ```
   Confirm `freerdp3.dll` and `freerdp-client3.dll` (or, if vcpkg kept a
   `lib` prefix, `libfreerdp3.dll`/`libfreerdp-client3.dll`) exist there,
   alongside `winpr3.dll` and its OpenSSL/zlib/etc. dependencies.

## Pointing it-toolbox at them

Set the `IT_TOOLBOX_FREERDP_DIR` environment variable to that `bin`
folder before launching the app:

```powershell
$env:IT_TOOLBOX_FREERDP_DIR = "C:\path\to\vcpkg\installed\x64-windows\bin"
python -m it_toolbox
```

`core/rdp/freerdp_client.py` picks this up, adds it to the DLL search
path, and tries both the with- and without-`lib`-prefix names for each
library. If it still fails to load, the error message lists every name
it tried — that's the first thing to report back.

## What almost certainly needs fixing next

This is a prediction, not something already confirmed:

- **The struct bindings in `_freerdp3_bindings.py` were generated from
  Linux headers/ABI.** The struct *shapes* should match (they're the
  same portable C headers), but padding/alignment assumptions
  (`ALIGN64`, `_pack_`) were derived from `ctypeslib2` running against a
  Linux target. If Windows's struct layout differs from what was
  captured, this reproduces the exact class of bug already fixed once in
  this project (the `ContextSize` heap corruption) — possibly
  regenerating bindings from a Windows-side clang/MSVC target will be
  necessary. Don't assume the existing `_freerdp3_bindings.py` is
  correct for Windows without checking.
- `platform.system() == "Windows"` branches in `freerdp_client.py` (DLL
  names, `ctypes.WinDLL` vs `ctypes.CDLL`) are the only Windows-specific
  code written so far — everything else (worker thread, Qt widget, input
  handling) is platform-agnostic Python and *should* work unchanged, but
  hasn't been exercised on Windows at all.
