"""App-wide look: one Fusion-based light/dark theme applied the same way on
Linux, Windows and macOS, instead of each platform's native style (which
left the app looking different -- and dated -- everywhere, with nothing
but hardcoded "color: gray"/"#c9190b" one-offs on top).

Everything visual hangs off a small set of named colors (Tokens): a
QPalette for the widgets that only read the palette, plus one app-wide
stylesheet for the shapes (radii, padding, tab/nav styling) the palette
can't express. Widgets that need a semantic color (an error label, a muted
hint) ask for it via set_tone()/color() rather than hardcoding one, so
it stays readable in both light and dark mode.

Mode is "system" (follow the OS light/dark setting, live), "light" or
"dark" -- see Settings > General > Appearance.
"""

import tempfile
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QByteArray, QObject, Qt, Signal
from PySide6.QtGui import QColor, QGuiApplication, QIcon, QPainter, QPalette, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QApplication, QWidget

_ICON_DIR = Path(__file__).resolve().parent.parent / "resources" / "icons" / "ui"

MODES = ("system", "light", "dark")


@dataclass(frozen=True)
class Tokens:
    window: str  # app background behind cards/panes
    surface: str  # cards, inputs, lists
    sidebar: str
    raised: str  # hover / alternate rows / tab bar
    border: str
    text: str
    muted: str
    accent: str
    accent_text: str  # text drawn on top of accent
    accent_soft: str  # selection tint behind normal text
    success: str
    warning: str
    danger: str


LIGHT = Tokens(
    window="#f4f5f7",
    surface="#ffffff",
    sidebar="#eceef2",
    raised="#e6e8ec",
    border="#d5d8de",
    text="#1d2330",
    muted="#677083",
    accent="#2563eb",
    accent_text="#ffffff",
    accent_soft="#dbe6fd",
    success="#15803d",
    warning="#b45309",
    danger="#c62828",
)

DARK = Tokens(
    window="#16181d",
    surface="#1e2128",
    sidebar="#121418",
    raised="#2a2e37",
    border="#343945",
    text="#e4e7ec",
    muted="#959cab",
    accent="#4f8cff",
    accent_text="#ffffff",
    accent_soft="#233456",
    success="#4ade80",
    warning="#fbbf24",
    danger="#f87171",
)


# The embedded terminal stays dark in both modes (see TerminalWidget).
TERMINAL_BACKGROUND = "#101318"
TERMINAL_FOREGROUND = "#d8dce4"


class _ThemeEvents(QObject):
    #: Emitted after the palette/stylesheet change, for widgets that cache
    #: tinted icons or custom-painted colors.
    changed = Signal()


events = _ThemeEvents()
_mode = "system"
_current = LIGHT
_following_os = False


def current() -> Tokens:
    return _current


def is_dark() -> bool:
    return _current is DARK


def color(name: str) -> QColor:
    return QColor(getattr(_current, name))


def set_tone(widget: QWidget, tone: str | None) -> None:
    """Gives a label (or any widget's text) a semantic color -- "muted",
    "danger", "warning", "success" or "accent" -- or back to the normal
    text color with None. Done through a dynamic property the app
    stylesheet matches on, rather than a per-widget color, so it follows
    light/dark switches on its own."""
    widget.setProperty("tone", tone or "")
    # Qt only re-matches property selectors on a re-polish.
    widget.style().unpolish(widget)
    widget.style().polish(widget)


def icon(name: str, color_name: str = "text", size: int = 64) -> QIcon:
    """A bundled Lucide line icon (resources/icons/ui/<name>.svg) tinted
    with a theme color. Lucide strokes with currentColor, so tinting is
    just a substitution before rasterizing (selected rows get the accent)."""
    path = _ICON_DIR / f"{name}.svg"
    if not path.is_file():
        return QIcon()
    svg = path.read_text(encoding="utf-8")
    result = QIcon()
    for mode, tint in (
        (QIcon.Mode.Normal, getattr(_current, color_name)),
        (QIcon.Mode.Selected, _current.accent),
        (QIcon.Mode.Disabled, _current.muted),
    ):
        # Rendered straight at `size` (not rasterized at the SVG's own
        # 24px and scaled up), so it stays crisp on HiDPI screens.
        renderer = QSvgRenderer(QByteArray(svg.replace("currentColor", tint).encode()))
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        renderer.render(painter)
        painter.end()
        result.addPixmap(pixmap, mode)
    return result


