from it_toolbox.modules.connection_manager.ui.memory_size_widget import MemorySizeWidget


def test_defaults_to_mib(qtbot):
    widget = MemorySizeWidget()
    qtbot.addWidget(widget)

    widget.set_value_mib(4096)

    assert widget.value_mib() == 4096
    assert widget._spin.suffix() == " MiB"
    assert widget._spin.value() == 4096


def test_switching_to_gib_converts_the_displayed_value(qtbot):
    widget = MemorySizeWidget()
    qtbot.addWidget(widget)
    widget.set_value_mib(4096)

    widget._unit_combo.setCurrentText("GiB")

    assert widget._spin.suffix() == " GiB"
    assert widget._spin.value() == 4
    assert widget.value_mib() == 4096  # still reports the same real MiB value


def test_editing_in_gib_mode_reports_correct_mib(qtbot):
    widget = MemorySizeWidget()
    qtbot.addWidget(widget)
    widget._unit_combo.setCurrentText("GiB")

    widget._spin.setValue(8)

    assert widget.value_mib() == 8192


def test_switching_back_to_mib_preserves_the_value(qtbot):
    widget = MemorySizeWidget()
    qtbot.addWidget(widget)
    widget._unit_combo.setCurrentText("GiB")
    widget._spin.setValue(8)

    widget._unit_combo.setCurrentText("MiB")

    assert widget.value_mib() == 8192
    assert widget._spin.value() == 8192


def test_switching_to_gib_rounds_a_non_whole_gib_value(qtbot):
    # GiB is a coarser granularity -- an inherent, expected trade-off,
    # not a bug (see the module's own docstring).
    widget = MemorySizeWidget()
    qtbot.addWidget(widget)
    widget.set_value_mib(2500)

    widget._unit_combo.setCurrentText("GiB")

    assert widget.value_mib() == 2048


def test_set_value_mib_while_in_gib_mode_converts_correctly(qtbot):
    widget = MemorySizeWidget()
    qtbot.addWidget(widget)
    widget._unit_combo.setCurrentText("GiB")

    widget.set_value_mib(16384)

    assert widget._spin.value() == 16
    assert widget.value_mib() == 16384


def test_value_changed_signal_fires_once_per_unit_switch(qtbot):
    widget = MemorySizeWidget()
    qtbot.addWidget(widget)
    widget.set_value_mib(4096)
    changes = []
    widget.valueChangedMib.connect(changes.append)

    widget._unit_combo.setCurrentText("GiB")

    assert changes == [4096]


def test_value_changed_signal_fires_on_spin_edit(qtbot):
    widget = MemorySizeWidget()
    qtbot.addWidget(widget)
    changes = []
    widget.valueChangedMib.connect(changes.append)

    widget._spin.setValue(8192)

    assert changes == [8192]
