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

## Windows verification (2026-09-03)

All of the above is now also verified on Windows, end to end, against a
real RDP server (this machine's own Remote Desktop service, `localhost`,
via a dedicated local test account):

1. **FreeRDP3 built via vcpkg**, `freerdp[client]:x64-windows` —
   `freerdp3.dll`, `freerdp-client3.dll`, `winpr3.dll` all produced under
   `<vcpkg root>\installed\x64-windows\bin`. Confirms
   `docs/windows-freerdp-setup.md`'s vcpkg recipe works as written.
   Prerequisites (VS Build Tools C++ workload, a real Python — the
   Windows Store's `python.exe` app-execution-alias stub is not one and
   errors on `pip`) had to be installed first; neither was present by
   default.
2. **Struct bindings are correct on Windows as-is** —
   `_freerdp3_bindings.py`, generated from Linux/LP64 headers, needed
   *no* regeneration. Ran the CLI harness's connect/disconnect and
   `--capture-frame` smoke tests (`core/rdp/freerdp_client.py`'s
   `_cli_main`) directly against `localhost:3389`: clean connect,
   disconnect, and a well-formed 1024x768 frame with real pixel
   diversity, no crash, no corruption. This was the main open risk in
   this doc's previous version — resolved.
3. **The actual `RdpWidget` (not just the bare CLI) verified too** — a
   throwaway offscreen Qt script instantiated `RdpWidget` for real,
   waited for `frame_ready`, and `grab()`'d the painted widget: a crisp,
   correctly-rendered capture of the remote Windows login screen came
   back (confirms `PIXEL_FORMAT_BGRX32` → `QImage.Format_RGB32` still
   lines up correctly on Windows, and `paintEvent`/`update()` work under
   the offscreen QPA platform there). One gotcha specific to this test
   harness: `grab()` right after `_image` is first set returns a blank
   frame — `update()` only *schedules* a repaint, so a few more
   `processEvents()` calls are needed before the backing store is
   actually painted. Not an app bug, just a smoke-test timing detail
   worth remembering if reproducing this.
