# FTP/SFTP client — status and handoff

Branch: `claude/vm-ftp-sftp-client-u8kbkc`. Read this file first if you're
picking this work up in a new session — it's written so a fresh session
with no prior conversation history can get oriented from the repo alone.

## What this branch is

Adds a FileZilla-style dual-pane FTP/SFTP client, reachable via
"Connect via SFTP"/"Connect via FTP" on Connection Manager's tree, same
place "Connect via SSH"/"Connect via RDP" already live:

- **Manual connections** (`modules/connection_manager/models.py`'s
  `ManualConnection`) now accept `kind="sftp"` or `kind="ftp"` alongside
  the existing `"rdp"`/`"ssh"` — the tree's existing generic
  `f"Connect via {kind.upper()}"` context-menu action needed no change
  at all to pick these up.
- **GCP Compute instances** get an explicit new "Connect via SFTP"
  action, tunneled through the same IAP/`BackgroundTunnel` machinery
  `_start_session_from_instance`'s SSH path already uses (SFTP is just
  an SSH subsystem, so it reuses the SSH port).
- **QEMU/libvirt guest VMs do not get this** — `QemuVm` has no tracked
  guest IP address anywhere in the codebase (SPICE is reached through
  the libvirt host, not a guest IP), so there's no host to dial. Adding
  that is future work; see "What's NOT done" below.

## Architecture

1. **`core/ftp_client.py`** — `SftpSession` (paramiko, real SSH2 SFTP —
   this app's SSH terminal instead shells out to the system `ssh`
   binary, but a real protocol library is needed here for structured
   listing/progress) and `FtpSession` (stdlib `ftplib`, MLSD-based
   listing — no LIST-text-parsing fallback for pre-MLSD servers). Both
   expose the same duck-typed interface (`connect`/`home_dir`/
   `list_dir`/`upload`/`download`/`mkdir`/`rmdir`/`remove`/`rename`/
   `close`, plus a `kind` class attribute) with no shared base class,
   matching how `TerminalWidget`/`RdpWidget`/`SpiceWidget` already
   coexist in this codebase. One session object lives for the whole
   life of one browser tab (unlike `core/rclone_client.py`, which
   shells out fresh per call because the `rclone` CLI itself is
   stateless) — every method is a plain blocking call, meant to run on
   a background thread via `core/async_utils.run_in_background`.
   SFTP host-key handling mirrors `_embed_ssh`'s GCP-vs-Manual split:
   `skip_host_key_check=True` (IAP-tunneled) trusts-and-never-persists
   via `paramiko.AutoAddPolicy`, otherwise it loads
   `~/.ssh/known_hosts` and rejects an unrecognized host outright
   (`paramiko.RejectPolicy`) — a real external host still gets real
   host-key protection, same as manual SSH connections do today.