_glyph_dir: Path | None = None


def _glyph(name: str, tint: str, stroke: str = "2") -> str:
    """Path to a tinted copy of a bundled icon, for stylesheet url()s
    (checkbox ticks, combo/spin arrows) -- QSS can only load images from
    files, not recolor them, so each tint gets written out once."""
    global _glyph_dir
    if _glyph_dir is None:
        _glyph_dir = Path(tempfile.mkdtemp(prefix="it-toolbox-theme-"))
    target = _glyph_dir / f"{name}-{tint.lstrip('#')}.svg"
    if not target.is_file():
        svg = (_ICON_DIR / f"{name}.svg").read_text(encoding="utf-8")
        svg = svg.replace("currentColor", tint).replace('stroke-width="2"', f'stroke-width="{stroke}"')
        target.write_text(svg, encoding="utf-8")
    return target.as_posix()


def _palette(t: Tokens) -> QPalette:
    p = QPalette()
    roles = QPalette.ColorRole
    p.setColor(roles.Window, QColor(t.window))
    p.setColor(roles.WindowText, QColor(t.text))
    p.setColor(roles.Base, QColor(t.surface))
    p.setColor(roles.AlternateBase, QColor(t.raised))
    p.setColor(roles.ToolTipBase, QColor(t.surface))
    p.setColor(roles.ToolTipText, QColor(t.text))
    p.setColor(roles.PlaceholderText, QColor(t.muted))
    p.setColor(roles.Text, QColor(t.text))
    p.setColor(roles.Button, QColor(t.surface))
    p.setColor(roles.ButtonText, QColor(t.text))
    p.setColor(roles.BrightText, QColor(t.danger))
    p.setColor(roles.Highlight, QColor(t.accent))
    p.setColor(roles.HighlightedText, QColor(t.accent_text))
    p.setColor(roles.Link, QColor(t.accent))
    p.setColor(roles.LinkVisited, QColor(t.accent))
    p.setColor(roles.Mid, QColor(t.border))
    p.setColor(roles.Midlight, QColor(t.raised))
    p.setColor(roles.Dark, QColor(t.border))
    p.setColor(roles.Shadow, QColor("#000000"))
    for role in (roles.WindowText, roles.Text, roles.ButtonText):
        p.setColor(QPalette.ColorGroup.Disabled, role, QColor(t.muted))
    return p


