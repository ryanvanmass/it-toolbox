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

## Clipboard sync — local→remote text, re-attempted with real reference source (2026-09-09)

The first attempt at this feature (below, kept for history) was reverted
after local→remote paste never worked and the root cause was never found.
This session re-implemented it — local→remote text only, remote→local
still out of scope — grounded in the real, current FreeRDP source fetched
directly from `github.com/FreeRDP/FreeRDP` (the header structs, the
channel-plugin internals, and — the piece unavailable last time — the X11
reference client, `client/X11/xf_cliprdr.c`) rather than guesswork. That
surfaced three concrete requirements the previous attempt likely got wrong
or never knew about:

1. **`cliprdr` is a static channel and must be explicitly loaded.**
   `freerdp_client_load_channels(instance)` — confirmed exported from
   `libfreerdp-client3.so.3` via `nm -D` against this project's real
   installed copy — must be called after settings are configured, before
   `freerdp_connect()`. Nothing in this codebase called it before now;
   `disp` (a DVC) never needed it, which is exactly what this doc's own
   "Dynamic resolution resizing" section above already flagged as a gap.
2. **`RedirectClipboard` and `ClipboardFeatureMask` settings**, resolved
   by name at runtime via the existing `_settings_key_for_name()` helper
   (same treatment as `DesktopWidth`/`DesktopHeight` — neither has a
   stable literal in a checked-in header). Verified against this
   machine's real installed `libfreerdp3.so.3`: `"FreeRDP_RedirectClipboard"`
   resolves to `4800`, `"FreeRDP_ClipboardFeatureMask"` to `4801`.
   `ClipboardFeatureMask` is already FreeRDP's own compiled-in default for
   a fresh settings object; set explicitly anyway.
3. **`ClientCapabilities` must be sent explicitly, with `CB_USE_LONG_FORMAT_NAMES`
   requested, in response to `MonitorReady`** — confirmed by reading
   `xf_cliprdr_monitor_ready()`, which always does exactly this before
   sending its format list. `cliprdr_main.c`'s own fallback path forces
   `useLongFormatNames = FALSE` whenever the server never sends its own
   capabilities PDU (legal and common — the protocol comment there
   explicitly says the server capabilities PDU is optional), so skipping
   this call is a real, previously-untested-but-now-confirmed way for the
   first attempt's symptom (`ClientFormatList` "succeeds" but the server
   never follows up with a `ServerFormatDataRequest`) to happen.

