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
