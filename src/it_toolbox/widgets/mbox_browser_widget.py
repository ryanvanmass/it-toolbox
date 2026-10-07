"""One opened mbox file, shown as a tab in the shared session-tab pane:
a sortable message list, a search field, and a preview of the selected
message (headers, body, attachments).

The search field filters the list by subject, sender, recipients and
date as you type. Ticking "Search message bodies" also matches message
text, which means reading every message, so that part runs in the
background (debounced, and abandoned as soon as the query changes).
"""

from datetime import datetime
from pathlib import Path

import shiboken6
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QProgressBar,
    QMenu,
    QMessageBox,
    QSplitter,
    QStyle,
    QTextBrowser,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from it_toolbox.core import async_utils
from it_toolbox.core.mbox_reader import (
    SCANNING,
    IndexCancelled,
    MboxReader,
    MessageDetail,
    MessageSummary,
)
from it_toolbox.widgets import status_bar

SUMMARY_ROLE = Qt.ItemDataRole.UserRole
ATTACHMENT_ROLE = Qt.ItemDataRole.UserRole

COLUMN_DATE, COLUMN_FROM, COLUMN_SUBJECT, COLUMN_ATTACHMENT = range(4)

BODY_SEARCH_DELAY_MS = 400
LOAD_PROGRESS_INTERVAL_MS = 100


def _format_size(size: int) -> str:
    for unit in ("B", "KB", "MB"):
        if size < 1024:
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"


def _date_sort_key(summary: MessageSummary) -> tuple[datetime, int]:
    # Undated messages sort as oldest; file order breaks ties.
    return (summary.date or datetime.min, summary.key)


class _MessageItem(QTreeWidgetItem):
    """Sorts the Date column chronologically rather than by its text."""

    def __lt__(self, other: QTreeWidgetItem) -> bool:
        column = self.treeWidget().sortColumn() if self.treeWidget() else 0
        if column == COLUMN_DATE:
            mine = self.data(0, SUMMARY_ROLE)
            theirs = other.data(0, SUMMARY_ROLE)
            if mine is not None and theirs is not None:
                return _date_sort_key(mine) < _date_sort_key(theirs)
        return self.text(column).lower() < other.text(column).lower()