New module `core/rdp/cliprdr.py` (mirrors `disp.py`'s shape): hand-written
`CliprdrClientContext` + `CLIPRDR_HEADER`/`CLIPRDR_CAPABILITIES`/
`CLIPRDR_FORMAT_LIST`/`CLIPRDR_FORMAT_DATA_REQUEST`/`CLIPRDR_FORMAT_DATA_RESPONSE`
structs, sourced from the real current headers, not memory. `ClipboardChannel`
binds on the `"cliprdr"` `ChannelConnected` event (confirmed still its
literal short name, no DVC-style full-name gotcha, same as before), sends
capabilities + an initial format list on `MonitorReady`, and responds to
`ServerFormatDataRequest` with the current local clipboard text
(UTF-16LE-encoded `CF_UNICODETEXT`, matching the exact field-population
requirements confirmed by reading `cliprdr_client_format_data_response`'s
own serializer). `ServerFormatList` is intentionally left unimplemented —
this client only ever announces its own clipboard, never reads the
server's.

Wired through `FreeRdpSession.announce_clipboard_text()` →
`RdpSessionWorker.send_clipboard_text()` (queued the same way mouse/
keyboard/resize events are) → `RdpWidget`, which connects
`QApplication.clipboard().dataChanged` to push every local copy, plus one
push on `_on_connected` so a session that connects with existing clipboard
content doesn't need a fresh copy first. `close_session()` disconnects
that signal — a new cleanup requirement, since `QApplication.clipboard()`
is a process-wide singleton that outlives any single tab, unlike every
other signal source this widget listens to.

**Known, accepted v1 behavior**: with multiple RDP tabs open, every local
copy is broadcast to every open session (not scoped to the focused tab) —
no existing precedent in this codebase scopes clipboard by tab/focus.

**Verified end-to-end against a real server** (2026-09-09, Windows Server
2025, provided by the user for exactly this test): connected via the
`core/rdp/freerdp_client.py` CLI layer directly (`WLOG_LEVEL=DEBUG` set),
drove the session with synthetic input to open Notepad, called
`announce_clipboard_text("hello from it-toolbox clipboard test")`, then
sent a Ctrl+V keystroke into the remote session. The full protocol
round trip fired exactly as designed:
`cliprdr_process_format_data_request: ServerFormatDataRequest (0x0000000d
[CF_UNICODETEXT])` → our `ClientFormatDataResponse` → `cliprdr_packet_send:
Cliprdr Sending (82 bytes)` (37 characters, UTF-16LE + null terminator +
the 6-byte header — the exact expected size) — and a captured frame
confirmed the text actually appeared in Notepad, character-for-character.
This is precisely the step that never fired in the first attempt
(`ServerFormatDataRequest` never arriving after `ClientFormatList`) — the
three fixes above (explicit channel load, the two settings, and sending
`ClientCapabilities` with `CB_USE_LONG_FORMAT_NAMES` before the format
list) resolved it. Multi-tab clipboard scoping (see above) and
remote→local are still unverified/out of scope, but local→remote text is
now confirmed working, not just protocol-plausible.

### First attempt — reverted, kept for history

A full bidirectional clipboard bridge was built and partially verified,
then reverted at the user's request rather than shipped half-working:

- **Remote→local text sync worked**, verified twice against the real
  remote server with fresh (non-stale) data each time. (Not reimplemented
  in the 2026-09-09 rework above — still explicitly out of scope.)
- **Local→remote (pasting local content into the remote session) did
  not work**, and the root cause was never found at the time. The
  client-side `ClientFormatList` call returned success (`0`/`CHANNEL_RC_OK`),
  but the server never followed up with a `ServerFormatDataRequest` —
  timing and widget-focus mixups were both ruled out. The two guesses
  recorded as untested — a `CLIPRDR_FORMAT_LIST` serialization issue, or
  a missing explicit `CB_USE_LONG_FORMAT_NAMES` capability negotiation —
  are addressed directly above; the second is now confirmed as a real,
  necessary step via the reference client, not just a guess.
- One thing confirmed *not* the bug, still true: `cliprdr` is a static
  channel and its `ChannelConnected` name genuinely is `"cliprdr"`
  (unlike `disp`) — channel binding itself worked fine on the first try,
  both times.

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
entirely when a fixed size is configured, since `paintEvent` scales the
image to fit the widget regardless of its native resolution (see
"Letterboxing" below for how that scaling preserves aspect ratio rather
than stretching). This sidesteps the round trip for the common case
rather than fixing it. "Match window size" (`None`) keeps today's
default behavior.

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

## Fixed resolution connects but renders nothing (2026-09-08, resolved)

Along the way to the `freerdp_settings_get_key_for_name()` fix above, an
intermediate version (the discarded `freerdp_client_settings_parse_command_line()`
approach) connected cleanly against a real GCP VM — TLS, `gdi_init_ex`,
all dynamic virtual channels loading, no errors anywhere in the log —
but rendered nothing. No frame ever painted.

Two theories were checked and ruled out:

- That the server was rendering through the newer Graphics Pipeline
  extension (`rdpgfx`, which our code never reads from; only
  `update->EndPaint` is hooked) instead of the classic bitmap-update
  path. Ruled out: `FreeRDP_SupportGraphicsPipeline` defaults to `0`
  (confirmed via `freerdp_settings_get_key_for_name()` +
  `freerdp_settings_get_bool()`) and nothing in `_configure_settings()`
  enables it, so the server has no capability signal from us to switch
  to it regardless of what channels load locally.
- That user testing directly against this same GCP VM confirmed
  disambiguates the scope: "Match window size" mode (never calls
  `_apply_desktop_size()` at all) renders the real remote desktop fine
  against this VM — so the blank-screen bug was specific to the
  resolution feature, not a pre-existing general issue with the embedded
  client over the IAP tunnel.

That second finding narrowed it down to something specific to
`_apply_desktop_size()` itself, and the only candidate left standing was
the thing that had been dismissed as "harmless" one section up: the
discarded command-line-parser approach's call to
`prepare_default_settings()`, which explicitly invokes
`freerdp_set_connection_type(settings, CONNECTION_TYPE_AUTODETECT)`.
The *raw integer* `connection type` value looked identical before/after
in the earlier `.rdp`-file-dump diff (both `7`), which is what led to
ruling it out — but a bare, freshly-created context reporting `7` as its
compiled-in default doesn't necessarily mean the *derived* bools
(`NetworkAutoDetect`/`BandwidthAutoDetect`) are also set the way an
explicit `freerdp_set_connection_type()` call would set them. The
working theory (not independently re-verified at the settings level,
but consistent with everything observed) is that explicitly invoking
connection-type auto-detection put the server into a bandwidth-probing
sequence this minimal client never responds to, stalling the first
frame indefinitely with no error on either side — while a bare
default's matching *integer* alone was never enough to trigger that
sequence.

**Confirmed fixed**: switching to `freerdp_settings_get_key_for_name()` +
direct `freerdp_settings_set_uint32()` calls (zero side effects,
verified earlier in this doc) resolved it — a real GCP VM connection
with a fixed resolution selected now renders correctly. This is also
the concrete lesson that motivated dropping the command-line-parser
approach in the first place, independent of this bug: any code path
that goes through FreeRDP's higher-level parsers (`.rdp`-file buffer,
command line) risks additional settings changing as a side effect
beyond what a diff of the *documented*/`.rdp`-representable fields can
catch, even when those side effects look inert on the surface.

