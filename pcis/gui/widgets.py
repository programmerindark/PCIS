"""Shared, Qt-only GUI widgets and helpers.

These pieces were originally defined inside ``main_window.py``. They
were extracted here so they can be reused by other GUI surfaces -- in
particular ``pcis.gui.guided`` -- WITHOUT importing ``main_window``,
which pulls in ``pcis.gui.charts`` and therefore ``PySide6.QtCharts``.
Keeping the reusable widgets in a module that imports only
``QtWidgets``/``QtCore`` lets the guided page be built and unit-tested
in environments where the (large) QtCharts add-on is not installed.

Everything here stores and returns values in SI; unit conversion is a
display-only concern handled via ``pcis.gui.units``. See the individual
docstrings -- the behaviour is byte-for-byte the same as when these
lived in ``main_window``.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDoubleSpinBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from pcis.core import envelope_presets as ep
from pcis.core import heat_moisture_balance as hmb
from pcis.gui import units


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
    # Never scroll sideways: the content must reflow/wrap to the viewport
    # width instead. Without this, any widget with a large minimum width
    # (e.g. the metrics row) forces a horizontal scrollbar and the tab
    # looks "zoomed in" and won't fit the window.
    area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
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

        # Most operators do not know their wall/ceiling U-value. This
        # picker lets them insert a surface by construction TYPE instead;
        # the U-value is a cited default from `envelope_presets` that
        # they can still edit. See that module for the sources.
        preset_row = QHBoxLayout()
        preset_hint = QLabel("Don't know your U-value? Add a typical surface:")
        preset_hint.setProperty("hint", True)
        self.preset_combo = QComboBox()
        for preset in ep.ENVELOPE_PRESETS:
            self.preset_combo.addItem(preset.label, preset)
        self.preset_combo.setToolTip(
            "Pick a construction type to insert a surface with a cited default "
            "U-value (from published poultry-housing R-values). Edit it afterwards "
            "if you know your own."
        )
        insert_btn = QPushButton("Add")
        insert_btn.clicked.connect(self._add_preset_row)
        preset_row.addWidget(preset_hint)
        preset_row.addWidget(self.preset_combo, 1)
        preset_row.addWidget(insert_btn)
        layout.addLayout(preset_row)

        buttons = QHBoxLayout()
        add_btn = QPushButton("Add blank row")
        add_btn.clicked.connect(lambda: self.add_row())
        remove_btn = QPushButton("Remove selected")
        remove_btn.clicked.connect(self.remove_selected)
        buttons.addWidget(add_btn)
        buttons.addWidget(remove_btn)
        buttons.addStretch(1)
        layout.addLayout(buttons)

        # Seed with two typical, CITED rows (an insulated, heated broiler
        # house) the user can edit rather than starting blank or from
        # uncited guesses. Values come from `envelope_presets`.
        self.add_row(ep.DEFAULT_WALL.default_name, ep.DEFAULT_WALL.u_value, 350.0)
        self.add_row(ep.DEFAULT_CEILING.default_name, ep.DEFAULT_CEILING.u_value, 1500.0)

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

    def _add_preset_row(self) -> None:
        """Insert a row for the construction type chosen in the picker,
        pre-filling its cited U-value. Area defaults to a rough figure
        the operator should correct to their own house."""
        preset = self.preset_combo.currentData()
        if preset is None:
            return
        # Ceilings cover the whole footprint; walls a smaller strip.
        # These are only starting areas -- the user edits them.
        default_area = 1000.0 if "ceiling" in preset.default_name else 200.0
        self.add_row(preset.default_name, preset.u_value, default_area)

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


class WeatherProfileTable(QWidget):
    """Editable table of outdoor conditions through the day: time,
    outdoor temperature, outdoor relative humidity.

    Reusable across the app (the guided page and the Recommendation
    tab). Temperatures are stored in SI (Celsius) and converted only for
    display, matching the rest of PCIS; `rows()` always returns SI. The
    time label is opaque free text, so "06:00", "dawn", or "step 3" all
    work. PCIS ships a starting example curve but no built-in weather
    model -- a defensible curve is site- and season-specific, so these
    are the operator's own readings.
    """

    #: A starting example day the user can edit (SI Celsius / % RH).
    DEFAULT_ROWS = [
        ("00:00", 24.0, 80.0), ("03:00", 22.0, 85.0), ("06:00", 21.0, 85.0),
        ("09:00", 28.0, 60.0), ("12:00", 34.0, 45.0), ("15:00", 37.0, 38.0),
        ("18:00", 34.0, 45.0), ("21:00", 28.0, 65.0),
    ]

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._system = units.METRIC
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.table = QTableWidget(0, 3)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Interactive)
        header.setStretchLastSection(True)
        header.setMinimumSectionSize(90)
        self.table.setAlternatingRowColors(True)
        self.table.setMinimumHeight(200)
        self._refresh_headers()
        layout.addWidget(self.table)

        buttons = QHBoxLayout()
        add_btn = QPushButton("Add time")
        add_btn.clicked.connect(lambda: self.add_row("12:00", 30.0, 50.0))
        remove_btn = QPushButton("Remove selected")
        remove_btn.clicked.connect(self._remove_selected)
        buttons.addWidget(add_btn)
        buttons.addWidget(remove_btn)
        buttons.addStretch(1)
        layout.addLayout(buttons)

        for label, t_c, rh in self.DEFAULT_ROWS:
            self.add_row(label, t_c, rh)
        self.table.resizeColumnsToContents()
        for col in range(self.table.columnCount() - 1):
            self.table.setColumnWidth(col, max(self.table.columnWidth(col) + 24, 120))

    def _refresh_headers(self) -> None:
        s = self._system
        self.table.setHorizontalHeaderLabels(
            ["Time", f"Outdoor temp ({s.temp_suffix.strip()})", "Outdoor RH (%)"]
        )

    def add_row(self, label: str, t_c: float, rh_pct: float) -> None:
        """Add a row. `t_c` is SI (Celsius); displayed converted."""
        row = self.table.rowCount()
        self.table.insertRow(row)
        self.table.setItem(row, 0, QTableWidgetItem(label))
        self.table.setItem(row, 1, _si_cell(self._system.temp_from_si(t_c), t_c))
        self.table.setItem(row, 2, QTableWidgetItem(f"{rh_pct:g}"))

    def _remove_selected(self) -> None:
        for index in sorted({i.row() for i in self.table.selectedIndexes()}, reverse=True):
            self.table.removeRow(index)

    def set_unit_system(self, system: units.UnitSystem) -> None:
        """Re-display temperatures in `system`, converting (not
        reinterpreting) the values already entered."""
        raw = self._read_rows(strict=False)
        self._system = system
        self._refresh_headers()
        self.table.setRowCount(0)
        for label, t_c, rh in raw:
            self.add_row(label, t_c, rh)

    def _read_rows(self, strict: bool) -> list[tuple[str, float, float]]:
        rows: list[tuple[str, float, float]] = []
        for row in range(self.table.rowCount()):
            label_item = self.table.item(row, 0)
            t_item = self.table.item(row, 1)
            rh_item = self.table.item(row, 2)
            label = label_item.text() if label_item else f"step {row + 1}"
            try:
                t_c = _cell_si_value(t_item, self._system.temp_to_si)
                rh = float(rh_item.text()) if rh_item else 0.0
            except ValueError as exc:
                if strict:
                    raise ValueError(
                        f"Row {row + 1} ({label}): temperature and humidity must be numbers"
                    ) from exc
                t_c, rh = 0.0, 0.0
            rows.append((label, t_c, rh))
        return rows

    def rows(self) -> list[tuple[str, float, float]]:
        """Validated (label, temp_c_SI, rh_pct) for each row, in order.

        Raises ValueError (for the caller to surface) if any cell is not
        a number.
        """
        return self._read_rows(strict=True)