def _stylesheet(t: Tokens) -> str:
    check = _glyph("check", t.accent_text, "3")
    partial = _glyph("minus", t.accent_text, "3")
    down = _glyph("chevron-down", t.muted)
    up = _glyph("chevron-up", t.muted)
    right = _glyph("chevron-right", t.muted)
    close = _glyph("x", t.muted)
    close_hover = _glyph("x", t.text)
    return f"""
QToolTip {{ background: {t.surface}; color: {t.text}; border: 1px solid {t.border};
    border-radius: 6px; padding: 4px 8px; }}

/* Sidebar column */
#Sidebar {{ background: {t.sidebar}; border-right: 1px solid {t.border}; }}
#Sidebar QTreeWidget, #Sidebar QTreeView, #Sidebar QListWidget {{ background: transparent; border: none; }}
#SidebarBrand {{ font-size: 12pt; font-weight: 600; padding: 14px 14px 8px 14px; }}
#ModuleNav {{ background: transparent; border: none; outline: 0; padding: 0 8px; }}
#ModuleNav::item {{ padding: 7px 8px; border-radius: 6px; margin: 1px 0; color: {t.text}; }}
#ModuleNav::item:hover {{ background: {t.raised}; }}
#ModuleNav::item:selected {{ background: {t.accent_soft}; color: {t.text}; font-weight: 600; }}
#SidebarDivider {{ background: {t.border}; margin: 0 12px; }}
#Sidebar QHeaderView {{ background: transparent; }}
#Sidebar QTreeView {{ show-decoration-selected: 1; }}
#Sidebar QTreeView::item {{ padding: 4px 2px; }}
#Sidebar QTreeView::item:selected, #Sidebar QTreeView::branch:selected {{ background: {t.accent_soft}; }}
#Sidebar QHeaderView::section {{ background: transparent; border: none; color: {t.muted};
    font-size: 8pt; font-weight: 600; text-transform: uppercase; padding: 6px 12px 4px 12px; }}
#Sidebar QLineEdit {{ margin: 4px 10px; }}

/* Lists/trees */
QTreeView, QListView, QTableView {{ background: {t.surface}; border: 1px solid {t.border};
    border-radius: 8px; outline: 0; selection-background-color: {t.accent_soft};
    selection-color: {t.text}; alternate-background-color: {t.window}; }}
QTreeView::item, QListView::item {{ padding: 4px 2px; border-radius: 4px; }}
QTreeView::item:hover, QListView::item:hover {{ background: {t.raised}; }}
QTreeView::item:selected, QListView::item:selected {{ background: {t.accent_soft}; color: {t.text}; }}
QTableView {{ gridline-color: {t.raised}; }}
QTableView::item {{ padding: 2px 6px; }}
QTableView::item:selected {{ background: {t.accent_soft}; color: {t.text}; }}
QHeaderView::section {{ background: {t.window}; color: {t.muted}; border: none;
    border-bottom: 1px solid {t.border}; padding: 6px 8px; font-weight: 600; }}

/* Inputs */
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QDateTimeEdit, QPlainTextEdit, QTextEdit {{
    background: {t.surface}; border: 1px solid {t.border}; border-radius: 6px;
    padding: 5px 8px; selection-background-color: {t.accent}; selection-color: {t.accent_text}; }}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus,
QPlainTextEdit:focus, QTextEdit:focus {{ border: 1px solid {t.accent}; }}
QComboBox::drop-down {{ border: none; width: 24px; }}
QComboBox::down-arrow {{ image: url({down}); width: 14px; height: 14px; }}
QSpinBox::up-button, QSpinBox::down-button, QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{
    border: none; width: 18px; }}
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {{ image: url({up}); width: 12px; height: 12px; }}
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{ image: url({down}); width: 12px; height: 12px; }}

/* Check boxes / radio buttons */
QCheckBox, QRadioButton {{ spacing: 8px; }}
QCheckBox::indicator, QTreeView::indicator, QListView::indicator {{ width: 16px; height: 16px;
    border: 1px solid {t.muted}; border-radius: 4px; background: {t.surface}; }}
QCheckBox::indicator:hover, QRadioButton::indicator:hover {{ border-color: {t.accent}; }}
QCheckBox::indicator:checked, QTreeView::indicator:checked, QListView::indicator:checked {{
    background: {t.accent}; border-color: {t.accent}; image: url({check}); }}
QCheckBox::indicator:indeterminate, QTreeView::indicator:indeterminate {{
    background: {t.accent}; border-color: {t.accent}; image: url({partial}); }}
QCheckBox::indicator:disabled {{ background: {t.raised}; border-color: {t.border}; }}
QRadioButton::indicator {{ width: 16px; height: 16px; border: 1px solid {t.muted};
    border-radius: 9px; background: {t.surface}; }}
QRadioButton::indicator:checked {{ border: 5px solid {t.accent}; background: {t.accent_text}; }}

/* Tree branch arrows */
QTreeView::branch:closed:has-children {{ image: url({right}); }}
QTreeView::branch:open:has-children {{ image: url({down}); }}
QComboBox QAbstractItemView {{ border: 1px solid {t.border}; border-radius: 6px; padding: 4px; }}

/* Buttons */
QPushButton, QToolButton {{ background: {t.surface}; border: 1px solid {t.border};
    border-radius: 6px; padding: 5px 14px; }}
QPushButton:hover, QToolButton:hover {{ background: {t.raised}; }}
QPushButton:pressed, QToolButton:pressed {{ background: {t.border}; }}
QPushButton:default {{ background: {t.accent}; color: {t.accent_text}; border-color: {t.accent}; }}
QPushButton:disabled, QToolButton:disabled {{ color: {t.muted}; background: {t.window}; }}
QToolButton {{ padding: 4px 8px; }}
QToolButton[autoRaise="true"] {{ border: none; background: transparent; }}
QToolButton[autoRaise="true"]:hover {{ background: {t.raised}; }}

/* Group boxes as cards */
QGroupBox {{ background: {t.surface}; border: 1px solid {t.border}; border-radius: 10px;
    margin-top: 26px; padding: 12px 10px 10px 10px; }}
QGroupBox::title {{ subcontrol-origin: margin; subcontrol-position: top left;
    left: 4px; top: 4px; padding: 0 2px; font-weight: 600; font-size: 10.5pt; }}

/* Tabs */
QTabWidget::pane {{ border: 1px solid {t.border}; border-radius: 8px; background: {t.surface}; top: -1px; }}
QTabBar::tab {{ background: transparent; color: {t.muted}; padding: 7px 14px;
    border: none; border-bottom: 2px solid transparent; margin-right: 2px; }}
QTabBar::tab:hover {{ color: {t.text}; background: {t.raised}; border-top-left-radius: 6px;
    border-top-right-radius: 6px; }}
QTabBar {{ qproperty-drawBase: 0; }}
QTabBar::close-button {{ image: url({close}); subcontrol-position: right; border-radius: 4px;
    width: 14px; height: 14px; margin-left: 4px; }}
QTabBar::close-button:hover {{ image: url({close_hover}); background: {t.border}; }}
QTabBar::tab:selected {{ color: {t.text}; border-bottom: 2px solid {t.accent}; font-weight: 600; }}

/* Chrome */
QSplitter::handle {{ background: {t.border}; }}
QSplitter::handle:horizontal {{ width: 1px; }}
QSplitter::handle:vertical {{ height: 1px; }}
QStatusBar {{ background: {t.sidebar}; color: {t.muted}; border-top: 1px solid {t.border}; }}
QStatusBar::item {{ border: none; }}
QMenu {{ background: {t.surface}; border: 1px solid {t.border}; border-radius: 8px; padding: 4px; }}
QMenu::item {{ padding: 6px 22px 6px 12px; border-radius: 4px; }}
QMenu::item:selected {{ background: {t.accent_soft}; color: {t.text}; }}
QMenu::separator {{ height: 1px; background: {t.border}; margin: 4px 6px; }}
QProgressBar {{ background: {t.raised}; border: none; border-radius: 4px; text-align: center;
    min-height: 8px; max-height: 14px; color: {t.text}; }}
QProgressBar::chunk {{ background: {t.accent}; border-radius: 4px; }}
QScrollArea {{ border: none; background: transparent; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle {{ background: {t.border}; border-radius: 3px; min-height: 24px; min-width: 24px; }}
QScrollBar::handle:hover {{ background: {t.muted}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

/* Embedded terminal (widgets/terminal_widget.py) */
QPlainTextEdit#Terminal {{ background: {TERMINAL_BACKGROUND}; color: {TERMINAL_FOREGROUND};
    border: none; border-radius: 0; padding: 4px 6px;
    selection-background-color: {t.accent}; selection-color: {t.accent_text}; }}

/* Semantic text colors -- see set_tone() */
*[tone="muted"] {{ color: {t.muted}; }}
*[tone="danger"] {{ color: {t.danger}; }}
*[tone="warning"] {{ color: {t.warning}; }}
*[tone="success"] {{ color: {t.success}; }}
*[tone="accent"] {{ color: {t.accent}; }}

/* Empty state shown in place of the session-tab pane */
#EmptyState QLabel#EmptyTitle {{ font-size: 13pt; font-weight: 600; }}
#EmptyState QLabel#EmptyHint {{ color: {t.muted}; }}
"""


def _resolve(mode: str) -> Tokens:
    if mode == "light":
        return LIGHT
    if mode == "dark":
        return DARK
    scheme = QGuiApplication.styleHints().colorScheme()
    return DARK if scheme == Qt.ColorScheme.Dark else LIGHT


def apply(app: QApplication, mode: str | None = None) -> None:
    """Applies the theme to the whole app. Call once at startup (after
    QApplication exists, before any window is built) and again whenever
    Settings changes the mode; None re-applies the current mode."""
    global _mode, _current, _following_os
    if mode is not None:
        _mode = mode if mode in MODES else "system"
    if not _following_os:
        _following_os = True
        QGuiApplication.styleHints().colorSchemeChanged.connect(
            lambda _scheme: _mode == "system" and apply(app)
        )
    app.setStyle("Fusion")
    _current = _resolve(_mode)
    app.setPalette(_palette(_current))
    app.setStyleSheet(_stylesheet(_current))
    events.changed.emit()