2. **`widgets/ftp_browser_widget.py`** — `FtpBrowserWidget`: a local
   pane and a remote pane (`_FilePaneWidget`, a small shared view for
   both — path bar, Up/Refresh, a table), plus a transfer queue table
   underneath. Double-click, or the context menu's Download/Upload,
   moves a file straight into the *other* pane's current directory (no
   per-file save dialog) — that dual-pane semantic is what
   distinguishes this from the existing single-pane browsers
   (`rclone_browser_widget.py`, `bucket_browser_widget.py`). Transfers
   are queued and run one at a time on a background thread (a single
   SFTP/FTP connection isn't safe for concurrent calls); a small
   `_TransferSignals` QObject bridges each transfer's progress callback
   (invoked on that background thread) back onto the Qt main thread for
   the progress column.
3. **`modules/connection_manager/ui/ftp_credentials_dialog.py`** —
   `FtpCredentialsDialog`: username + password fields always; SFTP also
   gets an optional private-key-path + passphrase field. Leaving both
   password and key blank isn't an error — paramiko's `allow_agent`/
   `look_for_keys` are always on, so it falls back to the SSH agent or
   `~/.ssh/id_ed25519`/`id_rsa`. A "remember password" checkbox is
   shown except for the GCP-instance path (there's no `ManualConnection`
   there to persist it onto — same "never persisted" treatment GCP's
   own RDP password prompt already gets).
4. **Password storage** — `ManualConnection.password_encrypted` (new
   field, SFTP/FTP only) is age-encrypted to the user's own SSH key via
   two new `core/settings.py` functions,
   `encrypt_manual_connection_password`/`decrypt_manual_connection_password`,
   which are exact copies of the existing
   `encrypt_glinet_password`/`decrypt_glinet_password` shape (same
   `SecretDecryptionError` fallback-to-prompt behavior). RDP/SSH manual
   connections are untouched — they still never persist a password.
5. **`manage_manual_connections_dialog.py`** — the kind combo now
   offers SFTP/FTP (default ports 22/21) alongside RDP/SSH, with a
   password field that only appears for those two kinds, shaped exactly
   like `manage_glinet_hosts_dialog.py`'s own "blank = keep existing"
   password field.

## What's done and verified

Every new/changed unit is covered:

- `tests/core/test_ftp_client.py` (15 tests) — `SftpSession`/`FtpSession`
  against mocked `paramiko`/`ftplib`, plus `list_local_dir`.
- `tests/widgets/test_ftp_browser_widget.py` (8 tests) — connect, folder
  navigation, download-on-double-click, upload-on-double-click, new
  folder, recursive remote delete, `close_session`, FTP-hides-
  permissions-column.
- `tests/modules/connection_manager/test_main_view_sessions.py` — 8 new
  tests covering manual SFTP/FTP connect (including the stored-password
  path, the fall-back-to-prompt-on-decrypt-failure path, and
  remember-password persistence) and the GCP-instance SFTP path (tunnel
  wiring, credentials dialog with the remember checkbox hidden).

Beyond mocked unit tests, this was verified **live against two real
local servers** stood up in the dev sandbox for exactly this purpose
(no mocking of paramiko/ftplib in these runs):

- A real `sshd` (OpenSSH, key-based auth, `internal-sftp` subsystem) —
  `SftpSession` connected, listed a real directory, downloaded a real
  file, uploaded a real file (with progress callback firing), created a
  directory, renamed a file, and deleted both, all through the actual
  paramiko SFTP wire protocol. `FtpBrowserWidget` was then driven
  end-to-end through a real Qt event loop against this same server:
  connect → populate the remote pane → double-click a local file →
  confirmed the transfer queue reached "Done".
- A real `pyftpdlib` FTP server (password auth) — `FtpSession`
  connected, listed via real MLSD, downloaded, uploaded (progress
  callback fired with real byte counts), created a directory, renamed,
  and deleted, all through the actual FTP wire protocol.

Both temporary servers were torn down after verification; nothing from
them is part of the repo or the test suite (the unit tests mock
paramiko/ftplib as usual, for a hermetic, fast suite).

Full existing suite still passes with these changes in place (verified
by running the whole `tests/` tree, excluding three tests that fail in
this sandbox for reasons unrelated to this change — see below).

## What's NOT done / known limitations

- **No QEMU/libvirt guest SFTP** — `QemuVm` has no guest IP anywhere in
  this codebase (see the models.py comment on `QemuVm`); adding one
  would need real discovery (e.g. via the guest agent's
  `virsh domifaddr`) that's out of scope here.
- **No recursive folder transfers** — uploading/downloading a directory
  isn't implemented; only individual files. Recursive *delete* of a
  remote directory is implemented (walks and removes children first).
- **No drag-and-drop** between panes or from the OS file manager — only
  double-click and the context menu's Download/Upload actions.
- **FTP has no `chmod`** — plain FTP has no standardized permissions
  primitive (`SITE CHMOD` is a common but non-universal extension), so
  "Change Permissions…" is only offered for SFTP.
- **No known_hosts pinning for GCP-tunneled SFTP** — same trade-off
  `_embed_ssh` already makes for GCP/IAP SSH terminals: the ephemeral
  local tunnel port has no meaningful host identity to pin, so that
  path always trusts-and-moves-on rather than checking a host key.

## Known pre-existing sandbox limitations (not related to this change)

Running the full `pytest` suite in this dev sandbox surfaces three
unrelated failures, confirmed via `git stash` to exist on `main`
before this branch's changes:

- `tests/test_app.py`, `tests/test_main.py`, and any test importing
  `RdpWidget` fail to collect — `libfreerdp-client3.so.3` isn't
  installed in this sandbox.
- A handful of `test_upload_ssh_key_*` tests in
  `test_main_view_sessions.py` hang when run together as a group (each
  passes individually) — pre-existing, unrelated to this change.
- `test_fetch_freerdp_runs_script_and_re_checks_status_on_success` fails
  on Linux because it simulates `platform_system="Windows"` and hits a
  real `os.add_dll_directory` call, which only exists on Windows.

## How to pick this up

1. `git checkout claude/vm-ftp-sftp-client-u8kbkc`, `git pull`.
2. `pip install -e ".[dev]"` (pulls in the new `paramiko` dependency).
3. Right-click a Manual Connection with `kind="sftp"`/`"ftp"` (add one
   via "Manage Connections…"), or a GCP instance's new "Connect via
   SFTP" action, to try the real UI against a real server.
4. If picking up "recursive folder transfers" or "drag-and-drop" next,
   both are called out as deliberately out of scope above — they're the
   natural next milestones if this needs to get closer to FileZilla's
   full feature set.
