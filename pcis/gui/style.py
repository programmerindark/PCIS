"""Visual styling for the PCIS desktop app.

Design intent
-------------
This is a working tool for a poultry house operator, often consulted
in a hurry and sometimes on a laptop in a shed. The styling choices
below follow from that rather than from decoration:

- **One accent colour, used sparingly.** A calm slate/teal palette,
  with saturated colour reserved for things that carry meaning:
  green/amber/red status, and the red unreachable-target warning. If
  everything is colourful, nothing reads as urgent.
- **Readable at a glance.** Larger base font than Qt's default,
  generous row spacing, and a clear type hierarchy, because the
  numbers on this screen get read quickly and acted on.
- **Grouped panels with visible structure.** Inputs are chunked into
  titled cards so the eye can find "the humidity one" without
  scanning every row.
- **Explicit focus states.** Keyboard-driven data entry (tab between
  fields, type, enter) should never leave you guessing which field is
  active.

Windows specifics
-----------------
Qt's default font on Windows renders small and tight. `Segoe UI` is
requested explicitly with fallbacks, sizes are set in points rather
than pixels so Windows display scaling works, and every input has a
minimum height so it doesn't collapse at 125%/150% scaling -- the
default on most modern Windows laptops, and the usual reason a Qt app
looks cramped there but fine on the developer's machine.
"""

from __future__ import annotations

# --- Palettes --------------------------------------------------------------
#
# Two complete palettes with identical keys. The app previously defined
# only light values, and any widget the stylesheet did not explicitly
# cover (QTextBrowser, plain container QWidgets) fell through to the
# system palette. On a machine running Windows in dark mode that
# produced near-black authored text on a dark system background -- the
# engineering explanation, the single densest thing on the screen, was
# effectively invisible.
#
# Fixing it by forcing light everywhere would have overridden a setting
# the user deliberately chose. Shipping both, and honouring the OS
# preference, is the correct behaviour for a desktop application.

LIGHT = {
    "INK": "#1a2027",
    "INK_MUTED": "#5a6672",
    "LINE": "#d8dee5",
    "SURFACE": "#ffffff",
    "CANVAS": "#eef1f5",
    "RAISED": "#e6f2f1",
    "ACCENT": "#0f766e",
    "ACCENT_HOVER": "#0d635c",
    "ACCENT_SOFT": "#e6f2f1",
    "ACCENT_TEXT": "#0f766e",
    "ON_ACCENT": "#ffffff",
    "OK": "#15803d",
    "WARN": "#b45309",
    "DANGER": "#b00020",
    "DANGER_SOFT": "#fdecef",
    "DANGER_TEXT": "#8c0019",
    "HEADER_BG": "#f5f7f9",
    "DIVIDER": "#f0f3f6",
    "SCROLL": "#c4ccd4",
    "DISABLED": "#a9b3bd",
}

DARK = {
    "INK": "#e7edf3",
    "INK_MUTED": "#9aa7b4",
    "LINE": "#2a3340",
    "SURFACE": "#151c26",
    "CANVAS": "#0b1220",
    "RAISED": "#16302e",
    "ACCENT": "#14b8a6",
    "ACCENT_HOVER": "#0f9c8c",
    "ACCENT_SOFT": "#16302e",
    "ACCENT_TEXT": "#5eead4",
    "ON_ACCENT": "#04201d",
    "OK": "#4ade80",
    "WARN": "#fbbf24",
    "DANGER": "#f87171",
    "DANGER_SOFT": "#2a1216",
    "DANGER_TEXT": "#fca5a5",
    "HEADER_BG": "#1b2430",
    "DIVIDER": "#212a36",
    "SCROLL": "#3a4552",
    "DISABLED": "#5c6875",
}

#: Colours of the theme currently in force. Rebound by `apply_theme`.
#: Exposed as module-level names so existing call sites (style.INK,
#: style.DANGER, ...) keep working without every caller learning about
#: theme objects.
INK = LIGHT["INK"]
INK_MUTED = LIGHT["INK_MUTED"]
LINE = LIGHT["LINE"]
SURFACE = LIGHT["SURFACE"]
CANVAS = LIGHT["CANVAS"]
ACCENT = LIGHT["ACCENT"]
ACCENT_HOVER = LIGHT["ACCENT_HOVER"]
ACCENT_SOFT = LIGHT["ACCENT_SOFT"]
OK = LIGHT["OK"]
WARN = LIGHT["WARN"]
DANGER = LIGHT["DANGER"]
DANGER_SOFT = LIGHT["DANGER_SOFT"]

