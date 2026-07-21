"""PCIS desktop GUI main window (PySide6).

This window is a thin wiring layer: it gathers user input, calls the
already-tested engineering modules (`pcis.core.*`), and displays the
result. It contains NO new engineering logic of its own -- every
number shown here comes from a function that already has its own
citation and unit tests. If you want to know why a number is what it
is, the answer lives in `pcis/core/*.py` and `PROGRESS.md`, not here.

Layout: a QTabWidget with four tabs (House & Equipment, Flock,
Environment, Recommendation). The Recommendation tab is where the
gathered inputs from the other three tabs are actually used.
"""

from __future__ import annotations

import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)
from sqlalchemy.orm import Session

from pcis.core import heat_moisture_balance as hmb
from pcis.core import recommendation_engine as rec_engine
from pcis.db.session import (
    init_db,
    save_flock_record,
    save_house_config,
    save_recommendation,
)
from pcis.equipment.cooling_pad import COOLING_PAD_CATALOG, CoolingPad
from pcis.equipment.fan_curve import FAN_CATALOG, FanCurve
from pcis.gui.charts import ComfortChartWidget, FanCurveChartWidget
from pcis.reports.pdf_report import generate_recommendation_report


class EnvelopeSurfaceEditor(QWidget):
    """Editable table of building-envelope surfaces (name / U-value /
    area), backed 1:1 by `pcis.core.heat_moisture_balance.Surface`.
    """

    COLUMNS = ("Surface name", "U-value (W/m2K)", "Area (m2)")

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)

        self.table = QTableWidget(0, len(self.COLUMNS))
        self.table.setHorizontalHeaderLabels(self.COLUMNS)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        layout.addWidget(self.table)

        buttons = QHBoxLayout()
        add_btn = QPushButton("Add surface")
        add_btn.clicked.connect(self.add_row)
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

    def add_row(self, name: str = "surface", u_value: float = 0.5, area_m2: float = 100.0) -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)
        self.table.setItem(row, 0, QTableWidgetItem(name))
        self.table.setItem(row, 1, QTableWidgetItem(str(u_value)))
        self.table.setItem(row, 2, QTableWidgetItem(str(area_m2)))

    def remove_selected(self) -> None:
        for index in sorted({i.row() for i in self.table.selectedIndexes()}, reverse=True):
            self.table.removeRow(index)

    def surfaces(self) -> list[hmb.Surface]:
        """Read the table back out as domain objects. Raises ValueError
        (surfaced to the user via a message box by the caller) if any
        row has invalid numbers.
        """
        result = []
        for row in range(self.table.rowCount()):
            name_item = self.table.item(row, 0)
            u_item = self.table.item(row, 1)
            a_item = self.table.item(row, 2)
            name = name_item.text() if name_item else f"surface_{row}"
            try:
                u_value = float(u_item.text()) if u_item else 0.0
                area_m2 = float(a_item.text()) if a_item else 0.0
            except ValueError as exc:
                raise ValueError(f"Row {row + 1} ({name}): U-value and area must be numbers") from exc
            result.append(hmb.Surface(name=name, u_value=u_value, area_m2=area_m2))
        return result


