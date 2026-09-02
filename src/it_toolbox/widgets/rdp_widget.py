"""Embedded RDP session via Microsoft's RDP ActiveX control (MsTscAx).

Windows-only — QtAxContainer (Qt's ActiveX container support) doesn't exist
on other platforms, and ships with Windows itself (MSTSCAX.DLL, the same
control behind mstsc.exe), so nothing extra to install.

UNVERIFIED: this has not been exercised against a real RDP session. The
property/method/event names below (Server, UserName, AdvancedSettings2.
RDPPort, Connect(), OnDisconnected) are long-documented, stable MsTscAx
interface members, but the exact behavior through PySide6's QAxWidget —
signal naming for COM events in particular — needs verification on a real
Windows machine before this can be trusted. Expect to debug this against
an actual connection.
"""

import sys

if sys.platform != "win32":
    raise ImportError("RdpWidget is only available on Windows (uses QtAxContainer/ActiveX)")

from PySide6.QtAxContainer import QAxWidget  # noqa: E402
from PySide6.QtCore import Signal  # noqa: E402


class RdpWidget(QAxWidget):
    disconnected = Signal()

    def __init__(
        self, host: str, port: int, username: str | None = None, parent=None
    ) -> None:
        super().__init__(parent)

        if not self.setControl("MsTscAx.MsTscAx"):
            raise RuntimeError(
                "Failed to load the RDP ActiveX control (MsTscAx.MsTscAx). It "
                "ships with Windows' own Remote Desktop client — confirm "
                "mstsc.exe works on this machine."
            )

        self.setProperty("Server", host)
        if username:
            self.setProperty("UserName", username)

        # RDPPort lives under the AdvancedSettings2 sub-object rather than
        # as a top-level property — needed since we're always connecting to
        # a local IAP tunnel port, never the default 3389.
        advanced_settings = self.querySubObject("AdvancedSettings2")
        if advanced_settings is not None:
            advanced_settings.setProperty("RDPPort", port)

        # PySide6 exposes COM events as Qt signals named after the event.
        # This attribute may not exist under this exact name/casing —
        # the first thing to check if embedding silently doesn't connect.
        on_disconnected = getattr(self, "OnDisconnected", None)
        if on_disconnected is not None:
            on_disconnected.connect(self._on_disconnected)

        self.dynamicCall("Connect()")

    def _on_disconnected(self, *args) -> None:
        self.disconnected.emit()

    def close_session(self) -> None:
        try:
            self.dynamicCall("Disconnect()")
        except Exception:  # noqa: BLE001 - best-effort cleanup
            pass
