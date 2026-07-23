"""Tests for the guided single-page schedule flow.

Split into two halves:

  * The pure logic in ``pcis.gui.guided_model`` -- no Qt at all, so it
    runs anywhere.
  * The widget ``pcis.gui.guided.GuidedScheduleWidget`` -- exercised
    headlessly via the offscreen Qt platform (see ``conftest.qapp``).
    Crucially this widget imports only ``QtWidgets``/``QtGui``, never
    ``QtCharts``, so these tests run without the (large) QtCharts add-on
    that ``test_gui``/``test_charts`` require.

Every number the flow shows comes from the already-tested engineering
core; these tests check that the flow *arranges and reports* those
numbers correctly, not the physics itself (covered by the core tests).
"""

from unittest.mock import patch

import pytest

from pcis.core import comfort_engine as ce
from pcis.core import digital_twin as twin
from pcis.core import growth_curve as gc
from pcis.core import heat_moisture_balance as hmb
from pcis.equipment.cooling_pad import COOLING_PAD_CATALOG
from pcis.equipment.fan_curve import FAN_CATALOG
from pcis.gui import guided_model as gm


# ----------------------------------------------------------------------
# guided_model -- pure logic
# ----------------------------------------------------------------------


def test_target_curve_spans_the_full_published_range():
    curve = gm.target_temperature_curve(60.0)
    assert curve[0].day == gc.ROSS_308_MIN_AGE_DAYS
    assert curve[-1].day == gc.ROSS_308_MAX_AGE_DAYS
    assert len(curve) == gc.ROSS_308_MAX_AGE_DAYS - gc.ROSS_308_MIN_AGE_DAYS + 1


def test_target_curve_matches_comfort_engine_point_for_point():
    # The curve must be exactly what comfort_engine yields for each day's
    # Aviagen weight -- no independent computation, no drift.
    for p in gm.target_temperature_curve(55.0):
        expected = ce.target_temperature(gc.ross_308_body_weight_kg(p.day), 55.0)
        assert p.target_temp_c == pytest.approx(expected)
        assert p.body_weight_kg == pytest.approx(gc.ross_308_body_weight_kg(p.day))


def test_target_curve_falls_as_birds_grow():
    # Chicks need it hot; grown birds need it cooler. The curve should be
    # (weakly) monotonically decreasing across the grow-out.
    temps = [p.target_temp_c for p in gm.target_temperature_curve(60.0)]
    assert all(b <= a + 1e-9 for a, b in zip(temps, temps[1:]))
    assert temps[0] > temps[-1]


def test_target_curve_can_be_restricted_and_never_extrapolates():
    curve = gm.target_temperature_curve(60.0, day_min=10, day_max=20)
    assert curve[0].day == 10 and curve[-1].day == 20
    # Asking beyond the table is clamped to it, not extrapolated.
    full = gm.target_temperature_curve(60.0, day_min=-5, day_max=999)
    assert full[0].day == gc.ROSS_308_MIN_AGE_DAYS
    assert full[-1].day == gc.ROSS_308_MAX_AGE_DAYS


def test_rh_clamp_flag_tracks_comfort_engine():
    assert gm.target_rh_is_clamped(85.0) is True
    assert gm.target_rh_is_clamped(60.0) is False


def _sample_result(**overrides):
    surfaces = [hmb.Surface("sidewalls", 0.6, 350.0), hmb.Surface("ceiling", 0.4, 1500.0)]
    conds = [
        twin.OutdoorCondition("00:00", 24.0, 80.0),
        twin.OutdoorCondition("06:00", 21.0, 85.0),
        twin.OutdoorCondition("12:00", 34.0, 45.0),
        twin.OutdoorCondition("18:00", 34.0, 45.0),
    ]
    kwargs = dict(
        conditions=conds, age_days=35, bird_count=20000,
        envelope_surfaces=surfaces, fan=FAN_CATALOG[0],
        design_static_pressure_pa=30.0, delta_t_c=3.0, indoor_rh_pct=60.0,
        cooling_pad=COOLING_PAD_CATALOG[0], installed_fan_count=8,
    )
    kwargs.update(overrides)
    return twin.simulate_schedule(**kwargs)