class MainWindow(QMainWindow):
    def __init__(self, db_path: str = "pcis.db") -> None:
        super().__init__()
        self.setWindowTitle("PCIS - Poultry Climate Intelligence System")
        self.resize(900, 700)

        self._engine = init_db(db_path)
        self._last_result: rec_engine.Recommendation | None = None
        self._last_inputs: dict | None = None

        tabs = QTabWidget()
        self.setCentralWidget(tabs)

        tabs.addTab(self._build_house_tab(), "House && Equipment")
        tabs.addTab(self._build_flock_tab(), "Flock")
        tabs.addTab(self._build_environment_tab(), "Environment")
        tabs.addTab(self._build_recommendation_tab(), "Recommendation")

    # ------------------------------------------------------------------
    # Tab builders
    # ------------------------------------------------------------------

    def _build_house_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)

        house_group = QGroupBox("House")
        form = QFormLayout(house_group)
        self.house_name_edit = QLineEdit("House 1")
        self.length_spin = self._make_spin(0.1, 500.0, 150.0, " m")
        self.width_spin = self._make_spin(0.1, 100.0, 15.0, " m")
        self.height_spin = self._make_spin(0.1, 20.0, 3.0, " m")
        form.addRow("House name", self.house_name_edit)
        form.addRow("Length", self.length_spin)
        form.addRow("Width", self.width_spin)
        form.addRow("Height (eave)", self.height_spin)
        layout.addWidget(house_group)

        envelope_group = QGroupBox("Envelope surfaces (for conduction loss)")
        envelope_layout = QVBoxLayout(envelope_group)
        self.envelope_editor = EnvelopeSurfaceEditor()
        envelope_layout.addWidget(self.envelope_editor)
        layout.addWidget(envelope_group)

        equipment_group = QGroupBox("Equipment")
        eq_form = QFormLayout(equipment_group)
        self.fan_combo = QComboBox()
        for fan in FAN_CATALOG:
            self.fan_combo.addItem(f"{fan.manufacturer} {fan.model}", fan)
        self.static_pressure_spin = self._make_spin(0.0, 200.0, 30.0, " Pa")
        self.pad_combo = QComboBox()
        self.pad_combo.addItem("(no cooling pad installed)", None)
        for pad in COOLING_PAD_CATALOG:
            self.pad_combo.addItem(f"{pad.manufacturer} {pad.model}", pad)
        eq_form.addRow("Fan model", self.fan_combo)
        eq_form.addRow("Design static pressure", self.static_pressure_spin)
        eq_form.addRow("Cooling pad", self.pad_combo)
        layout.addWidget(equipment_group)

        chart_group = QGroupBox("Fan curve")
        chart_layout = QVBoxLayout(chart_group)
        self.fan_chart = FanCurveChartWidget()
        chart_layout.addWidget(self.fan_chart)
        layout.addWidget(chart_group, stretch=1)

        self.fan_combo.currentIndexChanged.connect(self._refresh_fan_chart)
        self.static_pressure_spin.valueChanged.connect(self._refresh_fan_chart)
        self._refresh_fan_chart()

        return widget

    def _refresh_fan_chart(self) -> None:
        fan: FanCurve | None = self.fan_combo.currentData()
        if fan is not None:
            self.fan_chart.set_fan(fan, operating_static_pressure_pa=self.static_pressure_spin.value())

    def _build_flock_tab(self) -> QWidget:
        widget = QWidget()
        form = QFormLayout(widget)
        self.breed_edit = QLineEdit("Ross 308")
        self.bird_count_spin = QSpinBox()
        self.bird_count_spin.setRange(1, 500_000)
        self.bird_count_spin.setValue(20000)
        self.body_weight_spin = self._make_spin(0.01, 10.0, 2.5, " kg")
        form.addRow("Breed (informational only)", self.breed_edit)
        form.addRow("Bird count", self.bird_count_spin)
        form.addRow("Body weight", self.body_weight_spin)
        note = QLabel(
            "Note: breed is recorded for reference only. The underlying engineering\n"
            "model (CIGR broiler formula, Aviagen tables) is not currently breed-specific."
        )
        note.setWordWrap(True)
        form.addRow(note)
        return widget

    def _build_environment_tab(self) -> QWidget:
        widget = QWidget()
        form = QFormLayout(widget)
        self.indoor_t_spin = self._make_spin(-20.0, 50.0, 29.0, " C")
        self.indoor_rh_spin = self._make_spin(0.0, 100.0, 60.0, " %")
        self.outdoor_t_spin = self._make_spin(-40.0, 55.0, 35.0, " C")
        self.outdoor_rh_spin = self._make_spin(0.0, 100.0, 40.0, " %")
        self.delta_t_spin = self._make_spin(0.1, 20.0, 3.0, " C")
        self.outdoor_co2_spin = self._make_spin(300.0, 2000.0, 420.0, " ppm")
        form.addRow("Indoor temperature", self.indoor_t_spin)
        form.addRow("Indoor relative humidity", self.indoor_rh_spin)
        form.addRow("Outdoor temperature", self.outdoor_t_spin)
        form.addRow("Outdoor relative humidity", self.outdoor_rh_spin)
        form.addRow("Allowed temp rise (design dT)", self.delta_t_spin)
        form.addRow("Outdoor CO2 background", self.outdoor_co2_spin)
        return widget

    def _build_recommendation_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)

        run_btn = QPushButton("Run Recommendation")
        run_btn.clicked.connect(self.run_recommendation)
        layout.addWidget(run_btn)

        self.results_label = QLabel("Run a recommendation to see results here.")
        self.results_label.setWordWrap(True)
        layout.addWidget(self.results_label)

        self.comfort_chart = ComfortChartWidget()
        layout.addWidget(self.comfort_chart, stretch=1)

        layout.addWidget(QLabel("Engineering explanation:"))
        self.explanation_list = QListWidget()
        layout.addWidget(self.explanation_list, stretch=1)

        buttons = QHBoxLayout()
        self.save_db_btn = QPushButton("Save to Database")
        self.save_db_btn.clicked.connect(self.save_to_database)
        self.save_db_btn.setEnabled(False)
        self.export_pdf_btn = QPushButton("Export PDF Report...")
        self.export_pdf_btn.clicked.connect(self.export_pdf)
        self.export_pdf_btn.setEnabled(False)
        buttons.addWidget(self.save_db_btn)
        buttons.addWidget(self.export_pdf_btn)
        buttons.addStretch(1)
        layout.addLayout(buttons)

        return widget

    @staticmethod
    def _make_spin(minimum: float, maximum: float, value: float, suffix: str) -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        spin.setRange(minimum, maximum)
        spin.setValue(value)
        spin.setSuffix(suffix)
        spin.setDecimals(2)
        return spin

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def gather_inputs(self) -> dict:
        """Read every widget into a plain dict. Split out from
        `run_recommendation` so it can be exercised directly in tests
        without needing to simulate button clicks.
        """
        fan: FanCurve = self.fan_combo.currentData()
        pad: CoolingPad | None = self.pad_combo.currentData()
        return dict(
            house_name=self.house_name_edit.text().strip() or "House 1",
            length_m=self.length_spin.value(),
            width_m=self.width_spin.value(),
            height_m=self.height_spin.value(),
            surfaces=self.envelope_editor.surfaces(),
            breed=self.breed_edit.text().strip() or "unspecified",
            bird_count=self.bird_count_spin.value(),
            body_weight_kg=self.body_weight_spin.value(),
            indoor_t_c=self.indoor_t_spin.value(),
            indoor_rh_pct=self.indoor_rh_spin.value(),
            outdoor_t_c=self.outdoor_t_spin.value(),
            outdoor_rh_pct=self.outdoor_rh_spin.value(),
            delta_t_c=self.delta_t_spin.value(),
            outdoor_co2_ppm=self.outdoor_co2_spin.value(),
            fan=fan,
            design_static_pressure_pa=self.static_pressure_spin.value(),
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

        self.results_label.setText(
            f"<b>Fans ON:</b> {result.fans_on}"
            f" &nbsp;|&nbsp; <b>Pads ON:</b> {'Yes' if result.pads_on else 'No'}"
            f" &nbsp;|&nbsp; <b>Required airflow:</b> {result.required_airflow_m3_per_h:,.0f} m3/h"
            f" &nbsp;|&nbsp; <b>Governing:</b> {result.governing_constraint.replace('_', ' ')}"
            f" &nbsp;|&nbsp; <b>Confidence:</b> {result.confidence_score:.0f}/100"
        )
        self.explanation_list.clear()
        self.explanation_list.addItems(result.explanation)

        self.comfort_chart.set_recommendation(result, outdoor_t_c=inputs["outdoor_t_c"])

        self.save_db_btn.setEnabled(True)
        self.export_pdf_btn.setEnabled(True)
        return result

    def save_to_database(self) -> None:
        if self._last_result is None or self._last_inputs is None:
            return
        inputs = self._last_inputs
        with Session(self._engine) as session:
            house = save_house_config(
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
                recommendation=self._last_result,
            )
            session.commit()
        QMessageBox.information(self, "Saved", f"Saved house '{inputs['house_name']}' and this recommendation.")

    def export_pdf(self, path: str | None = None) -> str | None:
        if self._last_result is None or self._last_inputs is None:
            return None
        inputs = self._last_inputs
        if path is None:
            path, _ = QFileDialog.getSaveFileName(self, "Export PDF Report", f"{inputs['house_name']}.pdf", "PDF files (*.pdf)")
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
    app = QApplication.instance() or QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
