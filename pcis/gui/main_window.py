"""PCIS desktop GUI main window (PySide6).

This window is a thin wiring layer: it gathers user input, calls the
already-tested engineering modules (`pcis.core.*`), and displays the
result. It contains NO new engineering logic of its own -- every
number shown here comes from a function that already has its own
citation and unit tests. If you want to know why a number is what it
is, the answer lives in `pcis/core/*.py` and `PROGRESS.md`, not here.

Layout: a QTabWidget with five tabs (House & Equipment, Flock,
Environment, Recommendation, Schedule). The Recommendation tab answers
"what should be running right now"; the Schedule tab answers "how many
fans, at what time, for how long" via `pcis.core.digital_twin`.

Units
-----
The unit selector in the header switches every displayed value between
metric and imperial. This is display-only: `UnitAwareSpinBox` stores
its value in SI internally and converts only for presentation, so the
engineering core and the database never see anything but SI no matter
what is selected on screen. See `pcis/gui/units.py`.
"""

from __future__ import annotations

import datetime as dt
import logging
import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)
from sqlalchemy.orm import Session

LOG = logging.getLogger(__name__)

from pcis.core import digital_twin as twin
from pcis.core import growth_curve as gc
from pcis.core import heat_moisture_balance as hmb
from pcis.core import recommendation_engine as rec_engine
from pcis.db.session import (
    all_recommendation_logs,
    count_recommendation_logs,
    delete_recommendation_logs,
    export_recommendation_logs_csv,
    get_or_create_house_config,
    init_db,
    save_flock_record,
    save_recommendation,
    set_recommendation_test_flag,
)
from pcis.equipment.cooling_pad import COOLING_PAD_CATALOG, CoolingPad
from pcis.equipment.fan_curve import FAN_CATALOG, FanCurve
from pcis.gui import style, units
from pcis import config, logging_setup, paths, update_service, version
from pcis.gui.charts import ComfortChartWidget, FanCurveChartWidget, ScheduleChartWidget
from pcis.reports.pdf_report import generate_recommendation_report


