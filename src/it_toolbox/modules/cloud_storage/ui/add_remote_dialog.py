"""A generic "Add Remote" wizard that works for any of rclone's ~50
backend types without hand-built per-backend forms — it renders fields
straight from `rclone config providers`' own schema (see
core/rclone_client.py's module docstring for the underlying protocol).

Flow: pick a name + provider type -> fill in that provider's fields (a
single form covers the vast majority of backends) -> create. If the
backend needs one more piece of interactive input beyond plain fields
(OAuth token backends, mainly), the create call comes back with exactly
one more question instead of finishing, which this dialog then asks
one at a time until rclone reports the remote is done.
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)

from it_toolbox.core import async_utils, rclone_client
from it_toolbox.modules.cloud_storage.models import ConfigStep, Provider, ProviderOption

PROVIDER_ROLE = Qt.ItemDataRole.UserRole


def _make_field_widget(option: ProviderOption) -> QWidget:
    if option.exclusive and option.examples:
        combo = QComboBox()
        if not option.required:
            combo.addItem("", "")
        for value, help_text in option.examples:
            combo.addItem(f"{value} — {help_text}" if help_text else value, value)
        if option.default:
            index = combo.findData(option.default)
            if index != -1:
                combo.setCurrentIndex(index)
        return combo
    if option.type == "bool":
        checkbox = QCheckBox()
        checkbox.setChecked(option.default.lower() == "true")
        return checkbox
    line_edit = QLineEdit()
    if option.is_password:
        line_edit.setEchoMode(QLineEdit.EchoMode.Password)
    if option.default:
        line_edit.setPlaceholderText(option.default)
    return line_edit


def _field_value(widget: QWidget) -> str:
    if isinstance(widget, QComboBox):
        return widget.currentData() or ""
    if isinstance(widget, QCheckBox):
        return "true" if widget.isChecked() else "false"
    return widget.text().strip()


class AddRemoteDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Add Remote")
        self.resize(480, 560)

        self._providers: list[Provider] = []
        self._selected_provider: Provider | None = None
        self._show_advanced = False
        self._field_widgets: dict[str, QWidget] = {}

        self._body = QVBoxLayout()
        outer = QVBoxLayout(self)
        outer.addLayout(self._body)

        self._show_type_selection()
        async_utils.run_in_background(
            rclone_client.list_providers,
            on_result=self._on_providers_loaded,
            on_error=self._on_error,
        )

    # -- Stage management -------------------------------------------------

    def _clear_body(self) -> None:
        while self._body.count():
            item = self._body.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
            elif item.layout() is not None:
                self._clear_sublayout(item.layout())

    def _clear_sublayout(self, layout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    # -- Stage 1: name + provider type -------------------------------------

    def _show_type_selection(self) -> None:
        self._clear_body()

        self._name_edit = QLineEdit()
        self._name_edit.setPlaceholderText("Remote name")
        self._name_edit.textChanged.connect(self._update_type_stage_buttons)

        self._filter_edit = QLineEdit()
        self._filter_edit.setPlaceholderText("Filter provider types…")
        self._filter_edit.textChanged.connect(self._apply_provider_filter)

        self._provider_list = QListWidget()
        for provider in self._providers:
            label = f"{provider.name} — {provider.description}"
            item = QListWidgetItem(label)
            item.setData(PROVIDER_ROLE, provider)
            self._provider_list.addItem(item)
        self._provider_list.itemSelectionChanged.connect(self._update_type_stage_buttons)

        self._type_buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel
        )
        self._next_button = self._type_buttons.addButton(
            "Next", QDialogButtonBox.ButtonRole.AcceptRole
        )
        self._next_button.setEnabled(False)
        self._type_buttons.rejected.connect(self.reject)
        self._next_button.clicked.connect(self._on_next_clicked)

        self._body.addWidget(QLabel("Name:"))
        self._body.addWidget(self._name_edit)
        self._body.addWidget(QLabel("Provider type:"))
        self._body.addWidget(self._filter_edit)
        self._body.addWidget(self._provider_list, 1)
        self._body.addWidget(self._type_buttons)
        self._update_type_stage_buttons()

    def _on_providers_loaded(self, providers: list[Provider]) -> None:
        self._providers = providers
        # Only rebuild if we're still on the type-selection stage (the
        # background load can finish after the user already moved on, or
        # even after they closed the dialog).
        if hasattr(self, "_provider_list"):
            self._show_type_selection()

    def _apply_provider_filter(self, text: str) -> None:
        text = text.lower()
        for i in range(self._provider_list.count()):
            item = self._provider_list.item(i)
            item.setHidden(text not in item.text().lower())

    def _update_type_stage_buttons(self) -> None:
        has_name = bool(self._name_edit.text().strip())
        has_provider = bool(self._provider_list.selectedItems())
        self._next_button.setEnabled(has_name and has_provider)

    def _on_next_clicked(self) -> None:
        self._remote_name = self._name_edit.text().strip()
        selected = self._provider_list.selectedItems()[0]
        self._selected_provider = selected.data(PROVIDER_ROLE)
        self._show_config_form()

    # -- Stage 2: provider-specific fields ----------------------------------

    def _show_config_form(self) -> None:
        self._clear_body()
        provider = self._selected_provider

        self._body.addWidget(QLabel(f'Configure "{self._remote_name}" ({provider.name}):'))

        form = QFormLayout()
        self._field_widgets = {}
        for option in provider.options:
            if option.advanced and not self._show_advanced:
                continue
            widget = _make_field_widget(option)
            widget.setToolTip(option.help)
            self._field_widgets[option.name] = widget
            label = option.name + ("*" if option.required else "")
            form.addRow(label, widget)
        self._body.addLayout(form)

        advanced_checkbox = QCheckBox("Show advanced options")
        advanced_checkbox.setChecked(self._show_advanced)
        advanced_checkbox.toggled.connect(self._on_advanced_toggled)
        self._body.addWidget(advanced_checkbox)
        self._body.addStretch()

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        back_button = buttons.addButton("Back", QDialogButtonBox.ButtonRole.ResetRole)
        create_button = buttons.addButton("Create", QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.rejected.connect(self.reject)
        back_button.clicked.connect(self._show_type_selection)
        create_button.clicked.connect(lambda: self._on_create_clicked(buttons))
        self._body.addWidget(buttons)

    def _on_advanced_toggled(self, checked: bool) -> None:
        self._show_advanced = checked
        self._show_config_form()

    def _on_create_clicked(self, buttons: QDialogButtonBox) -> None:
        fields = {
            name: _field_value(widget)
            for name, widget in self._field_widgets.items()
            if _field_value(widget)
        }
        buttons.setEnabled(False)
        async_utils.run_in_background(
            lambda: rclone_client.start_create_remote(
                self._remote_name, self._selected_provider.name, fields
            ),
            on_result=lambda step: self._on_step_result(step, buttons),
            on_error=lambda error: self._on_error(error, buttons),
        )

    # -- Stage 3: extra interactive questions (OAuth backends, mainly) -----

    def _show_question(self, step: ConfigStep) -> None:
        self._clear_body()
        self._pending_state = step.state
        option = step.option

        self._body.addWidget(QLabel(option.help or option.name))
        widget = _make_field_widget(option)
        self._question_widget = widget
        self._body.addWidget(widget)
        self._body.addStretch()

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        submit_button = buttons.addButton("Submit", QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.rejected.connect(self.reject)
        submit_button.clicked.connect(lambda: self._on_submit_question(buttons))
        self._body.addWidget(buttons)

    def _on_submit_question(self, buttons: QDialogButtonBox) -> None:
        result = _field_value(self._question_widget)
        buttons.setEnabled(False)
        async_utils.run_in_background(
            lambda: rclone_client.continue_config_step(
                self._remote_name, self._pending_state, result
            ),
            on_result=lambda step: self._on_step_result(step, buttons),
            on_error=lambda error: self._on_error(error, buttons),
        )

    # -- Shared step handling -----------------------------------------------

    def _on_step_result(self, step: ConfigStep, buttons: QDialogButtonBox) -> None:
        if step.done:
            self.accept()
            return
        self._show_question(step)

    def _on_error(self, error: Exception, buttons: QDialogButtonBox | None = None) -> None:
        if buttons is not None:
            buttons.setEnabled(True)
        QMessageBox.warning(self, "Error", str(error))

    def remote_name(self) -> str:
        return getattr(self, "_remote_name", "")
