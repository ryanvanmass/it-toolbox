"""A memory-size input that lets the user pick MiB or GiB, whichever is
more convenient to type -- a 16 GiB VM is an awkward "16384" in raw MiB.
Used by both CreateVmDialog and ConfigureVmDialog's memory fields.

Always reports/accepts a plain MiB integer via value_mib()/set_value_mib()
-- the unit is purely a display/entry convenience, never something a
caller needs to know about; every backend call in this module already
takes memory_mib as a plain int, unchanged by this widget's existence.

Switching units converts the current value, but GiB is a coarser
granularity than MiB, so a value that isn't a whole number of GiB gets
rounded when switching *to* GiB (e.g. 2500 MiB -> "2 GiB", i.e. 2048 MiB)
-- an inherent, expected trade-off of choosing the coarser unit, not a
bug, and no different from how any such unit toggle would have to behave.
"""

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QSpinBox, QWidget

_MIB_PER_GIB = 1024
_MIN_MIB = 128
_MAX_MIB = 1_048_576  # 1024 GiB -- matches the previous plain-MiB spin's own upper bound


class MemorySizeWidget(QWidget):
    """Emits valueChangedMib(int) whenever the effective MiB value
    changes, whether from the spinbox itself or from a unit switch."""

    valueChangedMib = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._is_gib = False

        self._spin = QSpinBox()
        self._spin.setRange(_MIN_MIB, _MAX_MIB)
        self._spin.setSuffix(" MiB")
        self._spin.setValue(2048)
        self._spin.valueChanged.connect(lambda _: self.valueChangedMib.emit(self.value_mib()))

        self._unit_combo = QComboBox()
        self._unit_combo.addItems(["MiB", "GiB"])
        self._unit_combo.currentIndexChanged.connect(self._on_unit_changed)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._spin, 1)
        layout.addWidget(self._unit_combo)

    def _on_unit_changed(self, _index: int) -> None:
        new_is_gib = self._unit_combo.currentText() == "GiB"
        mib = self.value_mib()  # read using the *old* unit, before switching
        self._is_gib = new_is_gib
        # Reconfiguring range/suffix/value on a QSpinBox fires valueChanged
        # multiple times with transient, not-yet-correct intermediate
        # values (setRange() alone can clamp the current value) -- block
        # those and emit exactly one clean valueChangedMib with the real,
        # final result once everything's settled.
        self._spin.blockSignals(True)
        if new_is_gib:
            self._spin.setRange(1, _MAX_MIB // _MIB_PER_GIB)
            self._spin.setSuffix(" GiB")
            self._spin.setValue(max(1, round(mib / _MIB_PER_GIB)))
        else:
            self._spin.setRange(_MIN_MIB, _MAX_MIB)
            self._spin.setSuffix(" MiB")
            self._spin.setValue(mib)
        self._spin.blockSignals(False)
        self.valueChangedMib.emit(self.value_mib())

    def value_mib(self) -> int:
        return self._spin.value() * _MIB_PER_GIB if self._is_gib else self._spin.value()

    def set_value_mib(self, mib: int) -> None:
        if self._is_gib:
            self._spin.setValue(max(1, round(mib / _MIB_PER_GIB)))
        else:
            self._spin.setValue(mib)
