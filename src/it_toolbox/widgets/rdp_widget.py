"""Embedded RDP session via Microsoft's RDP ActiveX control (MsTscAx).

Windows-only — QtAxContainer (Qt's ActiveX container support) doesn't exist
on other platforms, and ships with Windows itself (MSTSCAX.DLL, the same
control behind mstsc.exe), so nothing extra to install.

Live-tested against a real IAP tunnel: setControl/Server/AdvancedSettings2.
RDPPort/Connect()/QAxBase's `exception` signal all confirmed working.
Connect() reliably failed with E_INVALIDARG (0x80070057) when called
synchronously from __init__ — even after setting DesktopWidth/DesktopHeight,
which was the first (wrong) theory. The actual cause: at that point the
widget has never been shown, so the ActiveX control has no real native
window handle yet, and Connect() needs one. connect_session() must be
called only after the widget is on screen (main_view defers it with
QTimer.singleShot(0, ...) right after addTab()). After that fix, Connect()
succeeded but the session took over full-screen instead of rendering in
the widget — the control defaults to negotiating a full-screen session
unless FullScreen is explicitly set False, a well-documented gotcha of
embedding it. Still unconfirmed: whether OnDisconnected actually fires
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
    connect_failed = Signal(str)

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
        # signal rather than a raisable Python exception.
        self._last_com_exception: str | None = None
        self.exception.connect(self._on_com_exception)

        self.setProperty("Server", host)
        if username:
            self.setProperty("UserName", username)
        self.setProperty("DesktopWidth", 1024)
        self.setProperty("DesktopHeight", 768)
        self.setProperty("ColorDepth", 32)
        # Without this, the control negotiates (and takes over) a
        # full-screen session instead of rendering embedded in this widget
        # — a well-documented gotcha, not optional for embedding.
        self.setProperty("FullScreen", False)

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

    def connect_session(self) -> None:
        """Actually start the RDP session.

        Must be called only after this widget has a real native window —
        i.e. after it's been added to a layout/shown, not from __init__.
        Reports failure via connect_failed rather than raising, since the
        caller (main_view) needs to react to a failure that can only be
        known well after construction.
        """
        self._last_com_exception = None
        self.dynamicCall("Connect()")
        if self._last_com_exception:
            self.connect_failed.emit(self._last_com_exception)

    def _on_com_exception(self, code, source, desc, help) -> None:  # noqa: A002
        self._last_com_exception = f"[{code}] {source or desc or help}".strip()

    def _on_disconnected(self, *args) -> None:
        self.disconnected.emit()

    def close_session(self) -> None:
        try:
            self.dynamicCall("Disconnect()")
        except Exception:  # noqa: BLE001 - best-effort cleanup
            pass
