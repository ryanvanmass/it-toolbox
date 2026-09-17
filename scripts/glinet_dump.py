"""One-off diagnostic: dumps the raw system.get_status() and
wifi.get_config() responses from a real GL.iNet router.

`glinet_client.py`'s field-name assumptions were originally best-effort
from `python-glinet`'s own README/bundled api_description.json example
output, then corrected against a real router during manual testing (see
docs/glinet-dashboard-status.md's "Field-mapping caveat" section) — this
script exists to ground any *further* correction the same way, instead
of guessing at field names again.

This is a DEV-ONLY tool, run against a real router by hand while
debugging a field-mapping mismatch. It is not imported by the app and
needs `python-glinet` installed (`pip install python-glinet`), same as
the dashboard feature itself.

Usage:
    python3 scripts/glinet_dump.py [URL] [USERNAME]

    python3 scripts/glinet_dump.py https://192.168.8.1/rpc root

Defaults to https://192.168.8.1/rpc / root if omitted. Prompts for the
password interactively (never pass it on the command line — it would
end up in shell history and `ps` output).
"""

import json
import sys

from pyglinet import GlInet


def main() -> int:
    url = sys.argv[1] if len(sys.argv) > 1 else "https://192.168.8.1/rpc"
    username = sys.argv[2] if len(sys.argv) > 2 else "root"

    glinet = GlInet(url=url, username=username, keep_alive=False, verify_ssl_certificate=False)
    glinet.login()
    try:
        api = glinet.get_api_client()
        print("=== system.get_status() ===")
        print(json.dumps(api.system.get_status(), indent=2))
        print()
        print("=== wifi.get_config() ===")
        print(json.dumps(api.wifi.get_config(), indent=2))
    finally:
        glinet.logout()
    return 0


if __name__ == "__main__":
    sys.exit(main())
