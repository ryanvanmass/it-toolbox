-- ProFTPD mod_sql's default schema (table/column names mod_sql expects
-- unless SQLUserInfo/SQLGroupInfo say otherwise -- this module doesn't
-- override those, so it must match exactly). Verified end-to-end against
-- a real ProFTPD 1.3.9 instance (AlmaLinux 10 / EPEL) before this was
-- written: FTP and SFTP logins, chroot, and on-disk file ownership all
-- confirmed working against this exact schema.
-- expires_at is this module's own addition, not part of mod_sql's
-- expected schema -- harmless to it either way, since mod_sql selects
-- columns by name, never `SELECT *`. On an already-existing users
-- table from before this column existed, the helper's own
-- _ensure_column adds it via ALTER TABLE instead (CREATE TABLE IF NOT
-- EXISTS, below, only ever helps a *brand new* database).
CREATE TABLE IF NOT EXISTS users (
  userid      TEXT PRIMARY KEY,
  passwd      TEXT NOT NULL,
  uid         INTEGER NOT NULL,
  gid         INTEGER NOT NULL,
  homedir     TEXT NOT NULL,
  shell       TEXT NOT NULL DEFAULT '/sbin/nologin',
  expires_at  TEXT
);

CREATE TABLE IF NOT EXISTS groups (
  groupname TEXT NOT NULL,
  gid       INTEGER NOT NULL,
  members   TEXT
);

-- mod_quotatab_sql's schema (column names/order are fixed by the four
-- SQLNamedQuery directives in proftpd-cockpit.conf.tmpl that reference
-- them -- both must change together). Adapted from the MySQL/Postgres
-- examples in mod_quotatab_sql's own docs (no ENUM/CHECK in SQLite;
-- per_session as 0/1). Only ever populated with quota_type='user' rows
-- by this module (see _set_user_quota) -- group/class/all-wide quotas
-- are a real mod_quotatab feature but not one this module exposes.
CREATE TABLE IF NOT EXISTS quotalimits (
  name              TEXT NOT NULL,
  quota_type        TEXT NOT NULL,
  per_session       INTEGER NOT NULL,
  limit_type        TEXT NOT NULL,
  bytes_in_avail    REAL NOT NULL,
  bytes_out_avail   REAL NOT NULL,
  bytes_xfer_avail  REAL NOT NULL,
  files_in_avail    INTEGER NOT NULL,
  files_out_avail   INTEGER NOT NULL,
  files_xfer_avail  INTEGER NOT NULL
);

-- Populated lazily by mod_quotatab_sql itself (via the insert-quota-tally
-- SQLNamedQuery) the first time a user with a quotalimits row actually
-- transfers something -- this module never writes to this table.
CREATE TABLE IF NOT EXISTS quotatallies (
  name            TEXT NOT NULL,
  quota_type      TEXT NOT NULL,
  bytes_in_used   REAL NOT NULL,
  bytes_out_used  REAL NOT NULL,
  bytes_xfer_used REAL NOT NULL,
  files_in_used   INTEGER NOT NULL,
  files_out_used  INTEGER NOT NULL,
  files_xfer_used INTEGER NOT NULL
);

-- mod_sftp_sql's example schema for SQL-backed SFTP authorized keys
-- (see contrib/mod_sftp_sql.html), with one addition: "key" must hold
-- *only* the raw base64 blob, not a full "type base64 comment"
-- authorized_keys-style line -- confirmed the hard way against a real
-- SFTP login attempt ("error base64-decoding raw key data from
-- database"; mod_sftp_sql's SQLNamedQuery selects this column
-- directly, so it must stay exactly what that query expects). key_type
-- is this module's own addition (mod_sftp_sql doesn't need or read it)
-- purely so _user_public_key can reconstruct a real "ssh-ed25519 AAAA..."
-- line for round-tripping through the UI -- see _set_user_key.
-- FTP has no concept of any of this at all; only mod_sftp's
-- SFTPAuthorizedUserKeys (proftpd-cockpit.conf.tmpl) reads it.
CREATE TABLE IF NOT EXISTS sftpuserkeys (
  name     TEXT NOT NULL,
  key      TEXT NOT NULL,
  key_type TEXT NOT NULL
);

-- Populated by mod_sql's own SQLLog directive (proftpd-cockpit.conf.tmpl)
-- via a plain INSERT SQLNamedQuery -- column order here is exactly the
-- order of meta-sequences in that query ("%u, %m, %f, %b, %{epoch}"),
-- both must change together. This module only ever reads from this
-- table (cmd_list_transfers) and prunes it (MAX_TRANSFER_LOG_ROWS) --
-- ProFTPD itself is the only writer.
CREATE TABLE IF NOT EXISTS transfers (
  username  TEXT NOT NULL,
  command   TEXT NOT NULL,
  path      TEXT NOT NULL,
  bytes     INTEGER NOT NULL,
  timestamp INTEGER NOT NULL
);

-- v5 virtual directories -- each row is a real Linux bind mount (a
-- systemd .mount unit, not just a config entry) of real_path into
-- <homedir>/virtual_name inside a user's chroot. A "shared" directory
-- is just the same real_path bind-mounted for more than one username --
-- no separate concept needed. See _add_virtual_mount/_remove_virtual_mount.
-- group_name (v6) is NULL for a private or v5-auto-shared mount, or
-- the admin-named group (see cmd_create_group) this member's row was
-- created because of -- see _ensure_column's own migration for a
-- database that already has this table without the column.
CREATE TABLE IF NOT EXISTS virtual_mounts (
  username     TEXT NOT NULL,
  virtual_name TEXT NOT NULL,
  real_path    TEXT NOT NULL,
  readonly     INTEGER NOT NULL DEFAULT 0,
  group_name   TEXT
);
