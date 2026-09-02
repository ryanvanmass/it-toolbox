"""Embedded RDP session via Microsoft's RDP ActiveX control (MsTscAx).

Windows-only — QtAxContainer (Qt's ActiveX container support) doesn't exist
on other platforms, and ships with Windows itself (MSTSCAX.DLL, the same
control behind mstsc.exe), so nothing extra to install.

STATUS (as tested live against one real Windows machine): embedding does
not currently work on that machine, and the cause turns out to be outside
this code. setControl/Server/AdvancedSettings2.RDPPort and QAxBase's
`exception` signal all work correctly — every property set was confirmed
via readback with zero exceptions. Connect() itself reliably fails with
E_INVALIDARG (0x80070057). Ruled out along the way: calling Connect()
before the widget was ever shown (fixed by deferring to connect_session(),
called after addTab() via QTimer.singleShot(0, ...) — necessary but not
sufficient); FullScreen=False and AdvancedSettings2.SmartSizing=True each
independently made it *worse* (same error, confirmed by isolation) and
were reverted. A standalone diagnostic (scripts/rdp_activex_diagnostic.py)
showed the real signal: none of the modern MsRdpClient5 through
MsRdpClient11NotSafeForScripting ProgIDs are registered on that machine —
only the legacy "safe for scripting" MsTscAx.MsTscAx — and Connect()'s
exception detail read "Class not registered", which persisted even after
`regsvr32 mstscax.dll`. That points at an incomplete/nonstandard RDP
client component installation on that specific machine, not a bug here.

This code is left in place because the approach (and the fallback below)
is still sound — it may well work on a machine with a complete RDP client
install. If it fails, connect_failed lets the caller fall back to
launching mstsc.exe externally (main_view.py does this), so the failure
mode is a working external session, not a broken one. Still unconfirmed
even on a machine where Connect() succeeds: whether OnDisconnected
actually fires under this exact attribute name.
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
        # Queried here rather than __init__ so this is the widget's real,
        # laid-out size rather than whatever it defaulted to before being
        # shown — set as close to Connect() as possible in case a resize
        # happens between construction and this call.
        self.setProperty("DesktopWidth", max(self.width(), 640))
        self.setProperty("DesktopHeight", max(self.height(), 480))
        self.setProperty("ColorDepth", 32)

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