def test_summarize_reports_peak_and_fan_hours():
    result = _sample_result()
    summ = gm.summarize(result, step_duration_h=6.0)
    assert summ.peak_fans_on == result.peak_fans_on
    assert summ.n_steps == len(result.steps)
    assert summ.total_hours == pytest.approx(len(result.steps) * 6.0)
    assert summ.fan_hours == pytest.approx(result.fan_hours(6.0))


def test_summarize_flags_fan_shortfall():
    result = _sample_result(installed_fan_count=1)
    summ = gm.summarize(result, step_duration_h=6.0)
    assert summ.fans_undersized is True


def test_describe_block_is_readable_and_uses_duration():
    result = _sample_result()
    line = gm.describe_block(result.blocks[0], step_duration_h=6.0)
    assert "fan" in line and ("heat" in line) and ("pads" in line)
    # A single-step block reports one label; a multi-step block a range.
    multi = next((b for b in result.blocks if b.n_steps > 1), None)
    if multi is not None:
        assert "–" in gm.describe_block(multi, 6.0)


# ----------------------------------------------------------------------
# GuidedScheduleWidget -- headless (no QtCharts)
# ----------------------------------------------------------------------


@pytest.fixture()
def guided(qapp):
    from pcis.gui.guided import GuidedScheduleWidget

    return GuidedScheduleWidget()


def test_widget_seeds_a_default_weather_profile(guided):
    assert guided.profile_table.rowCount() > 0


def test_build_produces_result_and_populates_blocks(guided):
    result = guided.build_schedule()
    assert result is not None
    assert len(result.steps) == guided.profile_table.rowCount()
    assert guided.blocks_list.count() == len(result.blocks)
    assert not guided.blocks_list.isHidden()
    assert not guided.summary_label.isHidden()


def test_blocks_hidden_until_built(guided):
    assert guided.blocks_list.isHidden()
    assert not guided.empty_label.isHidden()
    guided.build_schedule()
    assert not guided.blocks_list.isHidden()


def test_empty_profile_warns_and_returns_none(guided):
    guided.profile_table.setRowCount(0)
    with patch("pcis.gui.guided.QMessageBox.warning", return_value=None) as warn:
        assert guided.build_schedule() is None
    warn.assert_called_once()


def test_bad_cell_warns_and_returns_none(guided):
    guided.profile_table.item(0, 1).setText("not a number")
    with patch("pcis.gui.guided.QMessageBox.warning", return_value=None) as warn:
        assert guided.build_schedule() is None
    warn.assert_called_once()


def test_unit_switch_preserves_si_readings(guided):
    from pcis.gui import units

    # 24 degC seeded in row 0 must still read 24 degC after switching the
    # display to imperial and back to metric (conversion, not reinterpret).
    guided.set_unit_system(units.IMPERIAL)
    guided.set_unit_system(units.METRIC)
    result = guided.build_schedule()
    assert result.steps[0].outdoor_t_c == pytest.approx(24.0, abs=0.05)


def test_age_change_autofills_body_weight_from_growth_curve(guided):
    guided.age_spin.setValue(21)
    assert guided.body_weight_spin.si_value() == pytest.approx(
        gc.ross_308_body_weight_kg(21), abs=1e-6
    )


def test_target_chart_marker_follows_age(guided):
    guided.age_spin.setValue(28)
    assert guided.target_chart._marker_day == 28
    assert len(guided.target_chart._points) > 0


def test_installed_fan_shortfall_surfaces_in_notes(guided):
    guided.installed_fans_spin.setValue(1)
    guided.build_schedule()
    assert "WARNING" in guided.notes_label.text()


def test_gather_returns_si_values(guided):
    inputs = guided.gather()
    assert inputs["bird_count"] == guided.bird_count_spin.value()
    assert inputs["indoor_rh_pct"] == guided.indoor_rh_spin.value()
    assert inputs["surfaces"]  # non-empty envelope seeded
