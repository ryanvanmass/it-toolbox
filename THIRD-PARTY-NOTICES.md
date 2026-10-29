# Third-party notices

IT Toolbox's embedded RDP client links against these libraries at
runtime (see `docs/windows-freerdp-setup.md` for how they're built and
distributed alongside the app). None of their licenses are copyleft, and
none impose any requirement on IT Toolbox's own license — reproduced
here to satisfy each project's attribution terms.

## FreeRDP

`freerdp3.dll`, `freerdp-client3.dll`, `winpr3.dll` — Apache License 2.0.

Copyright the FreeRDP contributors. Full text: <https://github.com/FreeRDP/FreeRDP/blob/master/LICENSE>

## OpenSSL

`libssl-3-x64.dll`, `libcrypto-3-x64.dll`, `legacy.dll` — Apache License 2.0.

Copyright the OpenSSL contributors. Full text: <https://github.com/openssl/openssl/blob/master/LICENSE.txt>

## zlib

`z.dll` — zlib License.

Copyright (C) 1995-2026 Jean-loup Gailly and Mark Adler.

## cJSON

`cjson.dll` — MIT License.

Copyright (c) 2009-2017 Dave Gamble and cJSON contributors.

## Qt / PySide6

IT Toolbox's UI is built on PySide6, the official Python bindings for
Qt. PySide6 itself is LGPLv3 (or a commercial Qt license) — see
<https://www.qt.io/licensing/> for details. IT Toolbox uses PySide6 as
an unmodified, dynamically-linked dependency (installed via `pip`), which
does not require IT Toolbox's own code to be LGPL-licensed.

## Lucide icons

`src/it_toolbox/resources/icons/ui/*.svg` (sidebar, tab and form-control
icons; tinted at runtime by `ui/theme.py`) — ISC License.

Copyright (c) for portions of Lucide are held by Cole Bemis 2013-2022 as
part of Feather (MIT). All other copyright (c) for Lucide are held by
Lucide Contributors 2022.

Permission to use, copy, modify, and/or distribute this software for any
purpose with or without fee is hereby granted, provided that the above
copyright notice and this permission notice appear in all copies.

THE SOFTWARE IS PROVIDED "AS IS" AND THE AUTHOR DISCLAIMS ALL WARRANTIES
WITH REGARD TO THIS SOFTWARE INCLUDING ALL IMPLIED WARRANTIES OF
MERCHANTABILITY AND FITNESS. IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR
ANY SPECIAL, DIRECT, INDIRECT, OR CONSEQUENTIAL DAMAGES OR ANY DAMAGES
WHATSOEVER RESULTING FROM LOSS OF USE, DATA OR PROFITS, WHETHER IN AN
ACTION OF CONTRACT, NEGLIGENCE OR OTHER TORTIOUS ACTION, ARISING OUT OF
OR IN CONNECTION WITH THE USE OR PERFORMANCE OF THIS SOFTWARE.

## Linux tools WSL rootfs (Windows only)

The `it-toolbox-wsl-rootfs-<N>.tar.gz` release asset, which the Windows
build downloads on request from Settings > Linux tools (WSL), is an
unmodified Debian (trixie) base image plus unmodified Debian packages
(libvirt-clients, virtinst, python3-gi, gir1.2-spiceclientglib-2.0,
openssh-client and their dependencies), built by `packaging/wsl/`. Each
package keeps its own license, found in the image under
`/usr/share/doc/<package>/copyright`. Corresponding source for every
package is available from Debian at <https://sources.debian.org> and,
for the exact versions in a given image, <https://snapshot.debian.org>.
