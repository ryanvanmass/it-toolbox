# Embedded RDP client — status and handoff

Branch: `feature/embedded-rdp-libfreerdp`. Read this file first if you're
picking this work up in a new session (e.g. on a different machine) —
it's written so a fresh session with no prior conversation history can
get oriented from the repo alone.

## What this branch is

IT Toolbox's Connection Manager originally launched RDP sessions
externally (`mstsc.exe`/`xfreerdp`), because a Windows ActiveX
(`MsTscAx`) embedding attempt failed on the user's test machine — no
modern `MsRdpClient` ProgID was registered there, and that's not
something fixable from app code. This branch is a from-scratch embedded
RDP client built on `libfreerdp3` via raw `ctypes` (no Python FreeRDP
binding exists), replacing the ActiveX approach entirely and giving
IT Toolbox's own cross-platform embedded RDP widget instead of shelling
out to the OS's client.

## What's done and verified (Linux only, so far)

All of this has been tested against a real, reachable Windows RDP
server, from Linux as the client:

1. **ctypes bindings** (`src/it_toolbox/core/rdp/_freerdp3_bindings.py`,
   auto-generated — do not hand-edit, see
   `scripts/generate_freerdp_bindings.py`). Struct layout (70+ field
   `rdp_freerdp`/`rdp_context`/`rdp_client_context` etc.) comes straight
   from FreeRDP's own headers via `clang2py`/ctypeslib2, not
   hand-transcription — that struct is actively evolving and hand-typing
   it is exactly how you get silent memory corruption from one misplaced
   field.
2. **Connection lifecycle** (`core/rdp/freerdp_client.py`:
   `connect_and_disconnect`, `FreeRdpSession`). Found and fixed a real
   heap-corruption bug here: `entry_points.ContextSize` must be
   `sizeof(rdpClientContext)`, not `0` — FreeRDP's virtual-channel setup
   writes past the end of an undersized buffer, reproduced as `double
   free or corruption (!prev)` before the fix.
3. **GDI software rendering** (`FreeRdpSession.get_frame()`, hooked via
   `PostConnect`→`gdi_init` and `update->EndPaint`). Pixel format
   `PIXEL_FORMAT_BGRX32` was deliberately chosen to match Qt's
   `QImage.Format_RGB32` byte-for-byte on little-endian, so frames are
   wrapped with zero pixel conversion.
4. **Qt widget** (`src/it_toolbox/widgets/rdp_widget.py` +
   `core/rdp/rdp_session_worker.py`, the thread/signal bridge — mirrors
   `core/tunnel_session.py`'s split for the IAP tunnel). Renders live in
   an actual `QWidget`, confirmed via `grab()` + pixel-diversity checks
   and visual inspection.
5. **Input** (`core/rdp/scancodes.py` + `FreeRdpSession.send_*` +
   `RdpWidget` mouse/key event handlers). Mouse move/click/wheel and
   keyboard (unicode text + a hand-written PC/AT scancode table for
   control keys) both confirmed working — typed a command into a remote
   PowerShell window and watched it execute.
6. **Wired into the real app** (`modules/connection_manager/ui/main_view.py`).
   "Connect via RDP" now prompts for a password (masked, not persisted —
   no keyring integration in this app) and embeds `RdpWidget` in a
   session tab exactly like SSH already embeds `TerminalWidget`, instead
   of calling `session_launcher.launch_rdp`. `RdpWidget.finished` mirrors
   `TerminalWidget.finished` and drives the same
   `_on_disconnect_requested` teardown path.

Full commit-by-commit detail is in `git log` on this branch — each
commit message documents what was proven and how.

## What's NOT done: the entire Windows side

Nothing above has run on Windows. Concretely open:

1. **FreeRDP3 isn't installed anywhere on Windows yet.** There's no
   official prebuilt DLL package — see `docs/windows-freerdp-setup.md`
   for what was researched (vcpkg build, dynamic `x64-windows` triplet,
   `IT_TOOLBOX_FREERDP_DIR` env var the app now reads). **This has never
   actually been run** — the vcpkg build itself, the resulting DLL
   names, whether the app can load them — all unverified. Start here.
2. **The struct bindings may not be valid on Windows.**
   `_freerdp3_bindings.py` was generated against a Linux x86_64 target.
   Windows uses LLP64 (`long` is 4 bytes, vs 8 on Linux); if any FreeRDP
   struct field is a bare `long` rather than a fixed-width type
   (`UINT32`/`INT64`/etc.), the generated field size is wrong for
   Windows. This is the same *class* of bug as the `ContextSize` heap
   corruption already found and fixed on Linux — don't assume the
   existing bindings are correct on Windows without checking. If
   anything crashes with corruption-looking symptoms
   (`double free`, `access violation`, garbage frame data), suspect this
   first. Fix, if needed: regenerate with
   `scripts/generate_freerdp_bindings.py` pointed at a Windows-side
   clang install/headers, or a MinGW cross-compile target — not
   attempted yet.
3. **Everything else** (worker thread, Qt widget, input handling,
   `main_view.py` wiring) is plain Python/Qt with no Windows-specific
   code — it *should* work unchanged once the DLLs load and (1)/(2) are
   sorted, but "should" is doing real work in that sentence until it's
   actually run once.

## How to pick this up

1. `git checkout feature/embedded-rdp-libfreerdp`, `git pull`.
2. Work through `docs/windows-freerdp-setup.md` to get FreeRDP3 DLLs
   built and discoverable.
3. Try the app (`python -m it_toolbox`, right-click a VM →
   "Connect via RDP") and report back *exactly* what happens — an import
   error, a DLL-not-found, a crash, a garbled frame, or (hopefully) it
   just working. Whatever breaks first is the next thing to fix; this
   doc's job was to make sure that debugging starts from real signal
   instead of from scratch.

## Repo conventions worth knowing before touching this code

- Qt-free core in `core/rdp/`, Qt-aware code in `widgets/` — mirrors how
  `core/iap_tunnel.py` (Qt-free, CLI-testable) vs the app's Qt layer is
  split elsewhere in this project. Keep new RDP logic on the correct
  side of that line.
- Don't hand-edit `_freerdp3_bindings.py` — regenerate it via
  `scripts/generate_freerdp_bindings.py` (its docstring has full setup
  instructions) if headers change or a Windows regeneration is needed.
- Full test suite: `QT_QPA_PLATFORM=offscreen python -m pytest -q` (all
  visual verification in this project goes through offscreen rendering —
  never a real screenshot tool, which once accidentally captured private
  desktop content; that mistake must not repeat).