4. Benign warning worth knowing about, not a blocker: this vcpkg build
   of OpenSSL doesn't load its legacy provider, so `winpr` logs `Failed
   to initialize digest md4` and FreeRDP warns that "NTLM support" and
   RC4-based licensing/security aren't available. Connect/auth/render
   all still worked in this testing (NLA doesn't need MD4), but if NTLM
   fallback auth or certain older security modes matter for real target
   servers, that's the thing to revisit.

5. **Bidirectional input on Windows, verified too.** Drove real Qt
   events at a live `RdpWidget` (via `QTest`, not calling
   `worker.send_*` directly, so `_remote_pos` scaling and scancode
   lookup were exercised for real): a mouse click on the login screen's
   "Other user" tile produced a genuine server-side UI transition (a
   "sign in anyway?" dialog, since another session was already active),
   confirmed by screenshot. Then, keyboard-only (no mouse), an Enter
   keypress on that dialog's default-focused "No" button triggered a
   clean, verified round-trip: `RdpSessionWorker.signals.disconnected`
   fired and the server logged `ERRINFO_LOGOFF_BY_USER` — proof the
   keystroke actually reached the server and was acted on, not just
   that no exception was raised locally.

## Verified against a genuinely remote server too (2026-09-03)

Everything above was re-run against a real, separate machine on the LAN
(a Windows Server 2025 Datacenter Evaluation VM, not `localhost`), to
rule out anything that only happened to work over loopback:

- Connect/disconnect smoke test and `--capture-frame`: clean, no
  errors. (The first captured frame was the OOBE loading screen, not a
  bug — a real network login sequence takes longer to reach
  `LOGON_MSG_SESSION_CONTINUE` than loopback did, so a widget-level test
  that waits for more frames is the better way to check rendering, not
  the CLI harness's single-first-frame capture.)
- `RdpWidget`, given more time to actually finish logging in: 15 frames
  received, ending on a crisp, fully correct render of the remote
  machine's first-login OOBE screen ("Send diagnostic data to
  Microsoft") — legible text, no artifacts, over a real network path
  (this machine and the target are both on `192.168.2.0/24`, confirmed
  via `arp -a`/`Test-NetConnection`, not adjacent processes on one
  host).
- Mouse input over that same real network connection: a simulated click
  on the OOBE screen's "Accept" button round-tripped to the server and
  actually advanced the session — the next captured frame is the live
  Windows desktop (wallpaper + Recycle Bin), confirming input isn't
  loopback-only either.

This was the last item on the "what's still open" list. Everything the
previous version of this doc flagged as unverified on Windows —
DLL loading, struct bindings, GDI rendering, the Qt widget, mouse/
keyboard input, and now a genuinely remote server — has been checked.

## Dynamic resolution resizing (2026-09-03)

`RdpWidget` now asks the server to resize the remote desktop when the
widget itself is resized, instead of just stretching whatever fixed-size
bitmap it already had — implemented and verified against the real
remote server, both shrinking and growing, with each resize producing a
genuine fresh render at the new resolution (taskbar/desktop correctly
re-laid-out, not a stretched or cropped old frame).

- New module `core/rdp/disp.py`: hand-declared `DispClientContext` +
  `DISPLAY_CONTROL_MONITOR_LAYOUT` (`freerdp/client/disp.h` +
  `freerdp/channels/disp.h`). Much smaller than cliprdr's bindings —
  one struct, no embedded pointers, no array-lifetime concerns.
- `FreeRdpSession.request_resize(width, height)` calls `gdi_resize()`
  (resizes the local framebuffer) *and* `DisplayChannel.request_resize`
  (asks the server) together — deliberately gated on the disp channel
  actually being bound first. Calling `gdi_resize()` alone without
  server cooperation was tried and produces a cropped/corrupted display
  (the local buffer's dimensions desync from what the server is
  actually sending) — worse than doing nothing, so `request_resize` is
  a no-op until the channel is live.
- **Important lesson, reusable for any future DVC work**: the
  `ChannelConnected` pubsub event's `name` field is *not* always the
  short name a header's `_CHANNEL_NAME` macro suggests. `cliprdr` (a
  static channel) does report literally `"cliprdr"`, but `disp` (a
  Dynamic Virtual Channel) reports its full DVC name,
  `"Microsoft::Windows::RDS::DisplayControl"` — confirmed by tracing
  every `ChannelConnected` event against the real server. Matching only
  `"disp"` silently never bound the channel; the code now matches
  either name. If a future channel doesn't seem to bind, trace the
  actual names first rather than assuming the short one.
- `RdpWidget.resizeEvent` debounces via a 250ms single-shot `QTimer` —
  restarted on every resize, only actually sent once the size has
  settled — so a window drag doesn't fire a resize request per pixel.
- Settings: `SupportDisplayControl` (5185) and `DynamicResolutionUpdate`
  (1558), both bool, set alongside the existing TLS/NLA/RDP-security
  bools in `_configure_settings`. No `freerdp_client_load_channels`
  call needed here (unlike cliprdr) — disp is a DVC and loads
  automatically, confirmed via the "Loading Dynamic Virtual Channel
  disp" log line already visible in every session before this feature
  existed.

## Fixed: wrong initial resolution when opened straight into a maximized/fullscreen window (2026-09-04)

Reported bug: a fresh RDP connection sometimes opened at the wrong
(FreeRDP-default) resolution when the app window was already maximized/
fullscreened, staying wrong until the user forced *any* further resize
(e.g. nudging the window) — at which point it snapped to the correct
size.

Root cause, found by tracing the exact guard the "Dynamic resolution
resizing" section above already flagged as intentional: `request_resize`
is a no-op whenever `disp` (a Dynamic Virtual Channel, negotiated
*after* the main handshake completes) hasn't bound yet, specifically to
avoid the local-buffer/server desync described above. That guard is
correct, but the *dropped* request was never remembered or retried —
so the very first resize-to-fit (`RdpWidget`'s initial `resizeEvent`
firing while the widget lays out into an already-maximized window,
almost immediately after `RdpSessionWorker.start()`) reliably lost the
race against `disp`'s negotiation and vanished for good. Every
*subsequent* resize succeeded because by then the channel had finished
binding — exactly matching "stays wrong until I force a resize."

Fix: `FreeRdpSession` now remembers a resize requested before `disp` is
bound (`self._pending_resize`) and replays it automatically the moment
`_on_channel_connected` binds the channel, instead of requiring a
second, user-triggered resize to ever reach the server. `request_resize`
itself is unchanged in the already-bound case.

Verified via `tests/core/test_freerdp_client.py` — the first pytest
coverage for `core/rdp/` itself (previous note above about "no pytest
coverage for core/rdp/" is now stale for this one file). Exercises the
real `FreeRdpSession._on_channel_connected`/`request_resize` control
flow with real `ChannelConnectedEventArgs`/`DispClientContext` ctypes
structures, stubbing out only the parts that need a live connection
(`gdi_resize`, `SendMonitorLayout`) via `_apply_resize`. Skips cleanly
(`allow_module_level=True`) on a machine without libfreerdp3 installed,
same concern as every other native-library import in this project.
**Verified against a real server (2026-09-04)**, once one became
available: reproduced the exact race directly against `core/rdp/`
(request a resize before `pump_once()` has run at all, confirm it's
held as `_pending_resize` and only reaches the server once `disp` binds
~1-1.5s later) and through the real production path (`ConnectionManagerView`'s
manual-connection flow, a real `MainWindow` shown maximized, a real
tab-embedded `RdpWidget`) — both confirm the pending resize is now
correctly replayed and the final frame lands at the exact requested
size, with no manual resize needed.

### Follow-up: whitespace around the (correctly-sized) image

After the fix above, the *stretching* was gone, but a real Windows
retest turned up a new symptom: whitespace along the bottom/right of an
otherwise correctly-rendered session — i.e. the image itself was fine,
but `RdpWidget` was rendering smaller than the tab actually gives it.

Root cause: `RdpWidget.sizeHint()` returns the *live remote image's*
native pixel size, and the widget never declared a size policy —
QWidget's default is `Preferred`/`Preferred` in both directions, which
lets a layout shrink a widget down to its sizeHint instead of always
filling available space. `TerminalWidget` (SSH's tab-page widget, never
reported to have this problem) sets no custom sizeHint and no size
policy either, so it just takes whatever the tab gives it — `RdpWidget`
is the one widget in this app that overrides sizeHint, and until now
the one place that needed an explicit `Expanding` policy to stop that
hint from ever shrinking it below the tab's real content area (the
displayed image already stretches to fill self.rect() regardless of
its native size — see paintEvent — so there was never a reason for the
widget to render any smaller than its container allows).

Fix: `RdpWidget.__init__` now calls
`setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)`.
sizeHint() is left as-is (still useful context for a layout choosing
between competing hints) — only the "shrink to fit the hint" behavior
is what needed to stop.

**Not yet re-verified against a real server** — the exact trigger
condition for the shrink (almost certainly the very first, smaller
default-resolution frame landing before the resize race above
resolves, and some container in the real Windows app honoring that
transient sizeHint) didn't reproduce in this environment's Linux/X11
layout stack, so this fix is reasoned from the size-policy mismatch
rather than a locally-reproduced before/after. Needs the same
maximized-window retest as above, watching specifically for whitespace
this time.

## Clipboard sync — attempted, reverted, worth knowing before retrying

A full bidirectional clipboard bridge (`core/rdp/cliprdr.py`,
`CliprdrClientContext` + the `CLIPRDR_FORMAT_LIST`/`FORMAT_DATA_*`
message structs, wired through `RdpSessionWorker`/`RdpWidget` to Qt's
`QClipboard`) was built and partially verified, then **reverted** at the
user's request rather than shipped half-working. Do this over with
better tooling before re-attempting rather than repeating the same
trial-and-error:

- **Remote→local text sync worked**, verified twice against the real
  remote server with fresh (non-stale) data each time.
- **Local→remote (pasting local content into the remote session) did
  not work**, and the root cause was never found. The client-side
  `ClientFormatList` call returns success (`0`/`CHANNEL_RC_OK`), but the
  server never follows up with a `ServerFormatDataRequest` — ruled out
  timing (tested with a 6s wait) and widget-focus mixups (confirmed via
  screenshot the target window stayed empty). Best remaining guesses,
  untested: something in the `CLIPRDR_FORMAT_LIST` wire serialization
  (the `formats` array / `dataLen` handling), or a capability-
  negotiation default (`CB_USE_LONG_FORMAT_NAMES`) that needs setting
  explicitly via `ClientCapabilities` rather than relying on whatever
  FreeRDP defaults to unset.
- Getting further would need either a packet capture (Wireshark on the
  `cliprdr` static channel) to see the actual wire bytes, or reading
  FreeRDP's own `client/cliprdr_main.c` reference implementation (not
  vendored in this repo — only headers were available), rather than
  more guessing from the header alone.
- One thing confirmed *not* the bug, worth not re-litigating: `cliprdr`
  is a static channel and its `ChannelConnected` name genuinely is
  `"cliprdr"` (unlike `disp`, see above) — channel binding itself
  worked fine on the first try.

## What's still open

- The MD4/legacy-provider gap noted above, if it turns out to matter
  for a real target server (e.g. one that needs NTLM fallback rather
  than NLA, or RC4-based licensing/security).
- Clipboard sync (see above) — reverted, not on this branch.
- The pending-resize race fix (2026-09-04) is now verified against a
  real server; its whitespace follow-up fix (same date, size policy)
  is not — needs a real Windows maximized-window retest.
- Everything else verified so far has been manual smoke-testing (the
  CLI harness and throwaway Qt scripts), not automated tests — pytest
  coverage for `core/rdp/` itself is now limited to the one fix above
  (`tests/core/test_freerdp_client.py`); the rest of this area still
  needs a live server to test against.

## How to pick this up

1. `git checkout feature/embedded-rdp-libfreerdp`, `git pull`.
2. Get FreeRDP3 DLLs built per `docs/windows-freerdp-setup.md` (now
   confirmed working) and `IT_TOOLBOX_FREERDP_DIR` pointed at them.
3. At this point the embedded RDP client is verified working on both
   Linux and Windows, over loopback and a real network. What's left is
   normal hardening/polish work rather than open unknowns — e.g. the
   MD4 gap above, broader manual testing against different Windows
   versions/RDP server configurations, or deciding whether this is
   ready to replace the external `mstsc.exe`/`xfreerdp` path as the
   default.

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