FONT_STACK = '"Segoe UI", "Inter", "Noto Sans", system-ui, sans-serif'

_ACTIVE = dict(LIGHT)


def active() -> dict:
    """The palette currently applied."""
    return dict(_ACTIVE)


def system_prefers_dark() -> bool:
    """Whether the OS is asking for a dark UI.

    Uses Qt's own reported window colour rather than platform-specific
    registry or defaults reads: if the default window background is
    darker than mid-grey, the desktop is in dark mode. Works on
    Windows, macOS and Linux without branching per platform.
    """
    try:
        from PySide6.QtGui import QGuiApplication, QPalette

        app = QGuiApplication.instance()
        if app is None:
            return False
        bg = app.palette().color(QPalette.Window)
        # Rec. 601 luma; < 128 means a dark desktop.
        return (0.299 * bg.red() + 0.587 * bg.green() + 0.114 * bg.blue()) < 128
    except Exception:
        return False


#: Guard for `ensure_theme`. Applying an application-wide stylesheet
#: forces Qt to re-polish every existing widget in the process, so
#: doing it from a window constructor costs O(windows x widgets) every
#: time a window is created. Harmless with one window; it made a
#: 49-window test suite crawl to a halt.
_THEME_APPLIED = False


def ensure_theme(app, dark: bool | None = None) -> dict:
    """Apply the theme once per process; a no-op on later calls.

    Windows should call this rather than `apply_theme`, which is
    reserved for an explicit, deliberate re-theme.
    """
    global _THEME_APPLIED
    if _THEME_APPLIED:
        return active()
    _THEME_APPLIED = True
    return apply_theme(app, dark)


def apply_theme(app, dark: bool | None = None) -> dict:
    """Apply a full theme to `app`: stylesheet AND QPalette.

    Both are needed. The stylesheet covers widgets it names; the
    QPalette catches everything it does not -- native dialogs
    (QFileDialog, QMessageBox), tooltips, and any widget class added
    later that nobody remembered to style. Setting only the stylesheet
    is what left the explanation panel unreadable in the first place.

    `dark=None` follows the operating system.
    """
    global _ACTIVE, INK, INK_MUTED, LINE, SURFACE, CANVAS
    global ACCENT, ACCENT_HOVER, ACCENT_SOFT, OK, WARN, DANGER, DANGER_SOFT

    if dark is None:
        dark = system_prefers_dark()
    palette = DARK if dark else LIGHT
    _ACTIVE = dict(palette)

    INK, INK_MUTED, LINE = palette["INK"], palette["INK_MUTED"], palette["LINE"]
    SURFACE, CANVAS = palette["SURFACE"], palette["CANVAS"]
    ACCENT, ACCENT_HOVER = palette["ACCENT"], palette["ACCENT_HOVER"]
    ACCENT_SOFT = palette["ACCENT_SOFT"]
    OK, WARN = palette["OK"], palette["WARN"]
    DANGER, DANGER_SOFT = palette["DANGER"], palette["DANGER_SOFT"]

    try:
        from PySide6.QtGui import QColor, QPalette

        qp = QPalette()
        c = lambda k: QColor(palette[k])
        qp.setColor(QPalette.Window, c("CANVAS"))
        qp.setColor(QPalette.WindowText, c("INK"))
        qp.setColor(QPalette.Base, c("SURFACE"))
        qp.setColor(QPalette.AlternateBase, c("DIVIDER"))
        qp.setColor(QPalette.Text, c("INK"))
        qp.setColor(QPalette.PlaceholderText, c("INK_MUTED"))
        qp.setColor(QPalette.Button, c("SURFACE"))
        qp.setColor(QPalette.ButtonText, c("INK"))
        qp.setColor(QPalette.Highlight, c("ACCENT"))
        qp.setColor(QPalette.HighlightedText, c("ON_ACCENT"))
        qp.setColor(QPalette.ToolTipBase, c("INK"))
        qp.setColor(QPalette.ToolTipText, c("SURFACE"))
        qp.setColor(QPalette.Link, c("ACCENT_TEXT"))
        qp.setColor(QPalette.Disabled, QPalette.Text, c("DISABLED"))
        qp.setColor(QPalette.Disabled, QPalette.ButtonText, c("DISABLED"))
        qp.setColor(QPalette.Disabled, QPalette.WindowText, c("DISABLED"))
        app.setPalette(qp)
    except Exception:
        pass

    global _THEME_APPLIED
    _THEME_APPLIED = True
    app.setStyleSheet(build_stylesheet(palette))
    return palette