## Letterboxing instead of stretching (2026-09-09)

`RdpWidget.paintEvent` used to always `drawImage(self.rect(), ...)` —
stretching the received image to exactly fill the widget, distorting it
whenever the widget's aspect ratio didn't match the image's. That's
harmless in "Match window size" mode (the two are always kept equal by
`resizeEvent`), but with a *fixed* resolution selected, the widget can
be any shape — a 1920×1080 (16:9) session in a narrower or squarer app
window would render visibly squashed.

`_scaled_image_rect()` now computes the largest rect, centered in the
widget, that fits `self._image` at its own aspect ratio (`QSize.scaled(
..., Qt.AspectRatioMode.KeepAspectRatio)`), and `paintEvent` fills the
leftover space with solid black bars rather than stretching into it.
`_remote_pos()` (widget-space → remote-desktop-space, used by every
mouse event handler) had to change alongside it — it was written
assuming the image always covers the *entire* widget rect, which is no
longer true. It now maps through the same letterboxed rect, and clamps
clicks that land in the bars themselves to the nearest image edge
instead of producing a negative or out-of-range remote coordinate.

## Tab-stealing and unset keyboard layout (2026-09-10, resolved)

A user report of inconsistent behavior — Tab appearing to do nothing, and
Shift+key combos for punctuation like `"`/`:` producing wrong or no
characters — turned out to be two independent bugs:

1. **Qt's own focus-traversal was stealing Tab/Shift+Tab.**
   `QWidget::event()` intercepts these to cycle keyboard focus between
   widgets before `keyPressEvent()` ever runs — `setFocusPolicy(StrongFocus)`
   doesn't disable that. Once Tab moved local Qt focus away from the
   `RdpWidget`, every subsequent keystroke (Shift+key combos included)
   went to whatever local widget picked up focus instead, until a click
   brought focus back — explaining the "inconsistent" pattern, since it
   depends on what else was focusable nearby. Fixed with an `event()`
   override intercepting Tab/`Key_Backtab` KeyPress before Qt's default
   handling runs; confirmed for real via a test that fails without the
   fix and passes with it (not just reasoned). `scancodes.py` also had no
   mapping for `Key_Backtab` at all (Shift+Tab reports as this distinct
   key, not `Key_Tab` + a modifier) — added, mapped to the same scancode
   as plain Tab. The identical fix was applied to `SpiceWidget`, which
   shares the exact same input-handling shape and vulnerability.
2. **`KeyboardLayout` was never set, defaulting to 0** — confirmed
   against FreeRDP's own `libfreerdp/core/settings.c`: every other
   keyboard-related setting (`KeyboardType`/`SubType`/`FunctionKey`) gets
   a sane compiled-in default, but `KeyboardLayout` doesn't. A real
   client is expected to set this itself — confirmed by reading the
   actual X11 reference client (`client/X11/xf_keyboard.c`'s
   `xf_keyboard_init`), which auto-detects a layout from XKB/system
   locale and falls back to `ENGLISH_UNITED_STATES` (`0x0409`,
   `freerdp/locale/locale.h`) only if that fails. Left at 0, the server
   has no declared layout to interpret our scancodes against — plausible
   root cause for exactly this shape of bug (basic letters/numbers stay
   broadly consistent across layouts, punctuation varies a lot more).
   Since `scancodes.py`'s table is a fixed US QWERTY Set-1 mapping, not
   layout-adaptive, `freerdp_client.py` now hardcodes
   `KeyboardLayout = 0x0409` unconditionally in `_configure_settings` —
   the correct match for what this client actually sends, not a
   placeholder. Verified the setting round-trips through a real
   `FreeRdpSession` context (get/set via the real installed
   `libfreerdp3`), but — like everything else in this file needing a
   live server — the actual fix for real Shift+punctuation typing still
   needs to be confirmed against one.

## Keyboard layout is now a Settings override (2026-09-10)

The hardcoded `KeyboardLayout = 0x0409` (English (US)) fix above was
confirmed live against the original VM, but a second VM hit the exact
same Shift+punctuation symptom despite it — the declared layout is only
useful if the *server* actually has it installed, and a non-English-
language Windows image may simply not have English (US) available.
There's no way for the client to know what's installed on an arbitrary
target server ahead of time, so this can't be auto-detected/fixed once
and for all the way the original bug could.

