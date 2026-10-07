"""Qt-signal wrapper around spice_session_runner.SpiceSessionRunner -- the
in-process SPICE worker SpiceWidget uses wherever PyGObject/spice-glib are
installed (Linux). See spice_session_runner.py for how the session itself
is driven, and remote_spice_worker.py for the Windows equivalent that runs
the same runner inside the Linux tools WSL distro.

The runner's callbacks fire on its GLib loop thread, so each .emit() here
crosses back to the Qt thread via a queued signal emission -- exactly
analogous to RdpSessionWorker._on_frame. Input methods are the runner's
own (already safe to call from the Qt thread via GLib.idle_add).
"""

from it_toolbox.core.spice.spice_session_runner import SpiceSessionRunner
from it_toolbox.core.spice.spice_signals import SpiceSessionSignals

__all__ = ["SpiceSessionSignals", "SpiceSessionWorker"]


class SpiceSessionWorker(SpiceSessionRunner):
    def __init__(self, host: str, port: int, password: str = "") -> None:
        self.signals = SpiceSessionSignals()
        super().__init__(
            host,
            port,
            password,
            on_frame=self.signals.frame_ready.emit,
            on_connected=self.signals.connected.emit,
            on_agent_connected=self.signals.agent_connected.emit,
            on_error=self.signals.error.emit,
            on_disconnected=self.signals.disconnected.emit,
        )
