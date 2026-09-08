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

### Manual "Refresh Resolution" (2026-09-08)

Added a "Refresh Resolution" action on a session tab's right-click menu
(`RdpWidget.refresh_resolution()`) — re-sends the current widget size to
the server even though it hasn't changed, for when the remote
resolution has drifted out of sync without a real resize event to
trigger a fix on its own.

### Automatic post-connect trigger — attempted, reverted

Also tried firing that same refresh automatically once, shortly after
connecting, for when the server's *initial* resolution is already out
of sync. Reverted at the user's request after it didn't visibly work in
real usage; worth recording so a retry doesn't repeat the same path:

1. First attempt: fire it a fixed N seconds after `connected` (tried 3s,
   then 30s, then 5s). Real-usage report each time: the resolution never
   visibly updated — not occasionally late, just not working.
2. Root cause, from this file's own "Dynamic resolution resizing"
   section above: `request_resize()` is a **documented no-op** until the
   `disp` channel finishes binding (`self.display._context is None`
   guard in `freerdp_client.py`) — a *separate* negotiation that happens
   after `connected` already fired, with no fixed or guaranteed timing.
   A flat delay from `connected` was always going to be a guess.
3. Fix attempted: an actual `on_display_channel_ready` hook on
   `FreeRdpSession` (mirroring `on_frame`), threaded up through
   `RdpSessionWorker`/`RdpWidget` and wired directly to
   `refresh_resolution()` — event-driven instead of a guessed delay.
   Reasoned correctly from the documented gating above, but never
   confirmed live before being reverted.
4. **Reverted** rather than keep debugging blind — this repo's dev
   environment can't test against a real RDP server, and three rounds
   of "should work" not panning out in real usage was reason enough to
   stop guessing. The manual action above still works standalone and
   was kept.

If picking this up again: the event-driven `on_display_channel_ready`
approach (point 3) is still the technically correct fix for the
documented no-op gating — it just needs someone who can verify live
against a real server, ideally adding a log line at the point
`on_display_channel_ready` fires so a session's real console output
confirms whether/when the channel actually binds, rather than inferring
it indirectly from whether the resolution visibly changed.

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

## Fixed resolution option, for GCP/IAP-tunnel connections (2026-09-08)

A user report of 5-10s render lag after a window drag/resize turned out
to be specific to GCP VM connections — these route through
`core/iap_tunnel.py`/`core/tunnel_session.py`'s `BackgroundTunnel` (a
WebSocket-relayed IAP tunnel), not a plain TCP connection, and every
resize (match-window-size mode restarts a request on every
`resizeEvent`) pays that tunnel's round trip. A direct connection
doesn't show the lag; a real GCP VM does.