class MboxBrowserWidget(QWidget):
    #: Emitted once the file has been indexed (or failed to), with the
    #: message count, or -1 on failure.
    loaded = Signal(int)

    def __init__(self, path: str | Path, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.path = Path(path)
        self._reader: MboxReader | None = None
        self._summaries: list[MessageSummary] = []
        self._body_matches: set[int] = set()
        # Bumped on every query change; a body search still running for an
        # older generation stops early and its result is dropped.
        self._search_generation = 0
        self._current_key: int | None = None
        self._closed = False

        self._search_edit = QLineEdit()
        self._search_edit.setPlaceholderText("Search subject, sender, recipients, date")
        self._search_edit.setClearButtonEnabled(True)
        self._search_edit.textChanged.connect(self._on_query_changed)
        self._bodies_check = QCheckBox("Search message bodies")
        self._bodies_check.toggled.connect(self._on_query_changed)
        self._count_label = QLabel("Loading…")

        self._body_search_timer = QTimer(self)
        self._body_search_timer.setSingleShot(True)
        self._body_search_timer.setInterval(BODY_SEARCH_DELAY_MS)
        self._body_search_timer.timeout.connect(self._start_body_search)

        # Shown only while the file is being indexed. The worker thread
        # just stores its latest (phase, done, total) in self._load_progress
        # and a main-thread timer copies it onto the bar, so a big archive
        # doesn't flood the event loop with one update per message.
        self._load_progress: tuple[str, int, int] | None = None
        self._progress_label = QLabel(f"Opening {self.path.name}…")
        self._progress_bar = QProgressBar()
        self._progress_bar.setRange(0, 0)  # busy until the first update
        self._progress_bar.setTextVisible(False)
        self._progress_timer = QTimer(self)
        self._progress_timer.setInterval(LOAD_PROGRESS_INTERVAL_MS)
        self._progress_timer.timeout.connect(self._update_load_progress)
        self._progress_panel = QWidget()
        progress_layout = QVBoxLayout(self._progress_panel)
        progress_layout.setContentsMargins(0, 0, 0, 0)
        progress_layout.addWidget(self._progress_label)
        progress_layout.addWidget(self._progress_bar)

        search_row = QHBoxLayout()
        search_row.addWidget(self._search_edit, 1)
        search_row.addWidget(self._bodies_check)
        search_row.addWidget(self._count_label)

        self._list = QTreeWidget()
        self._list.setHeaderLabels(["Date", "From", "Subject", ""])
        self._attachment_icon = self.style().standardIcon(QStyle.StandardPixmap.SP_FileIcon)
        self._list.setRootIsDecorated(False)
        self._list.setUniformRowHeights(True)
        self._list.setSortingEnabled(True)
        self._list.sortByColumn(COLUMN_DATE, Qt.SortOrder.DescendingOrder)
        header = self._list.header()
        header.setSectionResizeMode(COLUMN_SUBJECT, QHeaderView.ResizeMode.Stretch)
        header.setStretchLastSection(False)
        header.resizeSection(COLUMN_DATE, 130)
        header.resizeSection(COLUMN_FROM, 220)
        header.resizeSection(COLUMN_ATTACHMENT, 30)
        self._list.currentItemChanged.connect(self._on_current_item_changed)
        self._list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._list.customContextMenuRequested.connect(self._on_list_context_menu)

        self._headers_label = QLabel()
        self._headers_label.setTextFormat(Qt.TextFormat.PlainText)
        self._headers_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._headers_label.setWordWrap(True)
        self._body_view = QTextBrowser()
        # Links open in the system browser. QTextBrowser never fetches
        # remote resources itself, so tracking pixels in HTML mail stay dark.
        self._body_view.setOpenExternalLinks(True)
        self._attachments = QListWidget()
        self._attachments.setMaximumHeight(90)
        self._attachments.itemDoubleClicked.connect(self._on_attachment_activated)
        self._attachments.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._attachments.customContextMenuRequested.connect(self._on_attachment_context_menu)
        self._attachments.setToolTip("Double-click an attachment to save it")
        self._attachments.hide()

        preview = QWidget()
        preview_layout = QVBoxLayout(preview)
        preview_layout.setContentsMargins(0, 0, 0, 0)
        preview_layout.addWidget(self._headers_label)
        preview_layout.addWidget(self._body_view, 1)
        preview_layout.addWidget(self._attachments)

        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.addWidget(self._list)
        splitter.addWidget(preview)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1)

        layout = QVBoxLayout(self)
        layout.addLayout(search_row)
        layout.addWidget(self._progress_panel)
        layout.addWidget(splitter, 1)

        self._set_searchable(False)
        self._load()

    # -- Loading ----------------------------------------------------------

    def _set_searchable(self, enabled: bool) -> None:
        self._search_edit.setEnabled(enabled)
        self._bodies_check.setEnabled(enabled)

    def _load(self) -> None:
        task = status_bar.begin(self, f"Reading {self.path.name}…")
        path = self.path

        def report(phase: str, done: int, total: int) -> None:
            self._load_progress = (phase, done, total)

        def open_and_index():
            reader = MboxReader(path)
            try:
                return reader, reader.index(progress=report, cancelled=lambda: self._closed)
            except Exception:
                reader.close()
                raise

        self._progress_timer.start()
        async_utils.run_in_background(
            open_and_index,
            on_result=lambda result: self._on_loaded(result, task),
            on_error=lambda error: self._on_load_error(error, task),
        )

    def _update_load_progress(self) -> None:
        if self._load_progress is None:
            return
        phase, done, total = self._load_progress
        if phase == SCANNING:
            self._progress_label.setText(f"Scanning {self.path.name}…")
            # QProgressBar's range is a C int, too small for byte counts.
            percent = done * 100 // total if total else 100
            self._progress_bar.setRange(0, 100)
            self._progress_bar.setValue(percent)
        else:
            self._progress_label.setText(f"Reading messages: {done:,} of {total:,}")
            self._progress_bar.setRange(0, max(total, 1))
            self._progress_bar.setValue(done)

    def _finish_load_progress(self) -> None:
        self._progress_timer.stop()
        self._progress_panel.hide()

    def _alive(self) -> bool:
        # The tab can be closed (or the whole window torn down) while a
        # background read is still in flight; its result then has nowhere
        # to go.
        return not self._closed and shiboken6.isValid(self)

    def _on_loaded(self, result, task: status_bar.StatusTask) -> None:
        if not self._alive():
            result[0].close()
            task.finish()
            return
        self._finish_load_progress()
        self._reader, self._summaries = result
        task.finish(f"Loaded {len(self._summaries)} messages from {self.path.name}")
        self._list.setSortingEnabled(False)
        for summary in self._summaries:
            item = _MessageItem(
                [
                    summary.date_text,
                    summary.sender,
                    summary.subject or "(no subject)",
                    "",
                ]
            )
            if summary.has_attachments:
                item.setIcon(COLUMN_ATTACHMENT, self._attachment_icon)
                item.setToolTip(COLUMN_ATTACHMENT, "Has attachments")
            item.setData(0, SUMMARY_ROLE, summary)
            item.setToolTip(COLUMN_SUBJECT, summary.subject)
            item.setToolTip(COLUMN_FROM, summary.sender)
            self._list.addTopLevelItem(item)
        self._list.setSortingEnabled(True)
        self._set_searchable(True)
        self._apply_filter()
        self.loaded.emit(len(self._summaries))

    def _on_load_error(self, error: Exception, task: status_bar.StatusTask) -> None:
        if isinstance(error, IndexCancelled) or not self._alive():
            task.finish()
            return
        task.finish(f"Couldn't read {self.path.name}")
        self._finish_load_progress()
        self._count_label.setText("Couldn't read file")
        self.loaded.emit(-1)
        QMessageBox.warning(self, "Couldn't open mbox file", f"{self.path}\n\n{error}")

    def close_session(self) -> None:
        self._closed = True  # also stops an index still in progress
        self._progress_timer.stop()
        self._search_generation += 1  # stop any body search in flight
        if self._reader is not None:
            self._reader.close()
            self._reader = None

    # -- Search -----------------------------------------------------------

    def _query(self) -> str:
        return self._search_edit.text().strip().lower()

    def _on_query_changed(self) -> None:
        self._search_generation += 1
        self._body_matches = set()
        self._body_search_timer.stop()
        self._apply_filter()
        if self._bodies_check.isChecked() and self._query() and self._reader is not None:
            self._count_label.setText("Searching bodies…")
            self._body_search_timer.start()

    def _start_body_search(self) -> None:
        if self._reader is None:
            return
        generation = self._search_generation
        query = self._query()
        reader = self._reader
        # Only messages the header filter didn't already match need reading.
        keys = [s.key for s in self._summaries if not s.matches(query)]
        task = status_bar.begin(self, f"Searching {self.path.name} for “{query}”…")
        async_utils.run_in_background(
            lambda: reader.search_bodies(
                keys, query, cancelled=lambda: generation != self._search_generation
            ),
            on_result=lambda found: self._on_body_search_done(found, generation, task),
            on_error=lambda error: self._on_body_search_error(error, generation, task),
        )

    def _on_body_search_done(
        self, found: set[int] | None, generation: int, task: status_bar.StatusTask
    ) -> None:
        task.finish()
        if found is None or generation != self._search_generation or not self._alive():
            return
        self._body_matches = found
        self._apply_filter()

    def _on_body_search_error(
        self, error: Exception, generation: int, task: status_bar.StatusTask
    ) -> None:
        task.finish("Body search failed")
        if generation != self._search_generation or not self._alive():
            return
        self._apply_filter()
        QMessageBox.warning(self, "Body search failed", str(error))

    def _apply_filter(self) -> None:
        query = self._query()
        shown = 0
        for row in range(self._list.topLevelItemCount()):
            item = self._list.topLevelItem(row)
            summary: MessageSummary = item.data(0, SUMMARY_ROLE)
            visible = not query or summary.matches(query) or summary.key in self._body_matches
            item.setHidden(not visible)
            shown += visible
        total = len(self._summaries)
        self._count_label.setText(
            f"{total} messages" if not query else f"{shown} of {total} messages"
        )

    # -- Preview ----------------------------------------------------------

    def _on_current_item_changed(self, current: QTreeWidgetItem | None, _previous) -> None:
        summary = current.data(0, SUMMARY_ROLE) if current is not None else None
        if summary is None or self._reader is None:
            self._show_detail(None)
            return
        self._current_key = summary.key
        reader = self._reader
        async_utils.run_in_background(
            lambda: reader.load(summary.key),
            on_result=self._on_detail_loaded,
            on_error=lambda error: self._on_detail_error(summary.key, error),
        )

    def _on_detail_loaded(self, detail: MessageDetail) -> None:
        if self._alive() and detail.key == self._current_key:
            self._show_detail(detail)

    def _on_detail_error(self, key: int, error: Exception) -> None:
        if self._alive() and key == self._current_key:
            self._show_detail(None)
            self._body_view.setPlainText(f"Couldn't read this message: {error}")

    def _show_detail(self, detail: MessageDetail | None) -> None:
        self._attachments.clear()
        if detail is None:
            self._current_key = None
            self._headers_label.clear()
            self._body_view.clear()
            self._attachments.hide()
            return
        self._headers_label.setText("\n".join(f"{name}: {value}" for name, value in detail.headers))
        if detail.text_body is not None:
            self._body_view.setPlainText(detail.text_body)
        elif detail.html_body is not None:
            self._body_view.setHtml(detail.html_body)
        else:
            self._body_view.setPlainText("(no text content)")
        for attachment in detail.attachments:
            item = QListWidgetItem(
                self._attachment_icon,
                f"{attachment.filename}  ({_format_size(attachment.size)}, "
                f"{attachment.content_type})"
            )
            item.setData(ATTACHMENT_ROLE, attachment)
            self._attachments.addItem(item)
        self._attachments.setVisible(bool(detail.attachments))

    # -- Saving -----------------------------------------------------------

    def _on_attachment_activated(self, item: QListWidgetItem) -> None:
        self._save_attachment(item.data(ATTACHMENT_ROLE))

    def _on_attachment_context_menu(self, pos) -> None:
        item = self._attachments.itemAt(pos)
        if item is None:
            return
        menu = QMenu(self)
        menu.addAction("Save Attachment…").triggered.connect(
            lambda: self._save_attachment(item.data(ATTACHMENT_ROLE))
        )
        menu.exec(self._attachments.viewport().mapToGlobal(pos))

    def _save_attachment(self, attachment) -> None:
        if self._reader is None or self._current_key is None:
            return
        destination, _ = QFileDialog.getSaveFileName(
            self, "Save Attachment", str(Path.home() / attachment.filename)
        )
        if not destination:
            return
        reader, key = self._reader, self._current_key
        self._write_in_background(
            lambda: reader.attachment_bytes(key, attachment.index), destination
        )

    def _on_list_context_menu(self, pos) -> None:
        item = self._list.itemAt(pos)
        summary = item.data(0, SUMMARY_ROLE) if item is not None else None
        if summary is None:
            return
        menu = QMenu(self)
        menu.addAction("Save Message as .eml…").triggered.connect(
            lambda: self._save_message(summary)
        )
        menu.exec(self._list.viewport().mapToGlobal(pos))

    def _save_message(self, summary: MessageSummary) -> None:
        if self._reader is None:
            return
        name = "".join(c for c in summary.subject if c.isalnum() or c in " -_").strip()
        destination, _ = QFileDialog.getSaveFileName(
            self,
            "Save Message",
            str(Path.home() / f"{name or 'message'}.eml"),
            "Email messages (*.eml)",
        )
        if not destination:
            return
        reader = self._reader
        self._write_in_background(lambda: reader.raw_bytes(summary.key), destination)

    def _write_in_background(self, read_bytes, destination: str) -> None:
        name = Path(destination).name
        task = status_bar.begin(self, f"Saving {name}…")

        def write():
            Path(destination).write_bytes(read_bytes())

        def on_error(error: Exception) -> None:
            task.finish(f"Couldn't save {name}")
            if not shiboken6.isValid(self):
                return
            QMessageBox.warning(self, "Couldn't save file", str(error))

        async_utils.run_in_background(
            write, on_result=lambda _: task.finish(f"Saved {name}"), on_error=on_error
        )
