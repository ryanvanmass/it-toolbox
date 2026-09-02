"""Standalone MsTscAx diagnostic — isolates exactly which call fails.

Run directly on Windows (not through the app):
    python scripts\\rdp_activex_diagnostic.py <host> <port> [username] [progid]

e.g.:
    python scripts\\rdp_activex_diagnostic.py 127.0.0.1 12345 myuser
    python scripts\\rdp_activex_diagnostic.py 127.0.0.1 12345 myuser MsRdpClient6NotSafeForScripting

With no [progid], first probes every candidate below (newest first) and
reports which ones this machine actually has registered, then runs the
full property/Connect() sequence against the newest one available.
"""

import sys

from PySide6.QtAxContainer import QAxWidget
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

# "MsTscAx.MsTscAx" is the legacy "safe for scripting" ProgID, originally
# meant for browser-hosted RDP with deliberately restricted capabilities.
# Desktop apps embedding this control programmatically are supposed to use
# one of these full-featured variants instead — trying newest-first since
# older ones may not be registered on a given Windows version.
CANDIDATE_PROGIDS = [
    "MsRdpClient11NotSafeForScripting",
    "MsRdpClient10NotSafeForScripting",
    "MsRdpClient9NotSafeForScripting",
    "MsRdpClient8NotSafeForScripting",
    "MsRdpClient7NotSafeForScripting",
    "MsRdpClient6NotSafeForScripting",
    "MsRdpClient5NotSafeForScripting",
    "MsTscAx.MsTscAx",
]


def probe_progids() -> list[str]:
    available = []
    for progid in CANDIDATE_PROGIDS:
        probe = QAxWidget()
        ok = probe.setControl(progid)
        print(f"   {progid}: {'available' if ok else 'not available'}")
        if ok:
            available.append(progid)
        probe.deleteLater()
    return available


def main() -> None:
    if len(sys.argv) < 3:
        print(f"Usage: python {sys.argv[0]} <host> <port> [username] [progid]")
        sys.exit(1)

    host = sys.argv[1]
    port = int(sys.argv[2])
    username = sys.argv[3] if len(sys.argv) > 3 else None
    forced_progid = sys.argv[4] if len(sys.argv) > 4 else None

    app = QApplication(sys.argv)

    if forced_progid:
        progid = forced_progid
    else:
        print("0. Probing available RDP ActiveX ProgIDs on this machine:")
        available = probe_progids()
        if not available:
            print("   None of the candidates are registered! Falling back to MsTscAx.MsTscAx.")
            progid = "MsTscAx.MsTscAx"
        else:
            progid = available[0]
            print(f"   Using newest available: {progid}")

    widget = QAxWidget()
    widget.resize(1024, 768)
    widget.show()

    exceptions = []
    widget.exception.connect(
        lambda code, source, desc, help: exceptions.append((code, source, desc, help))
    )

    print(f"1. setControl({progid}):", widget.setControl(progid))
    print("   classContext / control:", widget.control())

    print("2. setProperty Server:", widget.setProperty("Server", host))
    print("   readback Server:", widget.property("Server"))

    if username:
        print("3. setProperty UserName:", widget.setProperty("UserName", username))
        print("   readback UserName:", widget.property("UserName"))
    else:
        print("3. (no username given, skipped)")

    print("4. querySubObject AdvancedSettings2:", end=" ")
    advanced = widget.querySubObject("AdvancedSettings2")
    print("None" if advanced is None else "OK")

    if advanced is not None:
        print("5. AdvancedSettings2.setProperty RDPPort:", advanced.setProperty("RDPPort", port))
        print("   readback RDPPort:", advanced.property("RDPPort"))
    else:
        print("5. (no AdvancedSettings2 sub-object, skipped)")

    print("6. setProperty DesktopWidth:", widget.setProperty("DesktopWidth", widget.width()))
    print("7. setProperty DesktopHeight:", widget.setProperty("DesktopHeight", widget.height()))
    print("8. setProperty ColorDepth:", widget.setProperty("ColorDepth", 32))

    print("9. Exceptions raised so far:", exceptions)

    def do_connect():
        print("10. Calling Connect()...")
        widget.dynamicCall("Connect()")
        print("11. Exceptions after Connect():", exceptions)
        QTimer.singleShot(5000, app.quit)

    # Give the control a moment after being shown before connecting.
    QTimer.singleShot(500, do_connect)

    app.exec()
    print("Done. Final exceptions list:", exceptions)


if __name__ == "__main__":
    main()
