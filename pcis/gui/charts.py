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


def _theme_chart(chart) -> None:
    """Make a QChart follow the active PCIS theme.

    QChart paints its own opaque white plot area and near-black axis
    labels, neither of which comes from the widget stylesheet. On a dark
    theme that left a bright white rectangle in the middle of the window
    -- and simply making it transparent would have hidden the labels,
    since they would then be dark text on a dark surface. Both have to
    move together.
    """
    from PySide6.QtGui import QBrush, QColor, QPen

    from pcis.gui import style

    pal = style.active()
    ink = QColor(pal["INK"])
    muted = QColor(pal["INK_MUTED"])
    grid = QColor(pal["LINE"])

    chart.setBackgroundVisible(False)
    chart.setPlotAreaBackgroundVisible(False)
    chart.setTitleBrush(QBrush(ink))
    if chart.legend() is not None:
        chart.legend().setLabelBrush(QBrush(ink))
    for axis in chart.axes():
        axis.setLabelsBrush(QBrush(ink))
        axis.setTitleBrush(QBrush(muted))
        axis.setGridLinePen(QPen(grid))
        axis.setLinePen(QPen(grid))


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
        _theme_chart(self.chart)
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

    def set_recommendation(
        self, result: Recommendation, outdoor_t_c: float, unit_system=None
    ) -> None:
        """Plot the four temperatures.

        `unit_system` (a `pcis.gui.units.UnitSystem`) converts the
        displayed values. It defaults to None = metric so existing
        callers and tests are unaffected. Without this the chart kept
        showing Celsius while the rest of the window switched to
        Fahrenheit -- an inconsistency that is worse than having no
        chart, because both numbers look authoritative.
        """
        self.chart.removeAllSeries()
        for axis in list(self.chart.axes()):
            self.chart.removeAxis(axis)

        if unit_system is None:
            from pcis.gui import units as _u

            unit_system = _u.METRIC
        convert = unit_system.temp_from_si
        suffix = unit_system.temp_suffix.strip()

        categories = ["Outdoor", "Supply (post-pad)" if result.pads_on else "Supply", "Indoor", "Target"]
        values = [
            convert(v)
            for v in (
                outdoor_t_c,
                result.supply_air_t_c,
                result.comfort.t_c,
                result.comfort.target_temp_c,
            )
        ]

        bar_set = QBarSet(f"Temperature ({suffix})")
        bar_set.append(values)
        series = QBarSeries()
        series.append(bar_set)
        self.chart.addSeries(series)

        axis_x = QBarCategoryAxis()
        axis_x.append(categories)
        axis_y = QValueAxis()
        axis_y.setTitleText(suffix)
        # Zero baseline. A zoomed axis (e.g. 18.7-37.0) rendered the
        # 20.7 C target as a sliver beside a 35 C supply bar, implying
        # a ~20x difference where the real one is under 2x.
        #
        # Caveat worth knowing: temperature in C/F is an interval
        # scale, not a ratio one -- 40 C is not "twice as hot" as
        # 20 C -- so bar LENGTH here is not strictly meaningful either
        # way. Zero-baselined bars are the lesser distortion of the two
        # and the conventional reading, but the honest comparison is
        # the gap between bars, not their ratio.
        axis_y.setRange(0.0, max(values) * 1.15)

        self.chart.addAxis(axis_x, Qt.AlignBottom)
        self.chart.addAxis(axis_y, Qt.AlignLeft)
        series.attachAxis(axis_x)
        series.attachAxis(axis_y)

        _theme_chart(self.chart)

        thi = result.comfort.thi
        thi_class = result.comfort.thi_class
        # Kept short deliberately -- QChart titles don't wrap, and this
        # widget is often shown at modest width. Threshold definitions
        # (comfort < 26, heat_stress <= 29) live in comfort_engine.py
        # and PROGRESS.md, not repeated here.
        self.chart.setTitle(
            f"THI={thi:.1f} ({thi_class})  |  Comfort Index={result.comfort.comfort_index:.0f}/100"
        )


