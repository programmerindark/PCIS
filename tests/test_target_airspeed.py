"""Tests for the cited target tunnel air-velocity module and its use as
a governing constraint in the recommendation engine.

Pure logic -- no Qt. Verifies the cited regime switches (young-chick
ceiling, feathered-and-hot tunnel target, high-RH note) and that the
engine actually sizes fans to the target velocity when it governs.
"""

import pytest

from pcis.core import heat_moisture_balance as hmb
from pcis.core import recommendation_engine as re
from pcis.core import target_airspeed as tas
from pcis.equipment.fan_curve import FAN_CATALOG


# ----------------------------------------------------------------------
# target_airspeed -- regimes
# ----------------------------------------------------------------------


def test_young_chicks_get_a_ceiling_not_a_target():
    ta = tas.recommended_airspeed(body_weight_kg=0.3, air_temp_c=32.0,
                                  target_temp_c=33.0, indoor_rh_pct=60.0)
    assert ta.target_mps == 0.0
    assert ta.ceiling_mps == tas.YOUNG_CHICK_MAX_AIRSPEED_MPS == 0.15
    assert ta.windchill_effective is False
    assert "0.15" in ta.reason


def test_feathered_but_cool_needs_no_velocity_target():
    ta = tas.recommended_airspeed(body_weight_kg=2.3, air_temp_c=18.0,
                                  target_temp_c=21.0, indoor_rh_pct=60.0)
    assert ta.target_mps == 0.0
    assert ta.ceiling_mps is None


def test_feathered_and_hot_targets_cobb_tunnel_velocity():
    ta = tas.recommended_airspeed(body_weight_kg=2.3, air_temp_c=33.0,
                                  target_temp_c=21.0, indoor_rh_pct=55.0)
    assert ta.target_mps == tas.TUNNEL_TARGET_AIRSPEED_MPS == 3.0
    assert ta.windchill_effective is True
    assert "600 ft/min" in ta.reason


def test_high_humidity_flags_velocity_as_the_cooling_lever():
    ta = tas.recommended_airspeed(body_weight_kg=2.3, air_temp_c=33.0,
                                  target_temp_c=21.0, indoor_rh_pct=85.0)
    assert ta.target_mps == 3.0
    assert "70%" in ta.reason  # cites the Cobb high-RH rule


def test_required_airflow_matches_continuity():
    # Q = V * A, in m^3/h.  3.0 m/s * 25 m^2 * 3600 = 270,000.
    assert tas.required_airflow_for_airspeed(3.0, 25.0) == pytest.approx(270_000.0)
    assert tas.required_airflow_for_airspeed(0.0, 25.0) == 0.0
    assert tas.required_airflow_for_airspeed(3.0, 0.0) == 0.0


# ----------------------------------------------------------------------
# Engine integration
# ----------------------------------------------------------------------


def _surfaces():
    return [hmb.Surface("sidewalls", 0.41, 350.0), hmb.Surface("ceiling", 0.26, 1500.0)]


def test_airspeed_governs_for_grown_birds_in_heat():
    r = re.recommend(
        bird_count=20000, body_weight_kg=2.3, indoor_t_c=29.0, indoor_rh_pct=60.0,
        outdoor_t_c=37.0, outdoor_rh_pct=45.0, envelope_surfaces=_surfaces(),
        fan=FAN_CATALOG[0], design_static_pressure_pa=40.0, delta_t_c=3.0,
        cooling_pad=None, house_cross_section_m2=25.0,
    )
    assert r.governing_constraint == "target_airspeed"
    assert r.target_airspeed_mps == 3.0
    # Fans are staged so the delivered velocity meets or beats the target.
    assert r.air_speed_mps >= 3.0


def test_airspeed_target_absent_without_cross_section():
    # No cross-section supplied -> no velocity constraint can be formed.
    r = re.recommend(
        bird_count=20000, body_weight_kg=2.3, indoor_t_c=29.0, indoor_rh_pct=60.0,
        outdoor_t_c=37.0, outdoor_rh_pct=45.0, envelope_surfaces=_surfaces(),
        fan=FAN_CATALOG[0], design_static_pressure_pa=40.0, delta_t_c=3.0,
        cooling_pad=None, house_cross_section_m2=None,
    )
    assert r.governing_constraint != "target_airspeed"
    assert r.target_airspeed_mps is None


def test_young_birds_never_get_a_velocity_target_even_in_heat():
    r = re.recommend(
        bird_count=20000, body_weight_kg=0.3, indoor_t_c=32.0, indoor_rh_pct=60.0,
        outdoor_t_c=34.0, outdoor_rh_pct=45.0, envelope_surfaces=_surfaces(),
        fan=FAN_CATALOG[0], design_static_pressure_pa=40.0, delta_t_c=3.0,
        cooling_pad=None, house_cross_section_m2=25.0,
    )
    assert r.target_airspeed_mps is None
    assert r.governing_constraint != "target_airspeed"
