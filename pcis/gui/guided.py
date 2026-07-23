"""Guided single-page schedule flow.

This is the answer to the operator's whole question in one screen:
fill in the farm, the flock, and the day's weather, press one button,
and get back the full day-by-day plan -- how many fans to run and when,
when the cooling pads should be on, and when the heaters should fire --
plus the Aviagen day-wise target-house-temperature chart it is all
built against.

It replaces the older "Schedule" tab, which asked for the same
information but scattered across several other tabs first, and was
reported as confusing to use. Everything needed now lives here, in
numbered steps, top to bottom.

Design rules kept from the rest of PCIS:
  * No new engineering. Every number comes from the already-tested
    core (`digital_twin`, `recommendation_engine`, `comfort_engine`,
    `growth_curve`) via `guided_model`. This file only gathers input
    and paints output.
  * SI internally, display units on screen (see `pcis.gui.units`); the
    engine never sees anything but SI.
  * Honesty surfaced, not hidden -- the model's own notes and warnings
    (undersized fans, unreachable target, heating needed, clamped RH)
    are shown verbatim beneath the schedule.

It imports only `QtWidgets`/`QtGui`/`QtCore` (via `pcis.gui.widgets`),
never `pcis.gui.charts`, so it does not depend on the QtCharts add-on;
the target-temperature chart is drawn directly with `QPainter`.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen, QPolygonF
from PySide6.QtCore import QPointF
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QListWidget,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
    QAbstractItemView,
)

from pcis.core import digital_twin as twin
from pcis.core import growth_curve as gc
from pcis.equipment.cooling_pad import COOLING_PAD_CATALOG, CoolingPad
from pcis.equipment.fan_curve import FAN_CATALOG, FanCurve
from pcis.gui import guided_model as gm
from pcis.gui import style, units
from pcis.gui.widgets import (
    EnvelopeSurfaceEditor,
    UnitAwareSpinBox,
    _cell_si_value,
    _hint,
    _si_cell,
)


class TargetTempChart(QWidget):
    """A small, dependency-free line chart of the day-wise target house
    temperature across the grow-out, drawn with `QPainter`.

    Deliberately not a `QtCharts` widget: keeping it pure `QPainter`
    means the guided page carries no dependency on the (large) QtCharts
    add-on, and the same code renders in a headless test via the
    offscreen platform. The curve data is Aviagen-derived and supplied
    by `guided_model.target_temperature_curve`; this class only draws
    it.
    """

    _MARGIN_LEFT = 52
    _MARGIN_BOTTOM = 34
    _MARGIN_TOP = 14
    _MARGIN_RIGHT = 16

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._points: list[gm.TargetTempPoint] = []
        self._system: units.UnitSystem = units.METRIC
        self._marker_day: int | None = None
        self.setMinimumHeight(240)

    def set_curve(
        self,
        points: list[gm.TargetTempPoint],
        system: units.UnitSystem,
        marker_day: int | None = None,
    ) -> None:
        self._points = list(points)
        self._system = system
        self._marker_day = marker_day
        self.update()

    def set_unit_system(self, system: units.UnitSystem) -> None:
        self._system = system
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt override)
        pal = style.active()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)

        w, h = self.width(), self.height()
        painter.fillRect(0, 0, w, h, QColor(pal["SURFACE"]))

        if not self._points:
            painter.setPen(QColor(pal["INK_MUTED"]))
            painter.drawText(
                self.rect(),
                Qt.AlignCenter,
                "The day-wise target-temperature chart appears here.",
            )
            painter.end()
            return

        plot_l = self._MARGIN_LEFT
        plot_r = w - self._MARGIN_RIGHT
        plot_t = self._MARGIN_TOP
        plot_b = h - self._MARGIN_BOTTOM
        plot_w = max(1, plot_r - plot_l)
        plot_h = max(1, plot_b - plot_t)

        days = [p.day for p in self._points]
        temps = [self._system.temp_from_si(p.target_temp_c) for p in self._points]
        d_min, d_max = min(days), max(days)
        t_min, t_max = min(temps), max(temps)
        # Pad the temperature axis a little so the line never touches the frame.
        span = max(1.0, t_max - t_min)
        t_lo = t_min - span * 0.12
        t_hi = t_max + span * 0.12

        def x_of(day: float) -> float:
            return plot_l + (day - d_min) / max(1, (d_max - d_min)) * plot_w

        def y_of(temp: float) -> float:
            return plot_b - (temp - t_lo) / (t_hi - t_lo) * plot_h

        # --- gridlines + Y labels (temperature) --------------------------
        grid_pen = QPen(QColor(pal["LINE"]))
        grid_pen.setWidth(1)
        label_font = QFont()
        label_font.setPointSize(8)
        painter.setFont(label_font)
        n_ticks = 5
        for i in range(n_ticks + 1):
            temp = t_lo + (t_hi - t_lo) * i / n_ticks
            y = y_of(temp)
            painter.setPen(grid_pen)
            painter.drawLine(int(plot_l), int(y), int(plot_r), int(y))
            painter.setPen(QColor(pal["INK_MUTED"]))
            painter.drawText(
                0, int(y) - 8, self._MARGIN_LEFT - 6, 16,
                Qt.AlignRight | Qt.AlignVCenter,
                f"{temp:.0f}{self._system.temp_suffix}",
            )

        # --- X labels (day) ---------------------------------------------
        painter.setPen(QColor(pal["INK_MUTED"]))
        x_step = max(1, (d_max - d_min) // 7)
        day = d_min
        while day <= d_max:
            x = x_of(day)
            painter.drawText(
                int(x) - 14, plot_b + 6, 28, 16,
                Qt.AlignHCenter | Qt.AlignTop, f"{day}",
            )
            day += x_step
        painter.drawText(
            plot_l, h - 15, plot_w, 14,
            Qt.AlignHCenter | Qt.AlignVCenter, "Bird age (days)",
        )

        # --- the curve ---------------------------------------------------
        poly = QPolygonF([QPointF(x_of(p.day), y_of(t)) for p, t in zip(self._points, temps)])
        curve_pen = QPen(QColor(pal["ACCENT"]))
        curve_pen.setWidth(2)
        painter.setPen(curve_pen)
        painter.drawPolyline(poly)

        # --- marker at the selected age ----------------------------------
        if self._marker_day is not None and d_min <= self._marker_day <= d_max:
            match = next((p for p in self._points if p.day == self._marker_day), None)
            if match is not None:
                mt = self._system.temp_from_si(match.target_temp_c)
                mx, my = x_of(self._marker_day), y_of(mt)
                marker_pen = QPen(QColor(pal["WARN"]))
                marker_pen.setWidth(1)
                marker_pen.setStyle(Qt.DashLine)
                painter.setPen(marker_pen)
                painter.drawLine(int(mx), plot_t, int(mx), plot_b)
                painter.setBrush(QColor(pal["WARN"]))
                painter.setPen(Qt.NoPen)
                painter.drawEllipse(QPointF(mx, my), 4, 4)
                painter.setPen(QColor(pal["INK"]))
                tag = f"day {self._marker_day}: {mt:.1f}{self._system.temp_suffix}"
                fm = QFontMetrics(painter.font())
                tw = fm.horizontalAdvance(tag)
                tx = min(mx + 6, plot_r - tw)
                painter.drawText(int(tx), int(my) - 6, tag)
        painter.end()


class GuidedScheduleWidget(QWidget):
    """The whole guided flow, as one scrollable page.

    Self-contained: it owns every input it needs, so the operator never
    has to visit another tab first. `set_unit_system` keeps its
    displayed values in step with the app's global unit selector.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._system: units.UnitSystem = units.METRIC
        self._unit_spins: list[UnitAwareSpinBox] = []
        self._last_result: twin.SimulationResult | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        intro = QLabel("Guided schedule")
        intro_font = QFont()
        intro_font.setPointSize(15)
        intro_font.setWeight(QFont.Bold)
        intro.setFont(intro_font)
        root.addWidget(intro)
        root.addWidget(
            _hint(
                "Fill in the three steps below and press Build my schedule. PCIS returns "
                "how many fans to run and when, when the cooling pads and heaters should be "
                "on, and the Aviagen day-by-day target house temperature it is all based on."
            )
        )

        root.addWidget(self._build_farm_group())
        root.addWidget(self._build_flock_group())
        root.addWidget(self._build_weather_group())

        build_btn = QPushButton("Build my schedule")
        build_btn.setProperty("primary", True)
        build_btn.clicked.connect(self.build_schedule)
        root.addWidget(build_btn)

        root.addWidget(self._build_output_area())
        root.addStretch(1)

        self._apply_tooltips()
        self._on_age_changed(self.age_spin.value())

    def _apply_tooltips(self) -> None:
        """Give every input a tooltip (and, as a fallback, an accessible
        name) so the whole page is self-explanatory and passes the
        app-wide "every field is documented" contract test."""
        tips = {
            self.length_spin: "Inside length of the house.",
            self.width_spin: "Inside width of the house.",
            self.height_spin: "Eave (sidewall) height of the house.",
            self.fan_combo: "The exhaust-fan model to size the schedule against.",
            self.installed_fans_spin: "How many fans you physically have. Used only to flag a "
                                      "shortfall; the required count is never capped to it.",
            self.static_pressure_spin: "The static pressure the fan curve is read at — your "
                                       "house's design operating point.",
            self.pad_combo: "Evaporative cooling pad, if installed. Leave as none if you have none.",
            self.heater_kw_spin: "Total installed heater capacity. Needed only to turn the heating "
                                 "requirement into an on-time (duty %). Leave at 0 to just see "
                                 "whether heat is needed and how many kW.",
            self.bird_count_spin: "Number of birds in the house.",
            self.age_spin: "Bird age in days. Auto-fills body weight from the Aviagen Ross 308 "
                           "curve and sets the day-wise target temperature.",
            self.body_weight_spin: "Representative live body weight. Auto-filled from the Aviagen "
                                   "Ross 308 growth curve; edit to override.",
            self.indoor_rh_spin: "Indoor relative humidity the target temperature is evaluated at. "
                                 "Above 70% the Aviagen table is clamped and flagged.",
            self.delta_t_spin: "How much warmer the air may get crossing the house. A temperature "
                               "DIFFERENCE: 1 °C = 1.8 °F, with no 32° offset.",
            self.step_hours_spin: "How much time each weather row represents. Used to convert step "
                                  "counts into hours.",
        }
        for widget, tip in tips.items():
            widget.setToolTip(tip)
            if not widget.accessibleName():
                widget.setAccessibleName(tip.split(".")[0])

    # ------------------------------------------------------------------
    # Input sections
    # ------------------------------------------------------------------

    def _unit_spin(
        self, quantity: str, si_min: float, si_max: float, si_value: float, decimals: int = 2
    ) -> UnitAwareSpinBox:
        spin = UnitAwareSpinBox(quantity, si_min, si_max, si_value, decimals)
        self._unit_spins.append(spin)
        return spin

    def _build_farm_group(self) -> QGroupBox:
        group = QGroupBox("1.  Your farm && equipment")
        outer = QVBoxLayout(group)

        form = QFormLayout()
        form.setSpacing(9)
        form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)

        self.length_spin = self._unit_spin("length", 0.1, 500.0, 150.0)
        self.width_spin = self._unit_spin("length", 0.1, 100.0, 15.0)
        self.height_spin = self._unit_spin("length", 0.1, 20.0, 3.0)
        form.addRow("House length", self.length_spin)
        form.addRow("House width", self.width_spin)
        form.addRow("House height (eave)", self.height_spin)

        self.fan_combo = QComboBox()
        for fan in FAN_CATALOG:
            self.fan_combo.addItem(f"{fan.manufacturer} {fan.model}", fan)
        form.addRow("Fan model", self.fan_combo)

        self.installed_fans_spin = QSpinBox()
        self.installed_fans_spin.setRange(0, 200)
        self.installed_fans_spin.setValue(8)
        self.installed_fans_spin.setSpecialValueText("(not specified)")
        form.addRow("Fans installed", self.installed_fans_spin)

        self.static_pressure_spin = self._unit_spin("pressure", 0.0, 200.0, 30.0, decimals=3)
        form.addRow("Design static pressure", self.static_pressure_spin)

        self.pad_combo = QComboBox()
        self.pad_combo.addItem("(no cooling pad installed)", None)
        for pad in COOLING_PAD_CATALOG:
            self.pad_combo.addItem(f"{pad.manufacturer} {pad.model}", pad)
        form.addRow("Cooling pad", self.pad_combo)

        self.heater_kw_spin = QDoubleSpinBox()
        self.heater_kw_spin.setRange(0.0, 2000.0)
        self.heater_kw_spin.setValue(0.0)
        self.heater_kw_spin.setSuffix(" kW")
        self.heater_kw_spin.setDecimals(1)
        self.heater_kw_spin.setSpecialValueText("(not specified)")
        form.addRow("Heater capacity", self.heater_kw_spin)
        outer.addLayout(form)

        outer.addWidget(
            _hint(
                "Envelope surfaces below drive conduction heat loss/gain (Q = U·A·ΔT), which "
                "matters most for the heating requirement. U-values are yours to supply — PCIS "
                "has no verified materials table and will not guess one. Make the areas match "
                "the house dimensions above."
            )
        )
        self.envelope_editor = EnvelopeSurfaceEditor()
        outer.addWidget(self.envelope_editor)
        return group

    def _build_flock_group(self) -> QGroupBox:
        group = QGroupBox("2.  Your flock")
        form = QFormLayout(group)
        form.setSpacing(9)
        form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)

        self.bird_count_spin = QSpinBox()
        self.bird_count_spin.setRange(1, 500_000)
        self.bird_count_spin.setValue(20000)
        self.bird_count_spin.setGroupSeparatorShown(True)
        form.addRow("Bird count", self.bird_count_spin)

        self.age_spin = QSpinBox()
        self.age_spin.setRange(0, 100)
        self.age_spin.setValue(35)
        self.age_spin.setSuffix(" days")
        self.age_spin.valueChanged.connect(self._on_age_changed)
        form.addRow("Bird age", self.age_spin)

        self.body_weight_spin = self._unit_spin("mass", 0.01, 10.0, 2.296)
        form.addRow("Body weight", self.body_weight_spin)

        self.growth_status_label = _hint("")
        form.addRow("", self.growth_status_label)

        self.indoor_rh_spin = QDoubleSpinBox()
        self.indoor_rh_spin.setRange(0.0, 100.0)
        self.indoor_rh_spin.setValue(60.0)
        self.indoor_rh_spin.setSuffix(" %")
        self.indoor_rh_spin.setDecimals(1)
        form.addRow("Indoor target RH", self.indoor_rh_spin)

        self.delta_t_spin = self._unit_spin("delta_temp", 0.1, 20.0, 3.0)
        form.addRow("Allowed temperature rise", self.delta_t_spin)
        form.addRow(
            "",
            _hint(
                "Body weight auto-fills from the published Aviagen Ross 308 growth curve when "
                "you change the age; type over it if your flock differs. Allowed temperature "
                "rise is how much warmer the air may get crossing the house (a difference, so "
                "1 °C = 1.8 °F)."
            ),
        )
        return group

    def _build_weather_group(self) -> QGroupBox:
        group = QGroupBox("3.  Weather through the day")
        layout = QVBoxLayout(group)
        layout.addWidget(
            _hint(
                "Enter the outdoor temperature and humidity at each time of day. PCIS ships no "
                "built-in weather curve — a defensible one is site- and season-specific — so "
                "these are your readings. Edit the starting rows or add your own."
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
        self.profile_table.setMinimumHeight(230)
        layout.addWidget(self.profile_table)

        btns = QHBoxLayout()
        add_btn = QPushButton("Add time")
        add_btn.clicked.connect(lambda: self._add_profile_row("12:00", 30.0, 50.0))
        del_btn = QPushButton("Remove selected")
        del_btn.clicked.connect(self._remove_profile_rows)
        btns.addWidget(add_btn)
        btns.addWidget(del_btn)
        btns.addStretch(1)

        step_label = QLabel("Time per row:")
        self.step_hours_spin = QDoubleSpinBox()
        self.step_hours_spin.setRange(0.25, 24.0)
        self.step_hours_spin.setValue(3.0)
        self.step_hours_spin.setSuffix(" h")
        self.step_hours_spin.setDecimals(2)
        btns.addWidget(step_label)
        btns.addWidget(self.step_hours_spin)
        layout.addLayout(btns)

        for label, t_c, rh in [
            ("00:00", 24.0, 80.0), ("03:00", 22.0, 85.0), ("06:00", 21.0, 85.0),
            ("09:00", 28.0, 60.0), ("12:00", 34.0, 45.0), ("15:00", 37.0, 38.0),
            ("18:00", 34.0, 45.0), ("21:00", 28.0, 65.0),
        ]:
            self._add_profile_row(label, t_c, rh)
        self._refresh_profile_headers()
        # Size the Time/Temp columns to their headers so "Outdoor temp
        # (°C)" is not truncated; the last (RH) column stretches to fill.
        self.profile_table.resizeColumnsToContents()
        for col in range(self.profile_table.columnCount() - 1):
            self.profile_table.setColumnWidth(
                col, max(self.profile_table.columnWidth(col) + 24, 130)
            )
        return group

    # ------------------------------------------------------------------
    # Output section
    # ------------------------------------------------------------------

    def _build_output_area(self) -> QWidget:
        wrap = QWidget()
        layout = QVBoxLayout(wrap)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        self.summary_label = QLabel()
        self.summary_label.setWordWrap(True)
        self.summary_label.setVisible(False)
        layout.addWidget(self.summary_label)

        schedule_group = QGroupBox("Your schedule")
        sg_layout = QVBoxLayout(schedule_group)
        self.empty_label = _hint(
            "Press “Build my schedule” to generate the day’s fan, pad and heater plan."
        )
        self.empty_label.setAlignment(Qt.AlignCenter)
        self.empty_label.setMinimumHeight(40)
        sg_layout.addWidget(self.empty_label)
        self.blocks_list = QListWidget()
        self.blocks_list.setWordWrap(True)
        self.blocks_list.setMinimumHeight(150)
        self.blocks_list.setVisible(False)
        sg_layout.addWidget(self.blocks_list)
        layout.addWidget(schedule_group)

        chart_group = QGroupBox("Day-wise target house temperature (Aviagen Ross 308)")
        cg_layout = QVBoxLayout(chart_group)
        cg_layout.addWidget(
            _hint(
                "The temperature the house should be held at as the birds grow, at your indoor "
                "RH. The dashed marker is the age you entered above."
            )
        )
        self.target_chart = TargetTempChart()
        cg_layout.addWidget(self.target_chart)
        layout.addWidget(chart_group)

        self.notes_label = QLabel()
        self.notes_label.setWordWrap(True)
        self.notes_label.setVisible(False)
        layout.addWidget(self.notes_label)

        # Draw the curve immediately so the chart isn't blank on first open.
        self._refresh_target_chart()
        return wrap

    # ------------------------------------------------------------------
    # Profile table helpers
    # ------------------------------------------------------------------

    def _refresh_profile_headers(self) -> None:
        s = self._system
        self.profile_table.setHorizontalHeaderLabels(
            ["Time", f"Outdoor temp ({s.temp_suffix.strip()})", "Outdoor RH (%)"]
        )

    def _add_profile_row(self, label: str, t_c: float, rh_pct: float) -> None:
        row = self.profile_table.rowCount()
        self.profile_table.insertRow(row)
        self.profile_table.setItem(row, 0, QTableWidgetItem(label))
        self.profile_table.setItem(row, 1, _si_cell(self._system.temp_from_si(t_c), t_c))
        self.profile_table.setItem(row, 2, QTableWidgetItem(f"{rh_pct:g}"))

    def _remove_profile_rows(self) -> None:
        for index in sorted(
            {i.row() for i in self.profile_table.selectedIndexes()}, reverse=True
        ):
            self.profile_table.removeRow(index)

    def read_profile(self) -> list[twin.OutdoorCondition]:
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
    # Reactions
    # ------------------------------------------------------------------

    def _on_age_changed(self, age_days: int) -> None:
        try:
            weight_kg = gc.ross_308_body_weight_kg(float(age_days))
        except ValueError:
            self.growth_status_label.setText(
                f"Age {age_days} days is outside the published Aviagen Ross 308 table "
                f"({gc.ROSS_308_MIN_AGE_DAYS}–{gc.ROSS_308_MAX_AGE_DAYS} days) — enter body "
                "weight manually."
            )
            self._refresh_target_chart()
            return
        self.body_weight_spin.set_si_value(weight_kg)
        shown = self._system.mass_from_si(weight_kg)
        self.growth_status_label.setText(
            f"Body weight auto-filled to {shown:.3f}{self._system.mass_suffix} from the "
            f"Aviagen Ross 308 growth curve at day {age_days} (edit above to override)."
        )
        self._refresh_target_chart()

    def _refresh_target_chart(self) -> None:
        curve = gm.target_temperature_curve(self.indoor_rh_spin.value())
        self.target_chart.set_curve(curve, self._system, marker_day=self.age_spin.value())

    def set_unit_system(self, system: units.UnitSystem) -> None:
        """Re-display every value in `system`. Reads the profile table in
        the OUTGOING system first so on-screen numbers are converted, not
        reinterpreted (mirrors the main window's behaviour)."""
        try:
            profile_si = self.read_profile()
        except ValueError:
            profile_si = None

        self._system = system
        for spin in self._unit_spins:
            spin.set_unit_system(system)
        self.envelope_editor.set_unit_system(system)

        if profile_si is not None:
            self.profile_table.setRowCount(0)
            self._refresh_profile_headers()
            for cond in profile_si:
                self._add_profile_row(cond.label, cond.t_c, cond.rh_pct)
        else:
            self._refresh_profile_headers()

        self.target_chart.set_unit_system(system)
        self._refresh_target_chart()
        if self._last_result is not None:
            self._render_outputs(self._last_result)

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------

    def gather(self) -> dict:
        """Every input, in SI. Split out so it can be tested without
        clicking the button."""
        return dict(
            length_m=self.length_spin.si_value(),
            width_m=self.width_spin.si_value(),
            height_m=self.height_spin.si_value(),
            surfaces=self.envelope_editor.surfaces(),
            fan=self.fan_combo.currentData(),
            design_static_pressure_pa=self.static_pressure_spin.si_value(),
            cooling_pad=self.pad_combo.currentData(),
            installed_fan_count=(
                self.installed_fans_spin.value() if self.installed_fans_spin.value() > 0 else None
            ),
            heater_capacity_w=(
                self.heater_kw_spin.value() * 1000.0 if self.heater_kw_spin.value() > 0 else None
            ),
            bird_count=self.bird_count_spin.value(),
            age_days=float(self.age_spin.value()),
            indoor_rh_pct=self.indoor_rh_spin.value(),
            delta_t_c=self.delta_t_spin.si_value(),
            step_duration_h=self.step_hours_spin.value(),
        )

    def build_schedule(self) -> twin.SimulationResult | None:
        try:
            conditions = self.read_profile()
        except ValueError as exc:
            QMessageBox.warning(self, "Invalid weather input", str(exc))
            return None
        if not conditions:
            QMessageBox.warning(
                self, "No weather entered",
                "Add at least one time row in step 3 (Weather through the day).",
            )
            return None

        try:
            inputs = self.gather()
        except ValueError as exc:
            QMessageBox.warning(self, "Invalid input", str(exc))
            return None

        try:
            result = twin.simulate_schedule(
                conditions=conditions,
                age_days=inputs["age_days"],
                bird_count=inputs["bird_count"],
                envelope_surfaces=inputs["surfaces"],
                fan=inputs["fan"],
                design_static_pressure_pa=inputs["design_static_pressure_pa"],
                delta_t_c=inputs["delta_t_c"],
                indoor_rh_pct=inputs["indoor_rh_pct"],
                cooling_pad=inputs["cooling_pad"],
                installed_fan_count=inputs["installed_fan_count"],
                heater_capacity_w=inputs["heater_capacity_w"],
            )
        except (ValueError, RuntimeError) as exc:
            QMessageBox.warning(self, "Could not build schedule", str(exc))
            return None

        self._last_result = result
        self._render_outputs(result)
        self._refresh_target_chart()
        return result

    # ------------------------------------------------------------------
    # Render
    # ------------------------------------------------------------------

    def _render_outputs(self, result: twin.SimulationResult) -> None:
        pal = style.active()
        s = self._system
        step_h = self.step_hours_spin.value()
        summary = gm.summarize(result, step_h)

        # --- consolidated blocks ----------------------------------------
        self.blocks_list.clear()
        for block in result.blocks:
            self.blocks_list.addItem(gm.describe_block(block, step_h))
        self.empty_label.setVisible(False)
        self.blocks_list.setVisible(True)

        # --- summary strip ----------------------------------------------
        parts = [
            f"<b>Peak {summary.peak_fans_on} fans</b>",
            f"{summary.fan_hours:g} fan-hours over {summary.total_hours:g} h",
        ]
        if summary.pad_hours > 0:
            parts.append(f"pads {summary.pad_hours:g} h")
        if summary.heating_hours > 0:
            parts.append(f"heat {summary.heating_hours:g} h")
        flags = []
        if summary.fans_undersized:
            flags.append("⚠ more fans needed than installed")
        if summary.heater_undersized:
            flags.append("⚠ heater undersized")
        if summary.target_unreachable:
            flags.append("⚠ target unreachable at times")
        summary_html = "  •  ".join(parts)
        if flags:
            summary_html += (
                f'<br><span style="color:{pal["DANGER"]};font-weight:600;">'
                + "  •  ".join(flags)
                + "</span>"
            )
        self.summary_label.setText(summary_html)
        self.summary_label.setVisible(True)

        # --- honesty notes verbatim -------------------------------------
        if result.notes:
            joined = "<br>".join(
                (
                    f'<span style="color:{pal["DANGER"]};font-weight:600;">{n}</span>'
                    if n.startswith(("WARNING", "HEATING"))
                    else f'<span style="color:{pal["INK_MUTED"]};">{n}</span>'
                )
                for n in result.notes
            )
            self.notes_label.setText(joined)
            self.notes_label.setVisible(True)
        else:
            self.notes_label.setVisible(False)