Rather than trying to make that round trip faster (its own investigation
— the tunnel's frame/ACK protocol was read through and matches gcloud's
own `start-iap-tunnel` implementation, so there's no obvious protocol
bug to fix there), Settings now offers a **fixed resolution** option for
embedded RDP sessions (`core/settings.py`'s
`load_default_rdp_resolution()`/`save_default_rdp_resolution()`,
Settings page's new "RDP Display" section). Picking one of the presets
(1280×720 through 3840×2160) requests that resolution once at connect
and never again — `RdpWidget.resizeEvent` skips the resize-debounce
entirely when a fixed size is configured, since `paintEvent` already
stretches the image to fill the widget regardless of its native
resolution. This sidesteps the round trip for the common case rather
than fixing it. "Match window size" (`None`) keeps today's default
behavior.

The fixed size is applied via
`FreeRdpSession.connect(..., desktop_size=(w, h))` →
`freerdp_client._apply_desktop_size()`, which sets
`FreeRDP_DesktopWidth`/`FreeRDP_DesktopHeight` directly via
`freerdp_settings_set_uint32()` — but with the numeric key for each
looked up at runtime via `freerdp_settings_get_key_for_name()`
(`freerdp/settings.h`, a genuine public/exported API) rather than a
hand-picked literal, unlike the settings in `_configure_settings()`
(`SETTING_SERVER_PORT` etc., copied from a real generated header).
`DesktopWidth`/`DesktopHeight`'s numeric keys aren't stable literals
safe to transcribe by hand: FreeRDP's upstream
`include/config/settings_keys.h.in` is a bare CMake
`@SETTINGS_KEYS_UINT32@` template with no static enum checked into the
source tree at any version checked (3.0.0 through 3.31.1), generated at
build time in a way this project can't reproduce without a full FreeRDP
build. `freerdp_settings_get_key_for_name()` sidesteps that permanently
by resolving the name against whatever the *actual running library*
says it is — verified empirically against this machine's real installed
`libfreerdp3.so.3` (3.31.1): looking up `"FreeRDP_ServerPort"` this way
returns 19, matching `SETTING_SERVER_PORT` above exactly, confirming the
lookup is trustworthy and not just plausible.

Two earlier approaches were tried and discarded before landing here —
worth recording so neither gets retried:

1. `freerdp_client_settings_parse_connection_file_buffer()` (the
   `.rdp`-file parser). Looked correct in isolation — a standalone check
   confirmed a buffer with just `desktopwidth`/`desktopheight` lines set
   exactly those two fields — but real connections with a fixed
   resolution then failed to connect with no error surfaced. Root cause,
   found by diffing a `freerdp_client_settings_write_connection_file()`
   dump of the settings object before and after calling it: that parser
   allocates a whole `rdpFile` struct with ~50 fields of its *own*
   defaults (compression, connection type, authentication level, CredSSP
   support, ...) and applies **all** of them to the target settings, not
   just the two lines actually in the buffer — silently stomping the
   NLA/security settings `_configure_settings()` had already set. The
   one-off verification script that "confirmed" this approach only
   checked the two fields it cared about, not the full settings surface,
   which is exactly how this got missed initially.
2. `freerdp_client_settings_parse_command_line()` with
   `["it-toolbox", "/w:N", "/h:N"]` — fixed the NLA-stomping problem
   (each `/w`/`/h` handler is a single targeted
   `freerdp_settings_set_uint32()` call, verified against FreeRDP's own
   `cmdline.c`), and was re-verified clean against the real library the
   same before/after-diffing way, this time also checking the
   NLA/TLS/RDP-security bools directly (not just the `.rdp`-representable
   fields, which don't cover those). But it still indirectly triggers
   `prepare_default_settings()` setting `ConnectionType` to
   `CONNECTION_TYPE_AUTODETECT` as a side effect of no other
   network/gfx/rfx/bpp flag being present — turned out to be harmless in
   practice (`AUTODETECT` is FreeRDP's own compiled-in default for a
   bare context anyway, confirmed empirically), but still an unnecessary
   side channel to depend on when a direct settings call now does the
   whole job with zero side effects at all.

Lesson for next time: when verifying an isolated settings/protocol
change, diff the *entire* observable settings surface before vs. after,
not just the specific fields the change was meant to touch — a narrow
check can pass while a broader side effect still breaks the real thing
it feeds into.

## Fixed resolution connects but renders nothing (2026-09-08, open)

With the `freerdp_settings_get_key_for_name()` fix above in place, a
real GCP VM connection with a fixed resolution selected now completes
the *protocol* handshake cleanly — TLS, `gdi_init_ex` (local
`PIXEL_FORMAT_BGRX32`, remote `PIXEL_FORMAT_BGRA32`), all four dynamic
virtual channels (`ainput`, `rdpgfx`, `disp`, `rdpsnd`) loading, no
errors anywhere in the log — but the tab stays blank. No frame ever
paints.

Leading theory going in — that the server was rendering through the
newer Graphics Pipeline extension (`rdpgfx`, which our code never reads
from; only `update->EndPaint` is hooked) instead of the classic
bitmap-update path — was **ruled out**: `FreeRDP_SupportGraphicsPipeline`
defaults to `0` (confirmed via the same `freerdp_settings_get_key_for_name()`
+ `freerdp_settings_get_bool()` combination) and nothing in
`_configure_settings()` enables it, so the server has no capability
signal from us to switch to it regardless of what channels load
locally.

Also checked and ruled out: the `ConnectionType = CONNECTION_TYPE_AUTODETECT`
side effect from the discarded command-line-parser approach above isn't
the differentiator either — a bare, freshly-created context (no
command-line parsing at all, i.e. exactly what "Match window size" mode
uses) already reports `connection type:i:7` (`CONNECTION_TYPE_AUTODETECT`)
as FreeRDP's own compiled-in default, confirmed via the
`freerdp_client_settings_write_connection_file()` dump technique above.
So both modes get `AUTODETECT` regardless of the resolution fix, ruling
it out as something introduced by this feature specifically.

**Not yet resolved.** Still open: whether "Match window size" mode
(never calls `_apply_desktop_size` at all) also renders blank against
this same GCP VM — if so, the blank-screen bug is unrelated to the
resolution feature entirely and pre-dates it (this embedded RDP client
has only ever been verified end-to-end against a LAN test server per
the sections above, never through the actual IAP tunnel to a real GCP
VM) — versus something specific to setting `DesktopWidth`/`DesktopHeight`
still being the differentiator despite the settings-level checks coming
back clean.

## What's still open

- The MD4/legacy-provider gap noted above, if it turns out to matter
  for a real target server (e.g. one that needs NTLM fallback rather
  than NLA, or RC4-based licensing/security).
- Clipboard sync (see above) — reverted, not on this branch.
- Everything verified so far has been manual smoke-testing (the CLI
  harness and throwaway Qt scripts), not automated tests — there's
  still no pytest coverage for `core/rdp/` itself (only the
  `main_view.py` wiring is covered), consistent with how this area
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
