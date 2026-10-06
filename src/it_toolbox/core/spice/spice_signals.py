"""The Qt signal surface every SPICE worker exposes to SpiceWidget --
the in-process SpiceSessionWorker and the WSL-backed RemoteSpiceWorker
alike. Its own module (no gi import) so the Windows build, which has no
PyGObject, can import it.
"""

from PySide6.QtCore import QObject, Signal


class SpiceSessionSignals(QObject):
    # pixels (BGRX) for rows [band_top, band_top + band_height) of the full
    # canvas_width x canvas_height surface -- see SpiceSession.get_dirty_band()
    frame_ready = Signal(bytes, int, int, int, int, int)  # pixels, band_top, band_height, canvas_width, canvas_height, stride
    connected = Signal()
    error = Signal(str)
    disconnected = Signal()
    # Fires once the guest's agent (spice-vdagent or equivalent) finishes
    # connecting -- a real, separate, later event than `connected` above.
    # See SpiceSession.on_agent_connected's docstring for why a caller
    # that only tries a resize once, right after `connected`, can miss a
    # real agent that hasn't finished its own handshake yet.
    agent_connected = Signal()
