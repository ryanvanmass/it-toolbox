"""A site's Traffic tab in the Hosting Manager: requests, data sent and
visitors over a range, read from the site's nginx access log by the
cockpit-hosting helper's site-traffic (the Cockpit page's SiteTraffic)."""

from __future__ import annotations

import datetime

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPalette
from PySide6.QtWidgets import (
    QComboBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from it_toolbox.core import hosting_manager as hm
from it_toolbox.widgets.remote_helper_widget import fill_table, make_table

METRICS = [("requests", "Requests"), ("bytes", "Data sent"), ("visitors", "Visitors")]


def _when(seconds: float, fmt: str = "%Y-%m-%d %H:%M") -> str:
    """Epoch seconds from the helper, in this computer's time zone."""
    return datetime.datetime.fromtimestamp(seconds, tz=datetime.UTC).astimezone().strftime(fmt)


def point_label(time: float, bucket: int) -> str:
    """A bar's label: when it starts, as precisely as its bucket needs."""
    if bucket >= 7 * 86400:
        return "Week of " + _when(time, "%Y-%m-%d")
    if bucket >= 86400:
        return _when(time, "%a %b %d")
    if bucket >= 6 * 3600:
        return _when(time, "%a %H:%M")
    return _when(time, "%H:%M")


def metric_text(metric: str, value: float) -> str:
    return hm.format_bytes(int(value)) if metric == "bytes" else f"{int(value):,}"


def nice_max(value: float) -> float:
    """Rounds the top of the scale up to 1, 2 or 5 times a power of ten."""
    if value <= 0:
        return 1
    power = 10 ** len(str(int(value))) / 10
    return next((step * power for step in (1, 2, 5, 10) if step * power >= value), 10 * power)


class TrafficChart(QWidget):
    """Bars for one metric of the series, with the top of the scale and the
    first, middle and last bucket labelled; hovering a bar shows its numbers."""

    def __init__(self) -> None:
        super().__init__()
        self.setMinimumHeight(180)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMouseTracking(True)
        self.traffic: dict | None = None
        self.shown_metric = "requests"

    def show_traffic(self, traffic: dict | None, metric: str) -> None:
        self.traffic = traffic
        self.shown_metric = metric
        self.update()

    def _top(self) -> float:
        values = [p[self.shown_metric] for p in (self.traffic or {}).get("series") or []]
        top = max(values, default=0)
        return max(top, 1) if self.shown_metric == "bytes" else nice_max(top)

    def _plot(self) -> QRectF:
        return QRectF(70, 8, max(1, self.width() - 78), max(1, self.height() - 34))

    def mouseMoveEvent(self, event) -> None:
        series = (self.traffic or {}).get("series") or []
        plot = self._plot()
        x = event.position().x()
        if not series or not plot.left() <= x <= plot.right():
            self.setToolTip("")
            return
        point = series[min(len(series) - 1, int((x - plot.left()) / plot.width() * len(series)))]
        lines = [point_label(point["time"], self.traffic["bucket"]),
                 f"Requests: {point['requests']:,}", f"Data sent: {hm.format_bytes(point['bytes'])}",
                 f"Visitors: {point['visitors']:,}"]
        if point.get("client_errors") or point.get("server_errors"):
            lines.append(f"Errors: {point['client_errors']:,} client, {point['server_errors']:,} server")
        self.setToolTip("\n".join(lines))

    def paintEvent(self, _event) -> None:
        series = (self.traffic or {}).get("series") or []
        painter = QPainter(self)
        palette = self.palette()
        text = palette.color(QPalette.ColorRole.WindowText)
        grid = QColor(text)
        grid.setAlpha(50)
        plot = self._plot()
        top = self._top()
        painter.setPen(text)
        for fraction in (0.0, 0.5, 1.0):
            y = plot.bottom() - fraction * plot.height()
            painter.setPen(grid)
            painter.drawLine(int(plot.left()), int(y), int(plot.right()), int(y))
            painter.setPen(text)
            value = top * fraction if self.shown_metric == "bytes" else round(top * fraction)
            painter.drawText(QRectF(0, y - 8, plot.left() - 6, 16),
                             Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                             metric_text(self.shown_metric, value))
        if not series:
            painter.end()
            return
        bar = palette.color(QPalette.ColorRole.Highlight)
        width = plot.width() / len(series)
        for index, point in enumerate(series):
            height = point[self.shown_metric] / top * plot.height()
            painter.fillRect(QRectF(plot.left() + index * width + width * 0.1, plot.bottom() - height,
                                    max(1.0, width * 0.8), height), bar)
        painter.setPen(text)
        bucket = self.traffic["bucket"]
        axis = QRectF(plot.left(), plot.bottom() + 4, plot.width(), 18)
        painter.drawText(axis, Qt.AlignmentFlag.AlignLeft, point_label(series[0]["time"], bucket))
        painter.drawText(axis, Qt.AlignmentFlag.AlignHCenter, point_label(series[len(series) // 2]["time"], bucket))
        painter.drawText(axis, Qt.AlignmentFlag.AlignRight, point_label(series[-1]["time"], bucket))
        painter.end()


class TrafficPanel(QWidget):
    """The Traffic sub-tab. `load(name)` reads the selected range."""

    def __init__(self, detail) -> None:
        super().__init__()
        self.detail = detail
        self.traffic: dict | None = None
        self.loaded_for: str | None = None
        self.range = QComboBox()
        for value, label in hm.TRAFFIC_RANGES:
            self.range.addItem(label, value)
        self.metric_box = QComboBox()
        for value, label in METRICS:
            self.metric_box.addItem(label, value)
        refresh = QPushButton("Refresh")
        refresh.clicked.connect(lambda _=False: self.refresh())
        self.range.currentIndexChanged.connect(lambda _: self.refresh())
        self.metric_box.currentIndexChanged.connect(lambda _: self.chart.show_traffic(self.traffic, self.metric_key()))

        self.totals = QLabel()
        font = self.totals.font()
        font.setPointSize(font.pointSize() + 1)
        self.totals.setFont(font)
        self.notes = QLabel()
        self.notes.setWordWrap(True)
        self.chart = TrafficChart()
        self.pages_table = make_table(["Page", "Requests", "Data sent"])
        self.visitors_table = make_table(["Address", "Requests", "Data sent"])
        self.missing_table = make_table(["Page", "Requests"])
        self.referrers_table = make_table(["Site", "Requests"])
        self.statuses_table = make_table(["Status", "Requests"])
        tables = QGridLayout()
        for index, (title, table) in enumerate((("Top pages", self.pages_table), ("Top visitors", self.visitors_table),
                                                ("Not found", self.missing_table), ("Referrers", self.referrers_table),
                                                ("Status codes", self.statuses_table))):
            box = QGroupBox(title)
            QVBoxLayout(box).addWidget(table)
            tables.addWidget(box, index // 3, index % 3)
        self.source = QLabel()
        self.source.setWordWrap(True)

        controls = QHBoxLayout()
        controls.addWidget(QLabel("Range:"))
        controls.addWidget(self.range)
        controls.addWidget(QLabel("Chart:"))
        controls.addWidget(self.metric_box)
        controls.addWidget(refresh)
        controls.addStretch(1)
        layout = QVBoxLayout(self)
        layout.addLayout(controls)
        layout.addWidget(self.totals)
        layout.addWidget(self.notes)
        layout.addWidget(self.chart, 1)
        layout.addLayout(tables, 2)
        layout.addWidget(self.source)

    def metric_key(self) -> str:
        return self.metric_box.currentData()

    def clear(self) -> None:
        self.loaded_for = None
        self.show_traffic(None)

    def refresh(self) -> None:
        name = self.detail.name
        if not name:
            return
        traffic_range = self.range.currentData()
        self.loaded_for = name
        self.detail.busy(f"Reading {name}'s traffic…",
                         lambda: self.detail.connection.site_traffic(name, traffic_range), self.show_traffic)

    def show_traffic(self, traffic: dict | None) -> None:
        self.traffic = traffic
        self.chart.show_traffic(traffic, self.metric_key())
        if not traffic:
            self.totals.clear()
            self.notes.clear()
            self.source.clear()
            for table in (self.pages_table, self.visitors_table, self.missing_table, self.referrers_table,
                          self.statuses_table):
                table.setRowCount(0)
            return
        totals = traffic.get("totals") or {}
        requests = totals.get("requests") or 0
        errors = (totals.get("client_errors") or 0) + (totals.get("server_errors") or 0)

        def percent(n: int) -> str:
            return f" ({100 * n / requests:.1f}%)" if requests else ""

        self.totals.setText(f"Requests: {requests:,}    Data sent: {hm.format_bytes(totals.get('bytes') or 0)}    "
                            f"Visitors: {totals.get('visitors') or 0:,}    Errors: {errors:,}{percent(errors)}")
        notes = []
        if traffic.get("log_start") is not None:
            notes.append(f"The access log starts at {_when(traffic['log_start'])}.")
        if traffic.get("truncated"):
            notes.append("The access log is too long to read in full: these numbers cover only its most recent "
                         "requests.")
        self.notes.setText(" ".join(notes))
        self.notes.setVisible(bool(notes))
        fill_table(self.pages_table, [[r["path"], f"{r['requests']:,}", hm.format_bytes(r["bytes"])]
                                      for r in traffic.get("pages") or []])
        fill_table(self.visitors_table, [[r["ip"], f"{r['requests']:,}", hm.format_bytes(r["bytes"])]
                                         for r in traffic.get("visitors") or []])
        fill_table(self.missing_table, [[r["path"], f"{r['requests']:,}"] for r in traffic.get("missing") or []])
        fill_table(self.referrers_table, [[r["host"], f"{r['requests']:,}"] for r in traffic.get("referrers") or []])
        fill_table(self.statuses_table, [[r["status"], f"{r['requests']:,}{percent(r['requests'])}"]
                                         for r in traffic.get("statuses") or []])
        source = (f"From {traffic.get('log')}, {_when(traffic['start'])} to {_when(traffic['end'])}. "
                  "Visitors are distinct IP addresses.")
        unparsed = traffic.get("unparsed") or 0
        if unparsed:
            source += f" {unparsed:,} line{'' if unparsed == 1 else 's'} {'was' if unparsed == 1 else 'were'} " \
                      "not in nginx's log format."
        self.source.setText(source)
