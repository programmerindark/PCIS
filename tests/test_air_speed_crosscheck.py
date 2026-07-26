"""Measured air speed checks the engine's most load-bearing number.

Target air speed governs the majority of this farm's recommendations, and
until now it was purely computed: fan curve -> airflow -> continuity.
The WS90 array hangs inside the house, so its anemometer reads the air the
fans are actually moving, which makes that chain checkable.

PCIS reports both values and their gap. It deliberately does NOT let the
measurement overwrite the calculation: one anemometer samples a point, not
a cross-sectional average, and a house with a stalled fan should show a
disagreement rather than quietly redefine its own air speed as correct.
"""
from __future__ import annotations

import pytest

from backend.app.engine_api import _surfaces
from pcis.core import recommendation_engine as re
from pcis.equipment.fan_curve import FAN_CATALOG

MEASURED_PA = 94620.0
COMPUTED_MPS = 3.06   # 15 fans through 45 m2, from the fan curve at 30 Pa


def _rec(measured=None, cross_section=45.0):
    return re.recommend(
        bird_count=21940, body_weight_kg=2.496, indoor_t_c=21.0,
        indoor_rh_pct=96.0, outdoor_t_c=24.7, outdoor_rh_pct=99.0,
        envelope_surfaces=_surfaces(120.0, 15.0, 3.0, "insulated"),
        fan=FAN_CATALOG[0], design_static_pressure_pa=30.0, delta_t_c=3.0,
        cooling_pad=None, house_cross_section_m2=cross_section,
        heater_capacity_w=None, bird_age_days=37, pressure_pa=MEASURED_PA,
        measured_air_speed_mps=measured,
    )


def test_the_farms_actual_reading_agrees_with_the_calculation():
    """3.22 m/s measured vs 3.06 computed: the chain survives contact."""
    rec = _rec(3.22)
    assert rec.air_speed_agreement == "agree"
    assert abs(rec.air_speed_divergence_pct) < 10.0


def test_measurement_never_overwrites_the_calculation():
    with_meas = _rec(3.22)
    without = _rec(None)
    assert with_meas.air_speed_mps == without.air_speed_mps
    assert with_meas.measured_air_speed_mps == 3.22


def test_fan_count_is_unchanged_by_the_measurement():
    """A cross-check must not become a back-door control input."""
    assert _rec(3.22).fans_on == _rec(None).fans_on
    assert _rec(0.5).fans_on == _rec(None).fans_on


def test_a_stalled_fan_scenario_is_flagged_low():
    rec = _rec(1.5)
    assert rec.air_speed_agreement == "measured_lower"
    assert any("DISAGREEMENT" in e for e in rec.explanation)
    assert any("belt" in e or "shutters" in e for e in rec.explanation)


def test_a_narrowed_house_scenario_is_flagged_high():
    rec = _rec(5.5)
    assert rec.air_speed_agreement == "measured_higher"
    assert any("cross-section is" in e for e in rec.explanation)


def test_no_measurement_means_no_verdict_rather_than_a_false_pass():
    rec = _rec(None)
    assert rec.air_speed_agreement is None
    assert rec.air_speed_divergence_pct is None


def test_divergence_sign_is_measured_relative_to_computed():
    assert _rec(3.22).air_speed_divergence_pct > 0
    assert _rec(2.0).air_speed_divergence_pct < 0


@pytest.mark.parametrize("measured", [0.0, 15.0])
def test_extreme_readings_do_not_crash_the_engine(measured):
    assert _rec(measured).air_speed_agreement is not None


def test_no_cross_check_without_a_cross_section():
    """Without geometry there is no computed speed to compare against."""
    rec = _rec(3.22, cross_section=None)
    assert rec.air_speed_agreement is None
