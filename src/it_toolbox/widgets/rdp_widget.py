"""Embedded RDP session via Microsoft's RDP ActiveX control (MsTscAx).

Windows-only — QtAxContainer (Qt's ActiveX container support) doesn't exist
on other platforms, and ships with Windows itself (MSTSCAX.DLL, the same
control behind mstsc.exe), so nothing extra to install.

Live-tested against a real IAP tunnel: setControl/setControl/Server/
AdvancedSettings2.RDPPort/Connect()/QAxBase's `exception` signal all
confirmed working. Connect() failed with E_INVALIDARG until DesktopWidth/
DesktopHeight were set explicitly (they default to 0, which some MsTscAx
versions reject). Still unconfirmed: whether OnDisconnected actually fires
under this exact attribute name — if disconnecting doesn't clean up the
session, that's the first thing to check.
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

        # QAxBase reports COM errors (e.g. a failed Connect()) via this
        # signal rather than a raisable Python exception — without
        # connecting it, a failure here is just a console warning and a
        # permanently blank widget, with nothing telling the caller to fall
        # back to an external client.
        self._last_com_exception: str | None = None
        self.exception.connect(self._on_com_exception)

        self.setProperty("Server", host)
        if username:
            self.setProperty("UserName", username)

        # DesktopWidth/DesktopHeight default to 0 on a freshly-created
        # control, which some versions of MsTscAx reject Connect() for
        # (confirmed live: E_INVALIDARG / 0x80070057) — set real values.
        self.setProperty("DesktopWidth", 1024)
        self.setProperty("DesktopHeight", 768)
        self.setProperty("ColorDepth", 32)

        # RDPPort lives under the AdvancedSettings2 sub-object rather than
        # as a top-level property — needed since we're always connecting to
        # a local IAP tunnel port, never the default 3389.
        advanced_settings = self.querySubObject("AdvancedSettings2")
        if advanced_settings is not None:
            advanced_settings.setProperty("RDPPort", port)

        # PySide6 exposes COM events as Qt signals named after the event.
        # This attribute may not exist under this exact name/casing —
        # the first thing to check if embedding connects but disconnect
        # detection doesn't work.
        on_disconnected = getattr(self, "OnDisconnected", None)
        if on_disconnected is not None:
            on_disconnected.connect(self._on_disconnected)

        self.dynamicCall("Connect()")
        if self._last_com_exception:
            raise RuntimeError(f"RDP ActiveX Connect() failed: {self._last_com_exception}")

    def _on_com_exception(self, code, source, desc, help) -> None:  # noqa: A002
        self._last_com_exception = f"[{code}] {source or desc or help}".strip()

    def _on_disconnected(self, *args) -> None:
        self.disconnected.emit()

    def close_session(self) -> None:
        try:
            self.dynamicCall("Disconnect()")
        except Exception:  # noqa: BLE001 - best-effort cleanup
            pass
