# Bundled cockpit-proftpd helper

A copy of `helper/` from the user's cockpit-proftpd Cockpit module
(github.com/ryanvanmass/cockpit-proftpd, commit ca1e921), used by the
General Tools ProFTPD Manager (core/proftpd_manager.py).

The manager always prefers the helper the cockpit-proftpd package
installed on the server (/usr/libexec/cockpit-proftpd/), so both UIs run
the exact same code against the same database and config. This copy is
only installed (to /usr/local/libexec/it-toolbox-proftpd/) on a server
that doesn't have the Cockpit module, when the user asks for it.

When the helper changes upstream, copy the three files over again
unmodified.
