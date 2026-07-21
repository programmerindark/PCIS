"""Embedded chart widgets for the PCIS GUI.

Charting library choice
------------------------
The original project brief listed Plotly for charts/dashboards.
Plotly renders to HTML/JS, which does not embed natively inside a
desktop Qt widget tree without `QtWebEngine` -- a large additional
dependency (an embedded Chromium) that is fragile to install in a
minimal/headless environment (this is exactly the kind of environment
this GUI was smoke-tested in). `PySide6.QtCharts` ships as part of
PySide6 itself, renders natively into the widget tree with no extra
dependency, and -- importantly for testability -- can be interrogated
programmatically in headless tests (reading back series data points)
without needing a screenshot. That trade-off is why these charts use
QtCharts rather than Plotly; flagging it here since it's a deviation
from the original brief's specific library choice, not a silent
substitution.

Both widgets below are pure presentation: they take already-computed,
already-cited engineering objects (`FanCurve`, `Recommendation`) and
plot their existing fields. No new engineering numbers are computed
here.
"""

from __future__ import annotations

from PySide6.QtCharts import (
    QBarCategoryAxis,
    QBarSeries,
    QBarSet,
    QChart,
    QChartView,
    QLineSeries,
    QScatterSeries,
    QValueAxis,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import QVBoxLayout, QWidget

from pcis.core.recommendation_engine import Recommendation
from pcis.equipment.fan_curve import FanCurve


class FanCurveChartWidget(QWidget):
    """Airflow (m3/h) vs. static pressure (Pa) for one fan, with the
    current operating point marked.

    Plots `FanCurve.static_pressure_pa` / `FanCurve.airflow_m3_per_h`
    directly -- the same tested data points `airflow_at_static_pressure`
    interpolates between, so the chart is always consistent with the
    number actually used for fan sizing.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.chart = QChart()
        self.chart.setTitle("Fan curve: airflow vs. static pressure")
        self.chart.legend().setVisible(True)

        self.chart_view = QChartView(self.chart)
        self.chart_view.setRenderHint(QPainter.Antialiasing)

        layout = QVBoxLayout(self)
        layout.addWidget(self.chart_view)

        self._curve_series: QLineSeries | None = None
        self._operating_series: QScatterSeries | None = None

    def set_fan(self, fan: FanCurve, operating_static_pressure_pa: float | None = None) -> None:
        """Redraw the chart for a given fan, optionally marking the
        design operating point (design_static_pressure_pa from the
        House & Equipment tab).
        """
        self.chart.removeAllSeries()
        for axis in list(self.chart.axes()):
            self.chart.removeAxis(axis)

        points = sorted(zip(fan.static_pressure_pa, fan.airflow_m3_per_h))

        curve = QLineSeries()
        curve.setName(f"{fan.manufacturer} {fan.model}")
        for sp, flow in points:
            curve.append(sp, flow)
        self.chart.addSeries(curve)
        self._curve_series = curve

        axis_x = QValueAxis()
        axis_x.setTitleText("Static pressure (Pa)")
        axis_y = QValueAxis()
        axis_y.setTitleText("Airflow (m3/h)")
        self.chart.addAxis(axis_x, Qt.AlignBottom)
        self.chart.addAxis(axis_y, Qt.AlignLeft)
        curve.attachAxis(axis_x)
        curve.attachAxis(axis_y)

        if operating_static_pressure_pa is not None:
            try:
                op_flow = fan.airflow_at_static_pressure(operating_static_pressure_pa)
            except ValueError:
                op_flow = None
            if op_flow is not None:
                marker = QScatterSeries()
                marker.setName("Operating point")
                marker.setMarkerSize(12.0)
                marker.append(operating_static_pressure_pa, op_flow)
                self.chart.addSeries(marker)
                marker.attachAxis(axis_x)
                marker.attachAxis(axis_y)
                self._operating_series = marker

        # Kept short deliberately -- QChart titles don't wrap. Full
        # citation lives in fan.source / fan_curve.py / PROGRESS.md.
        self.chart.setTitle(f"Fan curve: {fan.manufacturer} {fan.model}")


class ComfortChartWidget(QWidget):
    """Bar chart comparing outdoor / supply / indoor / target dry-bulb
    temperatures for the current recommendation, plus a short THI
    status readout.

    All values come directly from an already-computed `Recommendation`
    (and the caller-supplied outdoor temperature) -- this widget adds
    no new numbers, only a visualization of ones already cited in
    `comfort_engine.py` and `recommendation_engine.py`.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.chart = QChart()
        self.chart.setTitle("Temperatures: outdoor / supply / indoor / target")
        self.chart.legend().setVisible(False)

        self.chart_view = QChartView(self.chart)
        self.chart_view.setRenderHint(QPainter.Antialiasing)

        layout = QVBoxLayout(self)
        layout.addWidget(self.chart_view)

    def set_recommendation(self, result: Recommendation, outdoor_t_c: float) -> None:
        self.chart.removeAllSeries()
        for axis in list(self.chart.axes()):
            self.chart.removeAxis(axis)

        categories = ["Outdoor", "Supply (post-pad)" if result.pads_on else "Supply", "Indoor", "Target"]
        values = [outdoor_t_c, result.supply_air_t_c, result.comfort.t_c, result.comfort.target_temp_c]

        bar_set = QBarSet("Temperature (C)")
        bar_set.append(values)
        series = QBarSeries()
        series.append(bar_set)
        self.chart.addSeries(series)

        axis_x = QBarCategoryAxis()
        axis_x.append(categories)
        axis_y = QValueAxis()
        axis_y.setTitleText("Degrees C")
        margin = 2.0
        axis_y.setRange(min(values) - margin, max(values) + margin)

        self.chart.addAxis(axis_x, Qt.AlignBottom)
        self.chart.addAxis(axis_y, Qt.AlignLeft)
        series.attachAxis(axis_x)
        series.attachAxis(axis_y)

        thi = result.comfort.thi
        thi_class = result.comfort.thi_class
        # Kept short deliberately -- QChart titles don't wrap, and this
        # widget is often shown at modest width. Threshold definitions
        # (comfort < 26, heat_stress <= 29) live in comfort_engine.py
        # and PROGRESS.md, not repeated here.
        self.chart.setTitle(
            f"THI={thi:.1f} ({thi_class})  |  Comfort Index={result.comfort.comfort_index:.0f}/100"
        )
