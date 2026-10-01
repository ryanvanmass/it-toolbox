"""One-off diagnostic: dumps raw responses from a real GL.iNet router
for every call glinet_client.py makes, plus a few VPN-related calls it
doesn't yet make (group/config lists, vpn_policy) for investigating
routers using GL.iNet's newer multi-tunnel "VPN Policy" feature.

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
        calls = [
            ("system.get_status()", lambda: api.system.get_status()),
            ("wifi.get_config()", lambda: api.wifi.get_config()),
            # wg_client.get_status()/wg_server.get_status() report a
            # single "active" tunnel's status in pyglinet's documented
            # (single-tunnel) model. Routers with GL.iNet's newer
            # multi-tunnel "VPN Policy" feature (named tunnels, each its
            # own client/server config) may not surface a policy-routed
            # tunnel through this single-status call at all -- the
            # group/config-list and vpn_policy calls below exist to see
            # the real shape of that case.
            ("wg_client.get_status()", lambda: api.wg_client.get_status()),
            ("wg_client.get_group_list()", lambda: api.wg_client.get_group_list()),
            ("wg_client.get_all_config_list()", lambda: api.wg_client.get_all_config_list()),
            ("wg_server.get_status()", lambda: api.wg_server.get_status()),
            ("wg_server.get_peer_list()", lambda: api.wg_server.get_peer_list()),
            ("ovpn_client.get_status()", lambda: api.ovpn_client.get_status()),
            ("ovpn_client.get_group_list()", lambda: api.ovpn_client.get_group_list()),
            ("ovpn_server.get_status()", lambda: api.ovpn_server.get_status()),
            ("vpn_policy.get_global_policy()", lambda: api.vpn_policy.get_global_policy()),
        ]
        for label, call in calls:
            print(f"=== {label} ===")
            try:
                print(json.dumps(call(), indent=2))
            except Exception as exc:  # noqa: BLE001 - want to see every call's outcome, errors included
                print(f"<raised {type(exc).__name__}: {exc}>")
            print()
    finally:
        glinet.logout()
    return 0


if __name__ == "__main__":
    sys.exit(main())
