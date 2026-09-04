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