Made it a Settings option instead (`settings.load_rdp_keyboard_layout`,
default unchanged at English (US)/`0x0409`), threaded through
`RdpWidget` -> `RdpSessionWorker` -> `FreeRdpSession.connect` ->
`_configure_settings`, the identical shape `desktop_size` already uses.
A "RDP Keyboard Layout" section (10 common-layout presets) lets a user
hitting this on a specific VM pick the layout that's actually installed
there instead.

## Shift+symbol in console apps: scancode+Shift vs Unicode input (2026-09-10)

Live investigation of the "second VM" report above ruled out a layout
mismatch entirely: the declared layout (English (US)) matched the VM's
own Windows language settings exactly, and Windows' own Remote Desktop
Connection (`mstsc`) typed Shift+symbol correctly against the very same
VM. So it was a bug in this client specifically, not a server-config
issue -- but every character/scancode/modifier looked individually
correct, which didn't fit until one more fact came in: **it worked when
typed into a GUI text field within the RDP session, but not into a
PowerShell/console prompt in that same session.**

That's the real signature. A GUI text control gets an already-resolved
character via `WM_CHAR` -- generated upstream in Windows' input
pipeline. A console app (PowerShell, cmd) instead resolves the raw
Shift+scancode pair itself, via its own lower-level keyboard-state
translation, reading each key as a separate synthetic event -- and is
evidently less forgiving about it than the WM_CHAR path GUI controls
already get for free.

`scancodes.py`'s own module docstring already said one possible fix:
"[Unicode input] sidesteps scancode/shift mapping entirely and works
correctly across keyboard layouts" -- but no printable character ever
actually used that path, because every one (letters, digits,
punctuation) had its own `SCANCODES` entry, so `_forward_key_event`
always took the scancode branch first. **Tried and reverted**:
restructured it to prefer sending the already-resolved Unicode
character for any printable key with no Ctrl/Alt held. Live-tested
result: this broke typing in PowerShell/cmd *entirely*, not just
Shift+symbol -- RDP's Unicode keyboard input synthesizes a Windows
`VK_PACKET` key event, and raw console input (unlike GUI controls,
which handle it fine via `WM_CHAR`) is a documented weak spot for
`VK_PACKET`-based synthetic keystrokes; it isn't reliably recognized
as a real keystroke at all there. So scancode has to stay the primary
path for anything with a `SCANCODES` entry -- back to this file's
original shape, Shift+symbol-in-console bug included and still
unresolved. The real fix needs to stay within scancode-based input,
not swap the transport.

## Shift+symbol in console apps: the actual fix (2026-09-10)

Root cause, finally pinned down from a real `IT_TOOLBOX_LOG_LEVEL=DEBUG`
capture of the live session: Qt (at least on Windows) reports Shift+
symbol keys -- Shift+`;` -> `:`, Shift+`1` -> `!`, and so on -- as their
own distinct `Key_*` constants (`Key_Colon`, `Key_Exclam`, ...), *not*
the unshifted key (`Key_Semicolon`, `Key_1`, ...) with a Shift modifier
set. None of those distinct constants had a `SCANCODES` entry, so every
one of them has *always* fallen through to `send_key_unicode()` -- fine
in a GUI text field, but the exact `VK_PACKET`-based path confirmed
broken in a Windows console in the entry above. This explains the whole
shape of the bug: plain letters and unshifted symbols (real `SCANCODES`
entries) always worked in both places; every Shift-row symbol (no
entry) only ever worked where Unicode input happens to work -- GUI
controls, not consoles.

Fix: added `SCANCODES` entries for all the Shift-row symbol keys
(`Key_Exclam` through `Key_Question` -- see `scancodes.py`), each
mapped to the *same physical scancode* as its unshifted key. Shift's
own press/release is already sent as a separate scancode event (visible
in the capture, right before each of these), so this uses the exact
scancode+Shift mechanism that was already proven working for everything
else -- no unicode/`VK_PACKET` involved at all for these keys anymore.

## What's still open

- Confirm the fix above against the actual reporting VM's PowerShell
  prompt -- strongly evidenced from a real live capture (the exact
  `Key_Colon`/`Key_QuoteDbl`/etc. codes were seen going through the
  unicode path), reasoned + unit-tested, but the live keystroke-level
  confirmation still needs to come from the user.
- The keyboard-layout Settings override (two sections up) turned out
  not to be what actually needed fixing for this specific report, but
  is still worth keeping for a case where a target VM's declared
  layout genuinely doesn't match what's installed there.
- The MD4/legacy-provider gap noted above, if it turns out to matter
  for a real target server (e.g. one that needs NTLM fallback rather
  than NLA, or RC4-based licensing/security).
- Clipboard sync, local→remote text (see above) — implemented and verified
  end-to-end against a real server on `feature/rdp-clipboard-local-to-remote`.
  Remote→local (and non-text formats/files) still out of scope.
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