def status_color(fraction: float) -> str:
    """Colour for a 0-1 quality fraction (confidence, comfort index).

    Thresholds are presentation-only -- they change what colour a
    number is printed in, never the number itself or any engineering
    decision. Chosen to match how the values are already described in
    the explanation text: comfortable / marginal / stressed.
    """
    if fraction >= 0.75:
        return OK
    if fraction >= 0.5:
        return WARN
    return DANGER


def build_stylesheet(p: dict) -> str:
    """Render the stylesheet for a palette.

    Was previously a module-level f-string baked against the light
    palette only, which is why a dark desktop produced a half-styled
    window.
    """
    return f"""
QWidget {{
    font-family: {FONT_STACK};
    font-size: 10.5pt;
    color: {p['INK']};
}}

QMainWindow, QDialog {{
    background: {p['CANVAS']};
}}

/* ---------- Tabs ---------- */

QTabWidget::pane {{
    border: 1px solid {p['LINE']};
    border-radius: 8px;
    background: {p['SURFACE']};
    top: -1px;
}}

QTabBar::tab {{
    background: transparent;
    color: {p['INK_MUTED']};
    padding: 9px 18px;
    margin-right: 2px;
    border: 1px solid transparent;
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
    font-weight: 600;
}}

QTabBar::tab:hover {{
    color: {p['INK']};
    background: {p['ACCENT_SOFT']};
}}

QTabBar::tab:selected {{
    background: {p['SURFACE']};
    color: {p['ACCENT']};
    border: 1px solid {p['LINE']};
    border-bottom: 1px solid {p['SURFACE']};
}}

/* ---------- Cards ---------- */

QGroupBox {{
    background: {p['SURFACE']};
    border: 1px solid {p['LINE']};
    border-radius: 8px;
    margin-top: 14px;
    padding: 14px 14px 12px 14px;
    font-weight: 600;
}}

QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 12px;
    padding: 0 6px;
    color: {p['ACCENT']};
    font-size: 9.5pt;
    text-transform: uppercase;
    letter-spacing: 1px;
}}

/* ---------- Inputs ---------- */

QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
    background: {p['SURFACE']};
    border: 1px solid {p['LINE']};
    border-radius: 6px;
    padding: 6px 9px;
    min-height: 22px;
    selection-background-color: {p['ACCENT']};
    selection-color: white;
}}

QLineEdit:hover, QSpinBox:hover, QDoubleSpinBox:hover, QComboBox:hover {{
    border-color: {p['SCROLL']};
}}

QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {{
    border: 2px solid {p['ACCENT']};
    padding: 5px 8px;
}}

QComboBox::drop-down {{
    border: none;
    width: 22px;
}}

QComboBox QAbstractItemView {{
    background: {p['SURFACE']};
    border: 1px solid {p['LINE']};
    selection-background-color: {p['ACCENT_SOFT']};
    selection-color: {p['INK']};
    outline: none;
}}

QSpinBox::up-button, QDoubleSpinBox::up-button,
QSpinBox::down-button, QDoubleSpinBox::down-button {{
    width: 18px;
    border: none;
    background: transparent;
}}

/* ---------- Buttons ---------- */

QPushButton {{
    background: {p['SURFACE']};
    border: 1px solid {p['LINE']};
    border-radius: 6px;
    padding: 8px 16px;
    min-height: 22px;
    font-weight: 600;
    color: {p['INK']};
}}

QPushButton:hover {{
    border-color: {p['ACCENT']};
    color: {p['ACCENT']};
}}

QPushButton:pressed {{
    background: {p['ACCENT_SOFT']};
}}

QPushButton:disabled {{
    color: {p['DISABLED']};
    border-color: {p['LINE']};
    background: {p['CANVAS']};
}}

QPushButton[primary="true"] {{
    background: {p['ACCENT']};
    border: 1px solid {p['ACCENT']};
    color: white;
    padding: 10px 22px;
    font-size: 11pt;
}}

QPushButton[primary="true"]:hover {{
    background: {p['ACCENT_HOVER']};
    border-color: {p['ACCENT_HOVER']};
    color: white;
}}

QPushButton[primary="true"]:disabled {{
    background: {p['DISABLED']};
    border-color: {p['DISABLED']};
    color: {p['CANVAS']};
}}

/* ---------- Tables & lists ---------- */

QTableWidget, QListWidget {{
    background: {p['SURFACE']};
    border: 1px solid {p['LINE']};
    border-radius: 6px;
    gridline-color: {p['DIVIDER']};
    outline: none;
}}

QTableWidget::item, QListWidget::item {{
    padding: 5px 7px;
}}

QListWidget::item {{
    border-bottom: 1px solid {p['DIVIDER']};
}}

QTableWidget::item:selected, QListWidget::item:selected {{
    background: {p['ACCENT_SOFT']};
    color: {p['INK']};
}}

QHeaderView::section {{
    background: {p['HEADER_BG']};
    color: {p['INK_MUTED']};
    border: none;
    border-bottom: 1px solid {p['LINE']};
    border-right: 1px solid {p['DIVIDER']};
    padding: 7px 8px;
    font-weight: 600;
    font-size: 9.5pt;
}}

/* ---------- Scrollbars ---------- */

QScrollBar:vertical {{
    background: transparent;
    width: 11px;
    margin: 0;
}}

QScrollBar::handle:vertical {{
    background: {p['SCROLL']};
    border-radius: 5px;
    min-height: 28px;
}}

QScrollBar::handle:vertical:hover {{
    background: {p['SCROLL']};
}}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}

QScrollBar:horizontal {{
    background: transparent;
    height: 11px;
}}

QScrollBar::handle:horizontal {{
    background: {p['SCROLL']};
    border-radius: 5px;
    min-width: 28px;
}}

QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    width: 0;
}}

/* ---------- Misc ---------- */

QToolTip {{
    background: {p['INK']};
    color: white;
    border: none;
    border-radius: 4px;
    padding: 6px 9px;
}}

QLabel[hint="true"] {{
    color: {p['INK_MUTED']};
    font-size: 9.5pt;
}}

QLabel[sectionHeader="true"] {{
    font-size: 13pt;
    font-weight: 700;
    color: {p['INK']};
}}

/* ---------- Widgets that previously fell through ---------- */
/* Each of these was unstyled, so on a dark desktop Qt painted them
   with the system dark palette while our authored text stayed dark --
   the cause of the unreadable explanation panel. */

QTextBrowser, QTextEdit, QPlainTextEdit {{
    background: {p['SURFACE']};
    color: {p['INK']};
    border: 1px solid {p['LINE']};
    border-radius: 6px;
    padding: 6px;
    selection-background-color: {p['ACCENT']};
    selection-color: {p['ON_ACCENT']};
}}

QScrollArea, QScrollArea > QWidget > QWidget {{
    background: transparent;
}}

QSplitter::handle, QFrame[frameShape="4"] {{
    background: {p['LINE']};
}}

QMenu {{
    background: {p['SURFACE']};
    color: {p['INK']};
    border: 1px solid {p['LINE']};
}}
QMenu::item:selected {{ background: {p['ACCENT_SOFT']}; }}

QMessageBox, QFileDialog {{
    background: {p['CANVAS']};
    color: {p['INK']};
}}

QChartView {{ background: transparent; }}
"""


#: Default stylesheet (light), kept for callers that have not migrated
#: to `apply_theme`. Prefer `apply_theme(app)`, which also sets the
#: QPalette that native dialogs and unstyled widgets depend on.
APP_STYLESHEET = build_stylesheet(LIGHT)
