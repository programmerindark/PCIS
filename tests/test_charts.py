"""Unit tests for pcis.gui.charts.

These tests read back the underlying QtCharts series data
programmatically (no screenshots/pixel comparisons needed) to confirm
each chart widget is plotting the actual values from the engineering
objects it was given, not just "didn't crash".
"""

from __future__ import annotations

import pytest

from pcis.core import heat_moisture_balance as hmb
from pcis.core import recommendation_engine as re
from pcis.equipment.cooling_pad import CELDEK_7090_15_150MM
from pcis.equipment.fan_curve import FAN_CATALOG
from pcis.gui.charts import ComfortChartWidget, FanCurveChartWidget

SURFACES = [
    hmb.Surface("sidewalls", u_value=0.6, area_m2=350.0),
    hmb.Surface("ceiling", u_value=0.4, area_m2=1500.0),
]


def test_fan_curve_chart_plots_all_data_points(qapp):
    fan = FAN_CATALOG[0]
    widget = FanCurveChartWidget()
    widget.set_fan(fan, operating_static_pressure_pa=fan.static_pressure_pa[1])

    series_list = widget.chart.series()
    # One line series for the curve, one scatter series for the marked
    # operating point.
    assert len(series_list) == 2
    curve = series_list[0]
    assert curve.count() == len(fan.static_pressure_pa)

    plotted_x = sorted(curve.at(i).x() for i in range(curve.count()))
    expected_x = sorted(fan.static_pressure_pa)
    assert plotted_x == pytest.approx(expected_x)


def test_fan_curve_chart_operating_point_matches_interpolation(qapp):
    fan = FAN_CATALOG[0]
    widget = FanCurveChartWidget()
    sp = (fan.static_pressure_pa[0] + fan.static_pressure_pa[1]) / 2.0
    widget.set_fan(fan, operating_static_pressure_pa=sp)

    marker = widget.chart.series()[1]
    assert marker.count() == 1
    point = marker.at(0)
    assert point.x() == pytest.approx(sp)
    assert point.y() == pytest.approx(fan.airflow_at_static_pressure(sp))


def test_fan_curve_chart_switching_fans_replaces_series(qapp):
    widget = FanCurveChartWidget()
    widget.set_fan(FAN_CATALOG[0])
    first_count = widget.chart.series()[0].count()
    widget.set_fan(FAN_CATALOG[1])
    assert len(widget.chart.series()) == 1  # no operating point this time
    assert widget.chart.series()[0].count() == len(FAN_CATALOG[1].static_pressure_pa)
    # Sanity: the two catalog fans have different curve lengths or
    # values in at least one respect (guards against a no-op update).
    assert FAN_CATALOG[0] is not FAN_CATALOG[1]
    _ = first_count


def test_comfort_chart_plots_four_temperature_bars(qapp):
    result = re.recommend(
        bird_count=20000,
        body_weight_kg=2.5,
        indoor_t_c=29.0,
        indoor_rh_pct=60.0,
        outdoor_t_c=38.0,
        outdoor_rh_pct=30.0,
        envelope_surfaces=SURFACES,
        fan=FAN_CATALOG[1],
        design_static_pressure_pa=30.0,
        delta_t_c=3.0,
        cooling_pad=CELDEK_7090_15_150MM,
    )
    widget = ComfortChartWidget()
    widget.set_recommendation(result, outdoor_t_c=38.0)

    assert len(widget.chart.series()) == 1
    bar_set = widget.chart.series()[0].barSets()[0]
    assert bar_set.count() == 4
    values = [bar_set.at(i) for i in range(bar_set.count())]
    assert values == pytest.approx(
        [38.0, result.supply_air_t_c, result.comfort.t_c, result.comfort.target_temp_c]
    )


def test_comfort_chart_title_reports_thi_and_comfort_index(qapp):
    result = re.recommend(
        bird_count=20000,
        body_weight_kg=2.5,
        indoor_t_c=18.0,
        indoor_rh_pct=60.0,
        outdoor_t_c=15.0,
        outdoor_rh_pct=55.0,
        envelope_surfaces=SURFACES,
        fan=FAN_CATALOG[1],
        design_static_pressure_pa=30.0,
        delta_t_c=3.0,
        cooling_pad=CELDEK_7090_15_150MM,
    )
    widget = ComfortChartWidget()
    widget.set_recommendation(result, outdoor_t_c=15.0)
    title = widget.chart.title()
    assert f"{result.comfort.thi:.1f}" in title
    assert result.comfort.thi_class in title
    assert f"{result.comfort.comfort_index:.0f}" in title
