"""Embedded RDP session via Microsoft's RDP ActiveX control (MsTscAx).

Windows-only — QtAxContainer (Qt's ActiveX container support) doesn't exist
on other platforms, and ships with Windows itself (MSTSCAX.DLL, the same
control behind mstsc.exe), so nothing extra to install.

Live-tested against a real IAP tunnel, several rounds:
- setControl/Server/AdvancedSettings2.RDPPort/Connect()/QAxBase's
  `exception` signal all confirmed working.
- Connect() reliably failed with E_INVALIDARG (0x80070057) when called
  synchronously from __init__, before the widget had ever been shown (no
  real native window handle yet) — fixed by deferring it to
  connect_session(), called only after the widget is on screen (main_view
  does this with QTimer.singleShot(0, ...) right after addTab()).
- With that fixed, Connect() succeeded but rendered at a fixed 1024x768
  regardless of this widget's actual size, which looked like "full
  screen" — not an actual full-screen negotiation.
- Explicitly setting FullScreen=False, AND separately
  AdvancedSettings2.SmartSizing=True, each independently broke Connect()
  again with the exact same E_INVALIDARG — confirmed live, both reverted.
  Whatever the real constraint is, it isn't obviously either of those.
- Current approach: don't fight the control's property quirks further —
  set DesktopWidth/DesktopHeight to this widget's actual pixel size,
  queried in connect_session() (by which point it's been laid out), so it
  should render at roughly the right size without needing a scaling
  property at all. Untested as of this comment.

Still unconfirmed: whether OnDisconnected actually fires under this exact
attribute name — if disconnecting doesn't clean up the session, that's the
first thing to check.
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