class UnitAwareSpinBox(QDoubleSpinBox):
    """A spinbox that holds an SI value but displays a converted one.

    The critical property: `si_value()` always returns SI regardless of
    what unit system is selected. Callers that feed the engineering
    core must use `si_value()`/`set_si_value()`, never `value()`.

    Range limits are given in SI and converted alongside the value, so
    switching units never silently clamps a legitimate entry.
    """

    def __init__(
        self,
        quantity: str,
        si_minimum: float,
        si_maximum: float,
        si_value: float,
        decimals: int = 2,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._quantity = quantity
        self._si_min = si_minimum
        self._si_max = si_maximum
        self._system = units.METRIC
        self._si_exact = si_value
        self.setDecimals(decimals)
        self._apply_system(units.METRIC, si_value)

    def _converters(self, system: units.UnitSystem):
        return (
            getattr(system, f"{self._quantity}_from_si"),
            getattr(system, f"{self._quantity}_to_si"),
        )

    def _apply_system(self, system: units.UnitSystem, si_value: float) -> None:
        from_si, _ = self._converters(system)
        self._system = system
        lo, hi = from_si(self._si_min), from_si(self._si_max)
        if lo > hi:  # no current quantity inverts, but be safe
            lo, hi = hi, lo
        self.blockSignals(True)
        self.setRange(lo, hi)
        self.setSuffix(getattr(system, f"{self._quantity}_suffix"))
        self.setValue(from_si(si_value))
        self.blockSignals(False)
        self._si_exact = si_value

    def set_unit_system(self, system: units.UnitSystem) -> None:
        """Re-display the same physical value in a different system."""
        self._apply_system(system, self.si_value())

    def si_value(self) -> float:
        """The value in SI.

        Returns the exact stored SI value when the box still displays
        an unedited rendering of it, rather than converting the
        displayed number back. The box shows 2 decimals, so 150 m
        renders as 492.13 ft and converts back to 150.0012 m -- a
        harmless 1.2 mm on a house, but it compounds every time the
        user toggles units, and it makes "switch units twice" fail to
        return the original number. Preferring the stored value keeps
        unit switching exactly lossless while still honouring real
        edits.
        """
        from_si, to_si = self._converters(self._system)
        from_display = to_si(self.value())
        displayed_exact = round(from_si(self._si_exact), self.decimals())
        if abs(self.value() - displayed_exact) < 10 ** (-self.decimals()) / 2:
            return self._si_exact
        return from_display

    def set_si_value(self, si_value: float) -> None:
        from_si, _ = self._converters(self._system)
        self.blockSignals(True)
        self.setValue(from_si(si_value))
        self.blockSignals(False)
        self._si_exact = si_value


#: Qt item-data role used to stash the exact SI value behind a table
#: cell whose text is a rounded, human-readable rendering of it.
SI_ROLE = Qt.UserRole + 1


def _si_cell(display_value: float, si_value: float) -> QTableWidgetItem:
    """A table cell showing a rounded value but remembering exact SI.

    Formatting a number for display loses precision (0.6 W/m²K becomes
    "0.105672" in imperial, which converts back to 0.5999994). That
    drift is invisible per switch but compounds if a user toggles units
    repeatedly. Stashing the exact SI value on the item makes the
    round-trip lossless while still showing a readable number.
    """
    item = QTableWidgetItem(f"{display_value:g}")
    item.setData(SI_ROLE, si_value)
    return item


def _cell_si_value(item: QTableWidgetItem | None, display_text_to_si) -> float:
    """Exact SI for a cell, preferring the stashed value when the text
    has not been edited since it was written.

    If the user has typed in the cell, the stashed value is stale and
    the typed text wins -- otherwise edits would be silently ignored.
    """
    if item is None:
        return 0.0
    typed = float(item.text())
    stashed = item.data(SI_ROLE)
    if stashed is not None and f"{stashed:g}" != item.text():
        # Text differs from a plain rendering of the stashed SI; it may
        # be a converted display value OR a user edit. Distinguish by
        # re-rendering the stashed SI in the current system.
        from_display = display_text_to_si(typed)
        # Tolerance sized to swallow display rounding (%g keeps 6
        # significant figures, so round-trip drift lands around 1e-6
        # relative) while still catching any edit a human would
        # actually make -- nobody retypes a value to change it by
        # 0.01%.
        if abs(from_display - float(stashed)) <= abs(float(stashed)) * 1e-4:
            return float(stashed)
        return from_display
    if stashed is not None:
        return float(stashed)
    return display_text_to_si(typed)


class MetricsPanel(QWidget):
    """Headline result metrics that reflow to fit the available width.

    A fixed 5-column grid collided at the window's minimum width: at
    940px "GOVERNING CONSTRAINT" and "CONFIDENCE" rendered with zero gap
    between them, which reads as one run-on label. Equal-width columns
    cannot solve this, because the captions differ in length by 3x.

    Instead each metric declares a minimum readable width and the panel
    recomputes its column count on resize, wrapping to a second row when
    the window is narrow. That keeps the labels legible at every size
    rather than only at the size it was designed on.
    """

    #: Width below which a metric's caption starts to crowd its neighbour,
    #: measured from the longest caption ("GOVERNING CONSTRAINT") plus
    #: breathing room.
    MIN_COLUMN_PX = 190

    def __init__(self, specs: list[tuple[str, str]], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._grid = QGridLayout(self)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setHorizontalSpacing(18)
        self._grid.setVerticalSpacing(14)

        self._cells: list[QWidget] = []
        self.value_labels: dict[str, QLabel] = {}

        for key, caption in specs:
            cell = QWidget()
            v = QVBoxLayout(cell)
            v.setContentsMargins(0, 0, 0, 0)
            v.setSpacing(2)
            cap = QLabel(caption.upper())
            cap.setProperty("hint", True)
            cap.setWordWrap(True)
            value = QLabel("—")
            vf = QFont()
            vf.setPointSize(17)
            vf.setWeight(QFont.Bold)
            value.setFont(vf)
            value.setWordWrap(True)
            v.addWidget(cap)
            v.addWidget(value)
            cell.setMinimumWidth(self.MIN_COLUMN_PX)
            self._cells.append(cell)
            self.value_labels[key] = value

        self._columns = 0
        self._relayout(len(specs))

    def _relayout(self, columns: int) -> None:
        if columns == self._columns:
            return
        self._columns = columns
        while self._grid.count():
            self._grid.takeAt(0)
        for i, cell in enumerate(self._cells):
            self._grid.addWidget(cell, i // columns, i % columns)
        for c in range(self._grid.columnCount()):
            self._grid.setColumnStretch(c, 1 if c < columns else 0)

    def columns_for_width(self, width: int) -> int:
        """How many columns fit in `width`.

        Split out from `resizeEvent` so the reflow rule can be tested
        directly: Qt does not deliver resize events to widgets that
        have never been shown, so a test that only called `resize()`
        silently exercised nothing.
        """
        spacing = self._grid.horizontalSpacing()
        fits = (max(1, width) + spacing) // (self.MIN_COLUMN_PX + spacing)
        return max(1, min(len(self._cells), int(fits)))

    def apply_width(self, width: int) -> None:
        """Reflow for the given width. Called by `resizeEvent`."""
        self._relayout(self.columns_for_width(width))

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.apply_width(self.width())

    def set_value(self, key: str, text: str, color: str | None = None) -> None:
        label = self.value_labels[key]
        label.setText(text)
        label.setStyleSheet(f"color: {color};" if color else "")


class ExplanationView(QTextBrowser):
    """Scrollable, properly wrapping view of the explanation lines.

    Why not QListWidget: its `setWordWrap(True)` is unreliable for long
    strings -- it elides with an ellipsis instead of wrapping, which
    silently truncated the single most important sentence on the
    screen (the unreachable-target warning ended mid-clause). An
    explanation the user cannot finish reading is worse than no
    explanation, because it looks complete.

    Keeps a list-like API (`addItems`/`clear`/`count`) so callers and
    tests can still assert that every line produced by the engine is
    actually displayed.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setOpenExternalLinks(False)
        self._items: list[str] = []

    def clear(self) -> None:  # type: ignore[override]
        self._items = []
        super().clear()

    def addItems(self, lines: list[str]) -> None:
        self._items.extend(lines)
        self._render()

    def count(self) -> int:
        return len(self._items)

    def item_texts(self) -> list[str]:
        return list(self._items)

    def _render(self) -> None:
        rows = []
        for line in self._items:
            escaped = (
                line.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            )
            # Deductions and warnings are the lines a user most needs to
            # notice, so they are tinted rather than left as body text.
            # Read the ACTIVE palette each render. Using the import-time
            # module constants meant this panel kept painting dark text
            # after a dark theme was applied -- the exact reason the
            # explanation was unreadable on a dark desktop.
            pal = style.active()
            if "WARNING" in line:
                color = pal["DANGER"]
                weight = "600"
            elif line.lstrip().startswith("-"):
                color = pal["WARN"]
                weight = "500"
            else:
                color = pal["INK"]
                weight = "400"
            rows.append(
                f'<div style="margin: 0 0 9px 0; color: {color}; font-weight: {weight};">'
                f"{escaped}</div>"
            )
        self.setHtml("".join(rows))


def _hint(text: str) -> QLabel:
    label = QLabel(text)
    label.setWordWrap(True)
    label.setProperty("hint", True)
    return label


def _scrollable(inner: QWidget) -> QScrollArea:
    """Wrap a tab body in a scroll area.

    Windows display scaling at 125%/150% makes every widget taller; a
    form that fits at 100% can overflow the window at 150% and leave
    controls unreachable. Scrolling costs nothing when it isn't needed
    and prevents that failure entirely.
    """
    area = QScrollArea()
    area.setWidget(inner)
    area.setWidgetResizable(True)
    area.setFrameShape(QFrame.NoFrame)
    return area


class EnvelopeSurfaceEditor(QWidget):
    """Editable table of building-envelope surfaces (name / U-value /
    area), backed 1:1 by `pcis.core.heat_moisture_balance.Surface`.

    Values are entered and stored in SI. Column headers show the
    current unit system's labels, and switching systems converts the
    displayed numbers -- the underlying `Surface` objects handed to the
    engineering core are always SI.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._system = units.METRIC
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.table = QTableWidget(0, 3)
        self._refresh_headers()
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Interactive)
        header.setStretchLastSection(True)
        header.setMinimumSectionSize(90)
        self.table.setAlternatingRowColors(True)
        # Interactive sections start at Qt's default width, which is
        # narrower than these headers -- "Surface name" rendered as
        # "urface nam". Size to the header text once; the user can still
        # drag from there.
        self.table.resizeColumnsToContents()
        for col in range(self.table.columnCount() - 1):
            self.table.setColumnWidth(col, max(self.table.columnWidth(col) + 24, 130))
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.setMinimumHeight(140)
        layout.addWidget(self.table)

        buttons = QHBoxLayout()
        add_btn = QPushButton("Add surface")
        add_btn.clicked.connect(lambda: self.add_row())
        remove_btn = QPushButton("Remove selected")
        remove_btn.clicked.connect(self.remove_selected)
        buttons.addWidget(add_btn)
        buttons.addWidget(remove_btn)
        buttons.addStretch(1)
        layout.addLayout(buttons)

        # Seed with two typical rows the user can edit rather than
        # starting from a totally blank table.
        self.add_row("sidewalls", 0.6, 350.0)
        self.add_row("ceiling", 0.4, 1500.0)

    def _refresh_headers(self) -> None:
        s = self._system
        self.table.setHorizontalHeaderLabels(
            ["Surface name", f"U-value ({s.u_value_suffix.strip()})", f"Area ({s.area_suffix.strip()})"]
        )

    def set_unit_system(self, system: units.UnitSystem) -> None:
        surfaces = self._read_si_rows()
        self._system = system
        self._refresh_headers()
        self.table.setRowCount(0)
        for name, u_si, area_si in surfaces:
            self.add_row(name, u_si, area_si)

    def _read_si_rows(self) -> list[tuple[str, float, float]]:
        """Current rows as (name, u_si, area_si), tolerating bad cells."""
        rows = []
        for row in range(self.table.rowCount()):
            name_item = self.table.item(row, 0)
            name = name_item.text() if name_item else f"surface_{row}"
            try:
                u_si = _cell_si_value(self.table.item(row, 1), self._system.u_value_to_si)
                area_si = _cell_si_value(self.table.item(row, 2), self._system.area_to_si)
            except ValueError:
                u_si, area_si = 0.0, 0.0
            rows.append((name, u_si, area_si))
        return rows

    def add_row(self, name: str = "surface", u_value: float = 0.5, area_m2: float = 100.0) -> None:
        """Add a row. `u_value` and `area_m2` are SI; they are converted
        for display according to the current unit system.
        """
        row = self.table.rowCount()
        self.table.insertRow(row)
        self.table.setItem(row, 0, QTableWidgetItem(name))
        self.table.setItem(row, 1, _si_cell(self._system.u_value_from_si(u_value), u_value))
        self.table.setItem(row, 2, _si_cell(self._system.area_from_si(area_m2), area_m2))

    def remove_selected(self) -> None:
        for index in sorted({i.row() for i in self.table.selectedIndexes()}, reverse=True):
            self.table.removeRow(index)

    def surfaces(self) -> list[hmb.Surface]:
        """Read the table back out as domain objects, in SI. Raises
        ValueError (surfaced to the user via a message box by the
        caller) if any row has invalid numbers.
        """
        result = []
        for row in range(self.table.rowCount()):
            name_item = self.table.item(row, 0)
            u_item = self.table.item(row, 1)
            a_item = self.table.item(row, 2)
            name = name_item.text() if name_item else f"surface_{row}"
            try:
                u_si = _cell_si_value(u_item, self._system.u_value_to_si)
                area_si = _cell_si_value(a_item, self._system.area_to_si)
            except ValueError as exc:
                raise ValueError(f"Row {row + 1} ({name}): U-value and area must be numbers") from exc
            result.append(hmb.Surface(name=name, u_value=u_si, area_m2=area_si))
        return result


class MainWindow(QMainWindow):
    def __init__(self, db_path: str | None = None) -> None:
        """`db_path=None` picks the correct location for how the app is
        running -- see `pcis.paths.default_database_path`. Tests pass
        ":memory:" explicitly."""
        super().__init__()
        self.setWindowTitle(f"PCIS {version.VERSION} - Poultry Climate Intelligence System")
        self.resize(1120, 820)
        self.setMinimumSize(940, 640)
        # Apply theme to the whole application, not just this window:
        # QMessageBox and QFileDialog are separate top-level windows and
        # would otherwise keep the system palette while the main window
        # used ours.
        app = QApplication.instance()
        if app is not None:
            style.ensure_theme(app)

        self._engine = init_db(db_path or paths.default_database_path())
        self._last_result: rec_engine.Recommendation | None = None
        self._last_inputs: dict | None = None
        self._unit_spins: list[UnitAwareSpinBox] = []
        self._display_system: units.UnitSystem = units.METRIC

        root = QWidget()
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(16, 12, 16, 14)
        outer.setSpacing(10)

        outer.addWidget(self._build_header())

        self.tabs = QTabWidget()
        outer.addWidget(self.tabs, stretch=1)

        self.tabs.addTab(_scrollable(self._build_house_tab()), "House && Equipment")
        self.tabs.addTab(_scrollable(self._build_flock_tab()), "Flock")
        self.tabs.addTab(_scrollable(self._build_environment_tab()), "Environment")
        # Every tab is scrollable. Without it, Qt squeezes widgets below
        # their stated minimum heights when the content is taller than
        # the window -- which is how the Schedule tab's Add/Remove
        # buttons ended up drawn on top of its table. Scrolling costs
        # nothing when the content fits.
        self.tabs.addTab(_scrollable(self._build_recommendation_tab()), "Recommendation")
        self.tabs.addTab(_scrollable(self._build_schedule_tab()), "Schedule")
        self.tabs.addTab(self._build_history_tab(), "History")
        self.tabs.currentChanged.connect(self._on_tab_changed)

        # Connected only now that every widget the handler touches
        # exists -- see the note in _build_header.
        self.unit_combo.currentIndexChanged.connect(self._on_units_changed)

        self._apply_group_box_margins()
        self._cap_input_widths()
        self._apply_tooltips()
        self._restore_settings()

    def _restore_settings(self) -> None:
        """Apply saved preferences. Never fatal: a bad settings file
        must not stop the application starting."""
        try:
            saved = config.load_settings()
        except Exception:
            LOG.exception("Could not load settings; using defaults")
            return
        if saved.get("unit_system") == "imperial":
            for i in range(self.unit_combo.count()):
                if self.unit_combo.itemData(i) is units.IMPERIAL:
                    self.unit_combo.setCurrentIndex(i)
                    break
        name = saved.get("default_house_name")
        if name:
            self.house_name_edit.setText(name)

    def _persist_settings(self) -> None:
        try:
            saved = config.load_settings()
            saved["unit_system"] = (
                "imperial" if self.unit_combo.currentData() is units.IMPERIAL else "metric"
            )
            saved["default_house_name"] = self.house_name_edit.text().strip() or "House 1"
            config.save_settings(saved)
        except Exception:
            LOG.exception("Could not save settings")

    def closeEvent(self, event) -> None:
        self._persist_settings()
        super().closeEvent(event)

    def show_about(self) -> None:
        info = version.full_version_info()
        svc = update_service.get_update_service()
        QMessageBox.about(
            self,
            "About PCIS",
            f"<h3>PCIS {info['version']}</h3>"
            "<p>Poultry Climate Intelligence System<br>"
            "Engineering decision support for environmentally controlled "
            "broiler houses.</p>"
            f"<p><b>Build date:</b> {info['build_date']}<br>"
            f"<b>Commit:</b> {info['git_commit']}<br>"
            f"<b>Update channel:</b> {type(svc).__name__}</p>"
            f"<p><b>Data folder:</b><br>{paths.user_data_dir()}<br>"
            f"<b>Log file:</b><br>{logging_setup.log_file_path()}</p>"
            "<p style='color:#666'>Every engineering figure in this application "
            "traces to a cited published source. Values that could not be "
            "verified are flagged rather than estimated. The underlying model "
            "has not yet been validated against measurements from a real "
            "house.</p>",
        )

    def _apply_tooltips(self) -> None:
        """Attach a tooltip to every input.

        Two reasons beyond politeness: screen readers announce the
        tooltip when a field has no other accessible description, and
        several of these fields have non-obvious engineering meaning
        (allowed temperature rise is a DIFFERENCE, static pressure is
        the design point the fan curve is evaluated at). A label alone
        does not convey either.

        Set in one place so a new field cannot silently ship without
        one -- there is a test asserting every input has a tooltip.
        """
        tips = {
            self.house_name_edit: "Identifies this house in saved records and exports. "
                                  "Reusing a name adds to that house's history.",
            self.length_spin: "Internal floor length of the house.",
            self.width_spin: "Internal floor width of the house.",
            self.height_spin: "Eave height. Used for house volume and air-change rate.",
            self.fan_combo: "Tunnel fan model. Its published airflow-vs-static-pressure "
                            "curve determines how many fans are needed.",
            self.static_pressure_spin: "The static pressure the fan curve is evaluated at. "
                                       "Must reflect your actual house; PCIS will not assume "
                                       "a typical value.",
            self.pad_combo: "Evaporative cooling pad, if installed. With none selected, "
                            "pads are never recommended.",
            self.breed_edit: "Recorded for reference only — the underlying model is not "
                             "breed-specific, so changing this does not change any result.",
            self.age_spin: "Bird age in days. Drives body weight from the Aviagen Ross 308 "
                           "growth curve, and through it the target temperature.",
            self.bird_count_spin: "Number of birds in the house. Scales total heat, "
                                  "moisture and CO₂ load.",
            self.body_weight_spin: "Live body weight per bird. Auto-filled from bird age; "
                                   "type over it if your flock differs from the table.",
            self.indoor_t_spin: "Current or target indoor temperature.",
            self.indoor_rh_spin: "Indoor relative humidity. Above 70% the Aviagen target-"
                                 "temperature table is clamped and flagged.",
            self.outdoor_t_spin: "Current outdoor (ambient) temperature.",
            self.outdoor_rh_spin: "Current outdoor relative humidity.",
            self.delta_t_spin: "How much warmer the air may get crossing the house. This is "
                               "a temperature DIFFERENCE: 1 °C = 1.8 °F, with no 32° offset.",
            self.outdoor_co2_spin: "Ambient outdoor CO₂. Leaving the 420 ppm default costs "
                                   "10 confidence points.",
            self.schedule_age_spin: "Bird age for the simulated day. Day 0 cannot be "
                                    "simulated — see the age note in the docs.",
            self.installed_fans_spin: "How many fans you physically have. Used only to flag "
                                      "a shortfall; the requirement is never capped to it.",
            self.step_hours_spin: "How much time each row of the profile represents. Used to "
                                  "convert step counts into hours.",
        }
        for widget, tip in tips.items():
            widget.setToolTip(tip)
            if not widget.accessibleName():
                widget.setAccessibleName(tip.split(".")[0])

    def _apply_group_box_margins(self) -> None:
        """Reserve room for the QGroupBox title inside every card.

        Qt lays a QGroupBox's child widgets out using the layout's
        contents margins, which know nothing about the stylesheet's
        `padding`/`margin-top`. Without this, the first row of every
        card renders underneath its own title -- which is exactly what
        happened to the Schedule tab's Add/Remove buttons. Done once
        here rather than repeated at every construction site so a new
        card cannot forget it.
        """
        for group in self.findChildren(QGroupBox):
            layout = group.layout()
            if layout is not None:
                m = layout.contentsMargins()
                layout.setContentsMargins(14, max(m.top(), 26), 14, 14)

    def _cap_input_widths(self) -> None:
        """Stop single values stretching across the whole window.

        A 950px-wide box holding "3.00 m" reads as though it wants a
        sentence. Capping the width makes the number the focus and
        keeps the label/value pairing tight enough to scan down a
        column.
        """
        for spin in self.findChildren(QDoubleSpinBox):
            spin.setMaximumWidth(220)
        for spin in self.findChildren(QSpinBox):
            spin.setMaximumWidth(220)
        for combo in self.findChildren(QComboBox):
            if combo is not self.unit_combo:
                combo.setMaximumWidth(420)
        self.house_name_edit.setMaximumWidth(420)
        self.breed_edit.setMaximumWidth(420)

    # ------------------------------------------------------------------
    # Header
    # ------------------------------------------------------------------

    def _build_header(self) -> QWidget:
        bar = QWidget()
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(2, 0, 2, 0)

        title = QLabel("Poultry Climate Intelligence System")
        title.setProperty("sectionHeader", True)
        f = QFont()
        f.setPointSize(15)
        f.setWeight(QFont.Bold)
        title.setFont(f)
        layout.addWidget(title)

        subtitle = _hint("Environmentally-controlled broiler house  ·  every figure traceable to a cited source")
        subtitle.setStyleSheet("font-size: 9.5pt; color: %s;" % style.active()["INK_MUTED"])
        layout.addWidget(subtitle)
        layout.addStretch(1)

        units_label = QLabel("Units")
        # Explicit size: header widgets sit outside the tab tree and were
        # falling back to Qt's 9pt platform default rather than picking up
        # the stylesheet's 10.5pt base, leaving this label visibly smaller
        # than every other field label in the window.
        units_label.setStyleSheet("font-size: 10.5pt;")
        layout.addWidget(units_label)
        self.unit_combo = QComboBox()
        for system in units.UNIT_SYSTEMS:
            self.unit_combo.addItem(system.name, system)
        self.unit_combo.setMinimumWidth(150)
        self.unit_combo.setToolTip(
            "Display units only. Values are stored and computed in SI regardless of "
            "this setting, so switching it never changes a result."
        )
        self.unit_combo.setAccessibleName("Display unit system")
        # NOTE: currentIndexChanged is connected in __init__ AFTER the
        # tabs exist. Connecting here would fire during addItem() (the
        # index moves -1 -> 0) and reach for widgets not built yet.
        layout.addWidget(self.unit_combo)

        about_btn = QPushButton("About")
        about_btn.setToolTip("Version, build details, and where PCIS stores your data.")
        about_btn.setMaximumWidth(90)
        about_btn.clicked.connect(self.show_about)
        layout.addWidget(about_btn)
        return bar

    def _on_units_changed(self) -> None:
        """Re-display every value in the newly selected system.

        Only presentation changes here -- `UnitAwareSpinBox` keeps its
        SI value across the switch, so no recomputation is needed and
        no precision is lost by round-tripping.
        """
        # Read the schedule profile in SI using the OUTGOING system
        # before anything switches. Reading it afterwards would
        # reinterpret the on-screen "24" as 24 degF instead of
        # converting the 24 degC it actually represents.
        try:
            profile_si = self.read_profile()
        except ValueError:
            profile_si = None

        system: units.UnitSystem = self.unit_combo.currentData()
        self._display_system = system

        for spin in self._unit_spins:
            spin.set_unit_system(system)
        self.envelope_editor.set_unit_system(system)

        if profile_si is not None:
            self.profile_table.setRowCount(0)
            self._refresh_profile_headers()
            for cond in profile_si:
                self._add_profile_row(cond.label, cond.t_c, cond.rh_pct)
        self._refresh_fan_chart()
        # Re-render the last result so its units follow the selector too.
        if self._last_result is not None and self._last_inputs is not None:
            self._render_result(self._last_result, self._last_inputs)

    @property
    def _system(self) -> units.UnitSystem:
        """The system the on-screen values are currently rendered in.

        Tracked separately from `unit_combo.currentData()` because
        during a switch the combo already reports the NEW system while
        the tables still hold values rendered in the OLD one -- reading
        them with the new system would silently reinterpret every
        number instead of converting it.
        """
        return self._display_system

    # ------------------------------------------------------------------
    # Widget helpers
    # ------------------------------------------------------------------

    def _unit_spin(
        self, quantity: str, si_min: float, si_max: float, si_value: float, decimals: int = 2
    ) -> UnitAwareSpinBox:
        spin = UnitAwareSpinBox(quantity, si_min, si_max, si_value, decimals)
        self._unit_spins.append(spin)
        return spin

    @staticmethod
    def _make_spin(minimum: float, maximum: float, value: float, suffix: str) -> QDoubleSpinBox:
        """Plain (unitless) spinbox -- for percentages, ppm, and other
        quantities that are the same in every unit system.
        """
        spin = QDoubleSpinBox()
        spin.setRange(minimum, maximum)
        spin.setValue(value)
        spin.setSuffix(suffix)
        spin.setDecimals(2)
        return spin

    # ------------------------------------------------------------------
    # Tab builders
    # ------------------------------------------------------------------

    def _build_house_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setSpacing(12)

        house_group = QGroupBox("House dimensions")
        form = QFormLayout(house_group)
        form.setSpacing(9)
        form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.house_name_edit = QLineEdit("House 1")
        self.length_spin = self._unit_spin("length", 0.1, 500.0, 150.0)
        self.width_spin = self._unit_spin("length", 0.1, 100.0, 15.0)
        self.height_spin = self._unit_spin("length", 0.1, 20.0, 3.0)
        form.addRow("House name", self.house_name_edit)
        form.addRow("Length", self.length_spin)
        form.addRow("Width", self.width_spin)
        form.addRow("Height (eave)", self.height_spin)
        layout.addWidget(house_group)

        envelope_group = QGroupBox("Envelope surfaces")
        env_layout = QVBoxLayout(envelope_group)
        env_layout.addWidget(
            _hint(
                "Used for conduction heat loss/gain (Q = U·A·ΔT). U-values are caller-supplied: "
                "PCIS has no verified materials table and will not guess one for you."
            )
        )
        self.envelope_editor = EnvelopeSurfaceEditor()
        env_layout.addWidget(self.envelope_editor)
        layout.addWidget(envelope_group)

        equipment_group = QGroupBox("Equipment")
        eq_form = QFormLayout(equipment_group)
        eq_form.setSpacing(9)
        eq_form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.fan_combo = QComboBox()
        for fan in FAN_CATALOG:
            self.fan_combo.addItem(f"{fan.manufacturer} {fan.model}", fan)
        self.static_pressure_spin = self._unit_spin("pressure", 0.0, 200.0, 30.0, decimals=3)
        self.pad_combo = QComboBox()
        self.pad_combo.addItem("(no cooling pad installed)", None)
        for pad in COOLING_PAD_CATALOG:
            self.pad_combo.addItem(f"{pad.manufacturer} {pad.model}", pad)
        eq_form.addRow("Fan model", self.fan_combo)
        eq_form.addRow("Design static pressure", self.static_pressure_spin)
        eq_form.addRow("Cooling pad", self.pad_combo)
        layout.addWidget(equipment_group)

        chart_group = QGroupBox("Fan performance curve")
        chart_layout = QVBoxLayout(chart_group)
        self.fan_chart = FanCurveChartWidget()
        self.fan_chart.setMinimumHeight(260)
        chart_layout.addWidget(self.fan_chart)
        layout.addWidget(chart_group, stretch=1)

        self.fan_combo.currentIndexChanged.connect(self._refresh_fan_chart)
        self.static_pressure_spin.valueChanged.connect(self._refresh_fan_chart)
        self._refresh_fan_chart()

        return widget

    def _refresh_fan_chart(self) -> None:
        fan: FanCurve | None = self.fan_combo.currentData()
        if fan is not None:
            self.fan_chart.set_fan(fan, operating_static_pressure_pa=self.static_pressure_spin.si_value())

    def _build_flock_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setSpacing(12)

        group = QGroupBox("Flock")
        form = QFormLayout(group)
        form.setSpacing(9)
        form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)

        self.breed_edit = QLineEdit("Ross 308")
        self.bird_count_spin = QSpinBox()
        self.bird_count_spin.setRange(1, 500_000)
        self.bird_count_spin.setValue(20000)
        self.bird_count_spin.setGroupSeparatorShown(True)

        self.age_spin = QSpinBox()
        self.age_spin.setRange(0, 100)
        self.age_spin.setValue(35)
        self.age_spin.setSuffix(" days")
        self.age_spin.valueChanged.connect(self._on_age_changed)

        self.body_weight_spin = self._unit_spin("mass", 0.01, 10.0, 2.5)

        form.addRow("Breed", self.breed_edit)
        form.addRow("Bird age", self.age_spin)
        form.addRow("Bird count", self.bird_count_spin)
        form.addRow("Body weight", self.body_weight_spin)

        self.growth_curve_status_label = _hint("")
        form.addRow("", self.growth_curve_status_label)
        layout.addWidget(group)
        self._on_age_changed(self.age_spin.value())

        note_group = QGroupBox("What these fields do")
        note_layout = QVBoxLayout(note_group)
        note_layout.addWidget(
            _hint(
                "Breed is recorded for reference only — the underlying model (CIGR broiler "
                "formula, Aviagen tables) is not currently breed-specific, so changing it does "
                "not change any calculation.\n\n"
                "Body weight auto-fills from the published Aviagen Ross 308 as-hatched growth "
                "curve (days 0–56) whenever you change the age. You can type over it if your "
                "flock differs from the table; ages outside 0–56 leave the field alone rather "
                "than extrapolating a guess."
            )
        )
        layout.addWidget(note_group)
        layout.addStretch(1)
        return widget

    def _on_age_changed(self, age_days: int) -> None:
        """Auto-fill body weight from the real Ross 308 growth curve
        (`pcis.core.growth_curve`) whenever the age spinner changes.
        The weight field stays a normal editable spinbox afterward --
        this only sets a starting point, it never locks the value.
        """
        try:
            weight_kg = gc.ross_308_body_weight_kg(float(age_days))
        except ValueError:
            self.growth_curve_status_label.setText(
                f"Age {age_days} days is outside the published Aviagen Ross 308 "
                f"table ({gc.ROSS_308_MIN_AGE_DAYS}-{gc.ROSS_308_MAX_AGE_DAYS} days) "
                "-- enter body weight manually."
            )
            return
        self.body_weight_spin.set_si_value(weight_kg)
        shown = self._system.mass_from_si(weight_kg)
        self.growth_curve_status_label.setText(
            f"Body weight auto-filled to {shown:.3f}{self._system.mass_suffix} from the "
            f"Aviagen Ross 308 as-hatched growth curve at day {age_days} "
            "(edit the field above to override)."
        )

    def _build_environment_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setSpacing(12)

        indoor = QGroupBox("Indoor (target conditions)")
        indoor_form = QFormLayout(indoor)
        indoor_form.setSpacing(9)
        indoor_form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.indoor_t_spin = self._unit_spin("temp", -20.0, 50.0, 29.0)
        self.indoor_rh_spin = self._make_spin(0.0, 100.0, 60.0, " %")
        indoor_form.addRow("Temperature", self.indoor_t_spin)
        indoor_form.addRow("Relative humidity", self.indoor_rh_spin)
        layout.addWidget(indoor)

        outdoor = QGroupBox("Outdoor (ambient)")
        outdoor_form = QFormLayout(outdoor)
        outdoor_form.setSpacing(9)
        outdoor_form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.outdoor_t_spin = self._unit_spin("temp", -40.0, 55.0, 35.0)
        self.outdoor_rh_spin = self._make_spin(0.0, 100.0, 40.0, " %")
        outdoor_form.addRow("Temperature", self.outdoor_t_spin)
        outdoor_form.addRow("Relative humidity", self.outdoor_rh_spin)
        layout.addWidget(outdoor)

        design = QGroupBox("Design parameters")
        design_form = QFormLayout(design)
        design_form.setSpacing(9)
        design_form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.delta_t_spin = self._unit_spin("delta_temp", 0.1, 20.0, 3.0)
        self.outdoor_co2_spin = self._make_spin(300.0, 2000.0, 420.0, " ppm")
        design_form.addRow("Allowed temperature rise", self.delta_t_spin)
        design_form.addRow("Outdoor CO₂ background", self.outdoor_co2_spin)
        design_form.addRow(
            "",
            _hint(
                "Allowed temperature rise is how much warmer the air may get crossing the house. "
                "It is a temperature DIFFERENCE, so in imperial it converts as 1 °C = 1.8 °F "
                "(no 32° offset).\n"
                "Leaving CO₂ at the 420 ppm default costs 10 confidence points — enter a locally "
                "measured value if you have one."
            ),
        )
        layout.addWidget(design)
        layout.addStretch(1)
        return widget


    @staticmethod
    def _banner_style(danger: bool) -> str:
        """Stylesheet for an inline status banner, in the active theme.

        Centralised because the same rule was inlined at three call
        sites and had to be updated in lockstep whenever the palette
        changed -- which is how one of them ended up unreadable.
        """
        pal = style.active()
        if danger:
            bg, fg, border = pal["DANGER_SOFT"], pal["DANGER_TEXT"], pal["DANGER"]
        else:
            bg, fg, border = pal["RAISED"], pal["OK"], pal["OK"]
        return (f"background: {bg}; color: {fg}; border: 1px solid {border};"
                " border-radius: 6px; padding: 10px 12px;")

    def _build_recommendation_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(11)

        run_btn = QPushButton("Run Recommendation")
        run_btn.setProperty("primary", True)
        run_btn.clicked.connect(self.run_recommendation)
        layout.addWidget(run_btn)

        # --- Headline metrics -------------------------------------------
        self.metrics_group = QGroupBox("Result")
        metrics_layout = QVBoxLayout(self.metrics_group)
        self.metrics_panel = MetricsPanel([
            ("fans", "Fans ON"),
            ("pads", "Cooling pads"),
            ("airflow", "Required airflow"),
            ("governing", "Governing constraint"),
            ("confidence", "Confidence"),
        ])
        metrics_layout.addWidget(self.metrics_panel)
        # Kept as an alias so existing callers/tests that reach for
        # individual value labels keep working after the reflow rewrite.
        self._metric_labels = self.metrics_panel.value_labels
        layout.addWidget(self.metrics_group)

        # --- Loud warning banner ----------------------------------------
        self.warning_label = QLabel()
        self.warning_label.setWordWrap(True)
        self.warning_label.setStyleSheet(self._banner_style(danger=True))
        self.warning_label.setVisible(False)
        layout.addWidget(self.warning_label)

        # Empty state: an axis-less chart frame with only a title in it
        # reads as "broken", and it consumed ~190px above the fold before
        # the user had run anything. Show a short instruction instead and
        # swap in the chart once there is data to plot.
        self.comfort_chart = ComfortChartWidget()
        self.comfort_chart.setMinimumHeight(190)
        self.comfort_chart.setMaximumHeight(260)
        self.comfort_chart.setVisible(False)
        layout.addWidget(self.comfort_chart, stretch=0)

        self.empty_state_label = _hint(
            "Press “Run Recommendation” to calculate fan staging and cooling-pad state "
            "for the conditions entered on the other tabs."
        )
        self.empty_state_label.setAlignment(Qt.AlignCenter)
        self.empty_state_label.setMinimumHeight(48)
        layout.addWidget(self.empty_state_label)

        expl_group = QGroupBox("Engineering explanation")
        expl_layout = QVBoxLayout(expl_group)
        # The explanation strings are produced inside the engineering
        # core, which works in SI. They are shown VERBATIM rather than
        # unit-converted, because converting them would mean either
        # regex-rewriting numbers out of prose (fragile, and a wrong
        # match silently corrupts an engineering statement) or teaching
        # the core about display units (which is exactly the coupling
        # this project keeps out of the solver). Labelled instead of
        # quietly left inconsistent.
        self.explanation_units_hint = _hint(
            "Reported in SI (°C, kW, m³/h) — these lines come verbatim from the "
            "engineering core, which computes in SI regardless of the display units above."
        )
        expl_layout.addWidget(self.explanation_units_hint)
        self.explanation_list = ExplanationView()
        self.explanation_list.setMinimumHeight(240)
        expl_layout.addWidget(self.explanation_list)
        layout.addWidget(expl_group, stretch=3)

        self.test_run_checkbox = QCheckBox("Log this as a test run (kept out of the real dataset)")
        self.test_run_checkbox.setToolTip(
            "Tick while you are just exploring or entering made-up numbers. The run is "
            "still saved and visible in the History tab, but is excluded from the "
            "training-data export so it cannot pollute the real dataset. You can change "
            "this later in History."
        )
        layout.addWidget(self.test_run_checkbox)

        self.record_status_label = _hint(
            "Every recommendation you run is logged automatically (age, conditions, "
            "fan/pad decision, comfort score) — nothing to click to save it. Review, "
            "tag or delete logged runs in the History tab."
        )
        layout.addWidget(self.record_status_label)

        buttons = QHBoxLayout()
        self.export_pdf_btn = QPushButton("Export PDF Report…")
        self.export_pdf_btn.clicked.connect(self.export_pdf)
        self.export_pdf_btn.setEnabled(False)
        self.export_training_data_btn = QPushButton("Export Training Data (CSV)…")
        self.export_training_data_btn.clicked.connect(self.export_training_data)
        self.export_training_data_btn.setToolTip(
            "Exports every recommendation logged so far (age, conditions, fan/pad "
            "decision, comfort score) as a CSV — a growing dataset for future "
            "calibration or ML work."
        )
        buttons.addStretch(1)
        buttons.addWidget(self.export_pdf_btn)
        buttons.addWidget(self.export_training_data_btn)
        layout.addLayout(buttons)

        return widget

    # ------------------------------------------------------------------
    # History tab -- review, tag and delete logged runs
    # ------------------------------------------------------------------

    HISTORY_COLUMNS = ["ID", "When", "House", "Age", "Indoor", "Outdoor",
                       "Fans", "Pads", "Conf.", "Test?", "Note"]

    def _build_history_tab(self) -> QWidget:
        """Every logged run, with the ability to tag or delete rows.

        This is the curation half of the data logging. Capture without
        curation fills the exported dataset with exploratory clicks and
        mistyped inputs; this tab is where garbage gets found and removed
        and where a genuine reading can be separated from a test.
        """
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        self.history_summary = QLabel()
        f = QFont()
        f.setPointSize(12)
        f.setWeight(QFont.Bold)
        self.history_summary.setFont(f)
        layout.addWidget(self.history_summary)

        layout.addWidget(_hint(
            "Every recommendation you run is logged here. Select rows to mark them as "
            "tests (excluded from the training export) or delete them. Deleting is "
            "permanent; marking as a test is reversible."
        ))

        self.history_table = QTableWidget(0, len(self.HISTORY_COLUMNS))
        self.history_table.setHorizontalHeaderLabels(self.HISTORY_COLUMNS)
        self.history_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.history_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.history_table.verticalHeader().setVisible(False)
        self.history_table.setAlternatingRowColors(True)
        self.history_table.setMinimumHeight(340)
        hh = self.history_table.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.Interactive)
        hh.setStretchLastSection(True)
        layout.addWidget(self.history_table, stretch=1)

        buttons = QHBoxLayout()
        refresh_btn = QPushButton("Refresh")
        refresh_btn.clicked.connect(self._refresh_history)
        mark_test_btn = QPushButton("Mark as test")
        mark_test_btn.setToolTip("Exclude the selected rows from the training-data export.")
        mark_test_btn.clicked.connect(lambda: self._flag_selected_history(True))
        mark_real_btn = QPushButton("Mark as real")
        mark_real_btn.setToolTip("Include the selected rows in the training-data export again.")
        mark_real_btn.clicked.connect(lambda: self._flag_selected_history(False))
        delete_btn = QPushButton("Delete selected…")
        delete_btn.setToolTip("Permanently remove the selected rows. This cannot be undone.")
        delete_btn.clicked.connect(self._delete_selected_history)
        export_real_btn = QPushButton("Export real data (CSV)…")
        export_real_btn.setToolTip("Export only rows NOT marked as tests.")
        export_real_btn.clicked.connect(lambda: self.export_training_data(exclude_test=True))

        buttons.addWidget(refresh_btn)
        buttons.addWidget(mark_test_btn)
        buttons.addWidget(mark_real_btn)
        buttons.addWidget(delete_btn)
        buttons.addStretch(1)
        buttons.addWidget(export_real_btn)
        layout.addLayout(buttons)
        return widget

    def _on_tab_changed(self, index: int) -> None:
        if self.tabs.tabText(index) == "History":
            self._refresh_history()

    def _refresh_history(self) -> None:
        s = self._system
        with Session(self._engine) as session:
            logs = all_recommendation_logs(session, limit=1000)
            real, tests = count_recommendation_logs(session)
            rows = []
            for log in logs:
                rows.append((
                    log.id,
                    log.timestamp.strftime("%Y-%m-%d %H:%M"),
                    log.house.name,
                    "" if log.age_days is None else str(log.age_days),
                    f"{s.temp_from_si(log.indoor_t_c):.0f}{s.temp_suffix}/{log.indoor_rh_pct:.0f}%",
                    f"{s.temp_from_si(log.outdoor_t_c):.0f}{s.temp_suffix}/{log.outdoor_rh_pct:.0f}%",
                    str(log.fans_on),
                    "ON" if log.pads_on else "off",
                    f"{log.confidence_score:.0f}",
                    "TEST" if log.is_test else "",
                    log.note or "",
                ))

        self.history_summary.setText(f"{real} real run(s), {tests} test run(s) logged")
        self.history_table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            for c, value in enumerate(row):
                item = QTableWidgetItem(str(value))
                if c == 0:
                    item.setData(Qt.UserRole, row[0])
                self.history_table.setItem(r, c, item)
        self.history_table.resizeColumnsToContents()

    def _selected_history_ids(self) -> list[int]:
        ids = []
        for idx in {i.row() for i in self.history_table.selectedIndexes()}:
            item = self.history_table.item(idx, 0)
            if item is not None:
                ids.append(int(item.text()))
        return ids

    def _flag_selected_history(self, is_test: bool) -> None:
        ids = self._selected_history_ids()
        if not ids:
            QMessageBox.information(self, "No rows selected", "Select one or more rows first.")
            return
        with Session(self._engine) as session:
            set_recommendation_test_flag(session, ids, is_test)
            session.commit()
        self._refresh_history()

    def _delete_selected_history(self) -> None:
        ids = self._selected_history_ids()
        if not ids:
            QMessageBox.information(self, "No rows selected", "Select one or more rows first.")
            return
        confirm = QMessageBox.question(
            self, "Delete runs?",
            f"Permanently delete {len(ids)} logged run(s)?\n\n"
            "This cannot be undone. If you only want to keep them out of the "
            "training export, use Mark as test instead.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return
        with Session(self._engine) as session:
            delete_recommendation_logs(session, ids)
            session.commit()
        self._refresh_history()

    def _build_schedule_tab(self) -> QWidget:
        """The digital twin: 'how many fans, at what time, for how long'."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(11)

        top = QHBoxLayout()

        profile_group = QGroupBox("Outdoor conditions through the day")
        profile_layout = QVBoxLayout(profile_group)
        profile_layout.addWidget(
            _hint(
                "PCIS deliberately ships no built-in weather curve — a defensible one is "
                "site- and season-specific. Enter your own readings, or edit the starting "
                "rows below."
            )
        )
        self.profile_table = QTableWidget(0, 3)
        self.profile_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.profile_table.verticalHeader().setVisible(False)
        pheader = self.profile_table.horizontalHeader()
        pheader.setSectionResizeMode(QHeaderView.Interactive)
        pheader.setStretchLastSection(True)
        pheader.setMinimumSectionSize(90)
        self.profile_table.setAlternatingRowColors(True)
        self.profile_table.setMinimumHeight(260)
        profile_layout.addWidget(self.profile_table, stretch=1)

        prof_btns = QHBoxLayout()
        add_row_btn = QPushButton("Add time")
        add_row_btn.clicked.connect(lambda: self._add_profile_row("12:00", 30.0, 50.0))
        del_row_btn = QPushButton("Remove selected")
        del_row_btn.clicked.connect(self._remove_profile_rows)
        prof_btns.addWidget(add_row_btn)
        prof_btns.addWidget(del_row_btn)
        prof_btns.addStretch(1)
        profile_layout.addLayout(prof_btns)
        profile_group.setMinimumHeight(360)
        top.addWidget(profile_group, stretch=3)

        settings_group = QGroupBox("Simulation settings")
        settings_form = QFormLayout(settings_group)
        settings_form.setSpacing(9)
        settings_form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.schedule_age_spin = QSpinBox()
        self.schedule_age_spin.setRange(0, 100)
        self.schedule_age_spin.setValue(35)
        self.schedule_age_spin.setSuffix(" days")
        self.installed_fans_spin = QSpinBox()
        self.installed_fans_spin.setRange(0, 200)
        self.installed_fans_spin.setValue(8)
        self.installed_fans_spin.setSpecialValueText("(not specified)")
        self.step_hours_spin = QDoubleSpinBox()
        self.step_hours_spin.setRange(0.25, 24.0)
        self.step_hours_spin.setValue(3.0)
        self.step_hours_spin.setSuffix(" h")
        self.step_hours_spin.setDecimals(2)
        settings_form.addRow("Bird age", self.schedule_age_spin)
        settings_form.addRow("Fans installed", self.installed_fans_spin)
        settings_form.addRow("Time per row", self.step_hours_spin)
        settings_hint = _hint(
            "Fans installed only flags when the requirement exceeds what you actually "
            "have — the required count is never capped to it, since capping would hide "
            "the shortfall."
        )
        settings_hint.setMinimumHeight(72)
        settings_form.addRow(settings_hint)
        settings_group.setMinimumHeight(300)
        settings_group.setAlignment(Qt.AlignTop)
        top.addWidget(settings_group, stretch=2)
        layout.addLayout(top)

        run_schedule_btn = QPushButton("Build Schedule")
        run_schedule_btn.setProperty("primary", True)
        run_schedule_btn.clicked.connect(self.run_schedule)
        layout.addWidget(run_schedule_btn)

        self.schedule_chart = ScheduleChartWidget()
        self.schedule_chart.setMinimumHeight(300)
        self.schedule_chart.setVisible(False)
        layout.addWidget(self.schedule_chart, stretch=1)

        self.schedule_empty_label = _hint(
            "Press “Build Schedule” to simulate the day and see how many fans "
            "should run at each time."
        )
        self.schedule_empty_label.setAlignment(Qt.AlignCenter)
        self.schedule_empty_label.setMinimumHeight(48)
        layout.addWidget(self.schedule_empty_label)

        blocks_group = QGroupBox("Consolidated schedule")
        blocks_layout = QVBoxLayout(blocks_group)
        self.schedule_blocks_list = QListWidget()
        self.schedule_blocks_list.setWordWrap(True)
        self.schedule_blocks_list.setMinimumHeight(150)
        blocks_layout.addWidget(self.schedule_blocks_list)
        layout.addWidget(blocks_group, stretch=1)

        self.schedule_notes_label = QLabel()
        self.schedule_notes_label.setWordWrap(True)
        self.schedule_notes_label.setVisible(False)
        layout.addWidget(self.schedule_notes_label)

        for label, t_c, rh in [
            ("00:00", 24.0, 80.0), ("03:00", 22.0, 85.0), ("06:00", 21.0, 85.0),
            ("09:00", 28.0, 60.0), ("12:00", 34.0, 45.0), ("15:00", 37.0, 38.0),
            ("18:00", 34.0, 45.0), ("21:00", 28.0, 65.0),
        ]:
            self._add_profile_row(label, t_c, rh)
        self._refresh_profile_headers()
        self.profile_table.resizeColumnsToContents()
        for col in range(self.profile_table.columnCount() - 1):
            self.profile_table.setColumnWidth(
                col, max(self.profile_table.columnWidth(col) + 24, 130))
        return widget

    def _refresh_profile_headers(self) -> None:
        s = self._system
        self.profile_table.setHorizontalHeaderLabels(
            ["Time", f"Outdoor temp ({s.temp_suffix.strip()})", "Outdoor RH (%)"]
        )

    def _add_profile_row(self, label: str, t_c: float, rh_pct: float) -> None:
        """Add a profile row. `t_c` is SI (Celsius); displayed converted."""
        row = self.profile_table.rowCount()
        self.profile_table.insertRow(row)
        self.profile_table.setItem(row, 0, QTableWidgetItem(label))
        self.profile_table.setItem(row, 1, _si_cell(self._system.temp_from_si(t_c), t_c))
        self.profile_table.setItem(row, 2, QTableWidgetItem(f"{rh_pct:g}"))

    def _remove_profile_rows(self) -> None:
        for index in sorted({i.row() for i in self.profile_table.selectedIndexes()}, reverse=True):
            self.profile_table.removeRow(index)

    def read_profile(self) -> list[twin.OutdoorCondition]:
        """Read the schedule tab's table into domain objects, in SI."""
        conditions = []
        for row in range(self.profile_table.rowCount()):
            label_item = self.profile_table.item(row, 0)
            t_item = self.profile_table.item(row, 1)
            rh_item = self.profile_table.item(row, 2)
            label = label_item.text() if label_item else f"step {row + 1}"
            try:
                t_c = _cell_si_value(t_item, self._system.temp_to_si)
                rh = float(rh_item.text()) if rh_item else 0.0
            except ValueError as exc:
                raise ValueError(
                    f"Row {row + 1} ({label}): temperature and humidity must be numbers"
                ) from exc
            conditions.append(twin.OutdoorCondition(label=label, t_c=t_c, rh_pct=rh))
        return conditions

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def gather_inputs(self) -> dict:
        """Read every widget into a plain dict, in SI. Split out from
        `run_recommendation` so it can be exercised directly in tests
        without needing to simulate button clicks.
        """
        fan: FanCurve = self.fan_combo.currentData()
        pad: CoolingPad | None = self.pad_combo.currentData()
        return dict(
            house_name=self.house_name_edit.text().strip() or "House 1",
            length_m=self.length_spin.si_value(),
            width_m=self.width_spin.si_value(),
            height_m=self.height_spin.si_value(),
            surfaces=self.envelope_editor.surfaces(),
            breed=self.breed_edit.text().strip() or "unspecified",
            age_days=self.age_spin.value(),
            bird_count=self.bird_count_spin.value(),
            body_weight_kg=self.body_weight_spin.si_value(),
            indoor_t_c=self.indoor_t_spin.si_value(),
            indoor_rh_pct=self.indoor_rh_spin.value(),
            outdoor_t_c=self.outdoor_t_spin.si_value(),
            outdoor_rh_pct=self.outdoor_rh_spin.value(),
            delta_t_c=self.delta_t_spin.si_value(),
            outdoor_co2_ppm=self.outdoor_co2_spin.value(),
            fan=fan,
            design_static_pressure_pa=self.static_pressure_spin.si_value(),
            cooling_pad=pad,
        )

    def run_recommendation(self) -> rec_engine.Recommendation | None:
        try:
            inputs = self.gather_inputs()
        except ValueError as exc:
            QMessageBox.warning(self, "Invalid input", str(exc))
            return None

        try:
            result = rec_engine.recommend(
                bird_count=inputs["bird_count"],
                body_weight_kg=inputs["body_weight_kg"],
                indoor_t_c=inputs["indoor_t_c"],
                indoor_rh_pct=inputs["indoor_rh_pct"],
                outdoor_t_c=inputs["outdoor_t_c"],
                outdoor_rh_pct=inputs["outdoor_rh_pct"],
                envelope_surfaces=inputs["surfaces"],
                fan=inputs["fan"],
                design_static_pressure_pa=inputs["design_static_pressure_pa"],
                delta_t_c=inputs["delta_t_c"],
                cooling_pad=inputs["cooling_pad"],
                outdoor_co2_ppm=inputs["outdoor_co2_ppm"],
            )
        except (ValueError, RuntimeError) as exc:
            QMessageBox.warning(self, "Could not compute recommendation", str(exc))
            return None

        self._last_result = result
        self._last_inputs = inputs
        self._render_result(result, inputs)
        self.export_pdf_btn.setEnabled(True)
        self._record_to_database(inputs, result)
        self._scroll_into_view(self.metrics_group)
        return result

    def _render_result(self, result: rec_engine.Recommendation, inputs: dict) -> None:
        """Paint the headline metrics, warning banner, chart and
        explanation. Presentation only -- called again on unit change
        so the displayed units follow the selector without recomputing.
        """
        s = self._system
        pal = style.active()
        airflow = s.airflow_from_si(result.required_airflow_m3_per_h)
        m = self.metrics_panel
        m.set_value("fans", str(result.fans_on))
        m.set_value("pads", "ON" if result.pads_on else "off",
                    pal["OK"] if result.pads_on else pal["INK"])
        m.set_value("airflow", f"{airflow:,.0f}{s.airflow_suffix}")
        m.set_value("governing", result.governing_constraint.replace("_", " "))
        m.set_value("confidence", f"{result.confidence_score:.0f}/100",
                    style.status_color(result.confidence_score / 100.0))

        self.empty_state_label.setVisible(False)
        self.comfort_chart.setVisible(True)

        if result.target_unreachable:
            gap_si = result.supply_air_t_c - result.comfort.target_temp_c
            self.warning_label.setText(
                "⚠  TARGET NOT REACHABLE — "
                f"supply air is {s.temp_from_si(result.supply_air_t_c):.1f}{s.temp_suffix} but the "
                f"target is {s.temp_from_si(result.comfort.target_temp_c):.1f}{s.temp_suffix} "
                f"(a {s.delta_temp_from_si(gap_si):.1f}{s.delta_temp_suffix} gap). "
                "Ventilation cannot cool the house below the air you feed it, so the fan count "
                "above will NOT achieve target — read it as \"run what you have\". More fans will "
                "not close this gap; more evaporative cooling capacity, or accepting a warmer "
                "house, will."
            )
            self.warning_label.setVisible(True)
        else:
            self.warning_label.setVisible(False)

        self.explanation_list.clear()
        self.explanation_list.addItems(result.explanation)
        self.comfort_chart.set_recommendation(
            result, outdoor_t_c=inputs["outdoor_t_c"], unit_system=s
        )

    def _record_to_database(self, inputs: dict, result: rec_engine.Recommendation) -> None:
        """Log this run to the database automatically -- no button, no
        confirmation dialog. Runs immediately after every successful
        `run_recommendation()` call so the saved history (used by
        `export_training_data`) grows just from normal use of the app.

        Uses `get_or_create_house_config` rather than `save_house_config`
        because the same house name is reused across every run --
        `HouseConfig.name` is unique, so a plain create would fail on
        the second call.
        """
        with Session(self._engine) as session:
            house = get_or_create_house_config(
                session,
                name=inputs["house_name"],
                length_m=inputs["length_m"],
                width_m=inputs["width_m"],
                height_m=inputs["height_m"],
                surfaces=inputs["surfaces"],
            )
            save_flock_record(
                session, house,
                breed=inputs["breed"],
                bird_count=inputs["bird_count"],
                body_weight_kg=inputs["body_weight_kg"],
            )
            save_recommendation(
                session, house,
                bird_count=inputs["bird_count"],
                body_weight_kg=inputs["body_weight_kg"],
                indoor_t_c=inputs["indoor_t_c"],
                indoor_rh_pct=inputs["indoor_rh_pct"],
                outdoor_t_c=inputs["outdoor_t_c"],
                outdoor_rh_pct=inputs["outdoor_rh_pct"],
                recommendation=result,
                age_days=inputs["age_days"],
                is_test=self.test_run_checkbox.isChecked(),
            )
            session.commit()
        tag = " (test)" if self.test_run_checkbox.isChecked() else ""
        self.record_status_label.setText(
            f"Logged{tag}: '{inputs['house_name']}', age {inputs['age_days']} days, "
            f"{dt.datetime.now().strftime('%Y-%m-%d %H:%M')}. Review or delete runs in "
            "the History tab."
        )
        if hasattr(self, "history_table"):
            self._refresh_history()

    def run_schedule(self) -> twin.SimulationResult | None:
        """Run the digital twin over the entered outdoor profile."""
        try:
            conditions = self.read_profile()
        except ValueError as exc:
            QMessageBox.warning(self, "Invalid schedule input", str(exc))
            return None
        if not conditions:
            QMessageBox.warning(
                self, "No conditions", "Add at least one row to the outdoor conditions table."
            )
            return None

        try:
            inputs = self.gather_inputs()
        except ValueError as exc:
            QMessageBox.warning(self, "Invalid input", str(exc))
            return None

        installed = self.installed_fans_spin.value()
        try:
            result = twin.simulate_schedule(
                conditions=conditions,
                age_days=float(self.schedule_age_spin.value()),
                bird_count=inputs["bird_count"],
                envelope_surfaces=inputs["surfaces"],
                fan=inputs["fan"],
                design_static_pressure_pa=inputs["design_static_pressure_pa"],
                delta_t_c=inputs["delta_t_c"],
                indoor_rh_pct=inputs["indoor_rh_pct"],
                cooling_pad=inputs["cooling_pad"],
                outdoor_co2_ppm=inputs["outdoor_co2_ppm"],
                installed_fan_count=installed if installed > 0 else None,
            )
        except (ValueError, RuntimeError) as exc:
            QMessageBox.warning(self, "Could not build schedule", str(exc))
            return None

        self._render_schedule(result)
        self._scroll_into_view(self.schedule_notes_label)
        return result

    def _scroll_into_view(self, widget: QWidget) -> None:
        """Scroll the enclosing tab so `widget` is visible.

        Both result areas sit below the fold at the window's minimum
        size, so pressing the action button appeared to do nothing --
        the output rendered off-screen with no indication it had worked.
        """
        parent = widget.parentWidget()
        while parent is not None and not isinstance(parent, QScrollArea):
            parent = parent.parentWidget()
        if isinstance(parent, QScrollArea):
            parent.ensureWidgetVisible(widget, 0, 40)

    def _render_schedule(self, result: twin.SimulationResult) -> None:
        self.schedule_chart.set_schedule(result)
        self.schedule_chart.setVisible(True)
        self.schedule_empty_label.setVisible(False)

        step_h = self.step_hours_spin.value()
        self.schedule_blocks_list.clear()
        for block in result.blocks:
            span = (
                block.start_label
                if block.n_steps == 1
                else f"{block.start_label} – {block.end_label}"
            )
            hours = block.n_steps * step_h
            self.schedule_blocks_list.addItem(
                f"{span}   →   {block.fans_on} fan(s), pads "
                f"{'ON' if block.pads_on else 'off'}   ({hours:g} h)"
            )

        summary = (
            f"Peak requirement: {result.peak_fans_on} fans.  "
            f"Total {result.fan_hours(step_h):,.0f} fan-hours, "
            f"{result.pad_hours(step_h):g} pad-hours."
        )
        warnings = [n for n in result.notes if n.startswith("WARNING")]
        if warnings:
            self.schedule_notes_label.setStyleSheet(self._banner_style(danger=True))
            self.schedule_notes_label.setText(summary + "\n\n" + "\n\n".join(f"⚠  {w}" for w in warnings))
        else:
            self.schedule_notes_label.setStyleSheet(self._banner_style(danger=False))
            self.schedule_notes_label.setText(summary)
        self.schedule_notes_label.setVisible(True)

    def export_training_data(self, path: str | None = None,
                             exclude_test: bool = False) -> str | None:
        """Export saved recommendations as a CSV for calibration/ML work.

        `exclude_test=True` drops rows marked as tests in the History
        tab, so the file is only genuine data. The default keeps every
        row with the `is_test` flag as a column, so the raw dump is
        complete and the caller can filter it themselves.
        """
        if path is None:
            default = "pcis_real_data.csv" if exclude_test else "pcis_training_data.csv"
            path, _ = QFileDialog.getSaveFileName(
                self, "Export Training Data (CSV)",
                str(paths.default_export_dir() / default),
                "CSV files (*.csv)"
            )
            if not path:
                return None
        with Session(self._engine) as session:
            export_recommendation_logs_csv(session, output_path=path, exclude_test=exclude_test)
        scope = "Real data (test runs excluded)" if exclude_test else "Training data"
        QMessageBox.information(self, "Exported", f"{scope} written to {path}")
        return path

    def export_pdf(self, path: str | None = None) -> str | None:
        if self._last_result is None or self._last_inputs is None:
            return None
        inputs = self._last_inputs
        if path is None:
            path, _ = QFileDialog.getSaveFileName(
                self, "Export PDF Report",
                str(paths.default_export_dir() / f"{inputs['house_name']}.pdf"),
                "PDF files (*.pdf)"
            )
            if not path:
                return None
        generate_recommendation_report(
            output_path=path,
            house_name=inputs["house_name"],
            recommendation=self._last_result,
            bird_count=inputs["bird_count"],
            body_weight_kg=inputs["body_weight_kg"],
            indoor_t_c=inputs["indoor_t_c"],
            indoor_rh_pct=inputs["indoor_rh_pct"],
            outdoor_t_c=inputs["outdoor_t_c"],
            outdoor_rh_pct=inputs["outdoor_rh_pct"],
            breed=inputs["breed"],
        )
        QMessageBox.information(self, "Exported", f"Report written to {path}")
        return path


def main() -> None:
    """Application entry point.

    Logging and the crash hook are installed BEFORE any window is
    constructed: a failure during start-up is exactly the case where a
    windowed build would otherwise die silently with nothing written
    down.
    """
    # --self-test verifies the PACKAGING (imports, bundled assets,
    # writable data dir, database, PDF, Qt) and exits. build.bat runs
    # this against the frozen exe, because a PyInstaller build can
    # succeed and still produce an app that cannot start.
    if "--self-test" in sys.argv:
        from pcis.self_test import run_self_test

        logging_setup.initialise()
        sys.exit(run_self_test())

    if "--version" in sys.argv:
        info = version.full_version_info()
        print(f"PCIS {info['version']} (build {info['build_date']}, "
              f"commit {info['git_commit']})")
        sys.exit(0)

    logging_setup.initialise()
    config.ensure_directories()

    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("PCIS")
    app.setApplicationVersion(version.VERSION)
    app.setOrganizationName("PCIS")

    icon_path = paths.resource_path("assets/pcis.ico")
    if icon_path.exists():
        from PySide6.QtGui import QIcon
        app.setWindowIcon(QIcon(str(icon_path)))

    style.apply_theme(app)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


# Without this, `python -m pcis.gui.main_window` imports the module,
# defines main(), and exits silently -- no window, no error message,
# nothing to debug. There is a test asserting this block exists
# (tests/test_gui.py::test_module_has_a_main_entry_point) because the
# failure is invisible: everything "works" except the app never opens.
if __name__ == "__main__":
    main()