class ScheduleChartWidget(QWidget):
    """Fan count (bars) and outdoor temperature (line) across a
    simulated day, from `pcis.core.digital_twin.SimulationResult`.

    Plotting both together is the point of the chart: it makes the
    relationship between the weather and the staging visible at a
    glance, which a table of numbers does not. Steps where the target
    is physically unreachable are drawn in a distinct colour so a
    schedule that "looks fine" cannot hide them.

    Pure presentation -- every value plotted is read straight off the
    already-computed SimulationResult.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.chart = QChart()
        self.chart.setBackgroundVisible(False)
        self.chart.legend().setAlignment(Qt.AlignBottom)
        self.view = QChartView(self.chart)
        self.view.setRenderHint(QPainter.Antialiasing)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.view)
        self._result = None

    def set_schedule(self, result) -> None:
        """Plot a `SimulationResult`."""
        self._result = result
        self.chart.removeAllSeries()
        for axis in list(self.chart.axes()):
            self.chart.removeAxis(axis)

        labels = [s.label for s in result.steps]
        fans = [float(s.fans_on) for s in result.steps]
        temps = [s.outdoor_t_c for s in result.steps]
        unreachable = [s.fans_on if s.target_unreachable else 0.0 for s in result.steps]
        reachable = [0.0 if s.target_unreachable else s.fans_on for s in result.steps]

        ok_set = QBarSet("Fans (target reachable)")
        ok_set.append(reachable)
        ok_set.setColor(Qt.darkCyan)
        bad_set = QBarSet("Fans (target NOT reachable)")
        bad_set.append(unreachable)
        bad_set.setColor(Qt.red)

        bars = QBarSeries()
        bars.append(ok_set)
        bars.append(bad_set)
        self.chart.addSeries(bars)

        axis_x = QBarCategoryAxis()
        axis_x.append(labels)
        self.chart.addAxis(axis_x, Qt.AlignBottom)
        bars.attachAxis(axis_x)

        axis_fans = QValueAxis()
        axis_fans.setTitleText("Fans")
        axis_fans.setRange(0, max(fans + [1.0]) * 1.25)
        axis_fans.setLabelFormat("%d")
        self.chart.addAxis(axis_fans, Qt.AlignLeft)
        bars.attachAxis(axis_fans)

        temp_series = QLineSeries()
        temp_series.setName("Outdoor temperature")
        for i, t in enumerate(temps):
            temp_series.append(i, t)
        self.chart.addSeries(temp_series)
        axis_temp = QValueAxis()
        axis_temp.setTitleText("Outdoor °C")
        lo, hi = min(temps), max(temps)
        pad = max(1.0, (hi - lo) * 0.2)
        axis_temp.setRange(lo - pad, hi + pad)
        self.chart.addAxis(axis_temp, Qt.AlignRight)
        temp_series.attachAxis(axis_temp)
        # The line shares the bar chart's category positions, so it is
        # attached to a hidden value x-axis spanning the same indices.
        axis_x2 = QValueAxis()
        axis_x2.setRange(-0.5, len(labels) - 0.5)
        axis_x2.setVisible(False)
        self.chart.addAxis(axis_x2, Qt.AlignBottom)
        temp_series.attachAxis(axis_x2)

        peak = result.peak_fans_on
        unreachable_n = result.unreachable_steps
        title = f"Fan schedule — peak {peak} fan(s)"
        if unreachable_n:
            title += f" — target unreachable at {unreachable_n} of {len(labels)} steps"
        _theme_chart(self.chart)
        self.chart.setTitle(title)

    def fan_values(self) -> list[float]:
        """Fan counts currently plotted, for tests."""
        if self._result is None:
            return []
        return [float(s.fans_on) for s in self._result.steps]
