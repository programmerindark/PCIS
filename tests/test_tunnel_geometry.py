"""Tests for tunnel geometry (ceiling height / cross-section) and the
predicted indoor humidity from the moisture balance."""

import pytest

from pcis.core import house_metrics as hmet
from pcis.core import psychrometrics as psy
from pcis.core import target_airspeed as tas
from pcis.core import tunnel_geometry as tg


# ----------------------------------------------------------------------
# Continuity: A = Q / V
# ----------------------------------------------------------------------

def test_cross_section_inverts_the_velocity_equation():
    q = 331_000.0  # 10 fans @ 30 Pa
    area = tg.cross_section_for_velocity(q, 3.0)
    assert area == pytest.approx((q / 3600.0) / 3.0)
    # round-trip
    assert tg.velocity_at(q, area) == pytest.approx(3.0)


def test_smaller_cross_section_gives_higher_velocity():
    q = 331_000.0
    assert tg.velocity_at(q, 23.0) > tg.velocity_at(q, 45.0)


def test_rejects_nonsense_inputs():
    with pytest.raises(ValueError):
        tg.cross_section_for_velocity(0.0, 3.0)
    with pytest.raises(ValueError):
        tg.cross_section_for_velocity(331_000.0, 0.0)
    with pytest.raises(ValueError):
        tg.velocity_at(331_000.0, 0.0)


# ----------------------------------------------------------------------
# Ceiling-height table
# ----------------------------------------------------------------------

def test_velocity_table_flags_the_cited_thresholds():
    q = 331_000.0
    rows = tg.velocity_table(q, house_width_m=15.0, heights_m=[3.0, 2.5, 2.0, 1.6])
    assert [r.ceiling_height_m for r in rows] == [3.0, 2.5, 2.0, 1.6]
    # velocity must rise as the ceiling drops
    vs = [r.velocity_mps for r in rows]
    assert vs == sorted(vs)
    # 3.0 m is too big a profile for 10 fans; 2.0 m reaches the Cobb target
    assert rows[0].meets_tunnel_target is False
    assert rows[2].meets_tunnel_target is True
    # thresholds agree with the cited constants
    for r in rows:
        assert r.meets_tunnel_target == (r.velocity_mps >= tas.TUNNEL_TARGET_AIRSPEED_MPS)
        assert r.windchill_effective == (r.velocity_mps >= tas.EFFECTIVE_WINDCHILL_THRESHOLD_MPS)


def test_velocity_table_reports_ft_per_min():
    rows = tg.velocity_table(331_000.0, 15.0, [2.0])
    assert rows[0].velocity_fpm == pytest.approx(rows[0].velocity_mps * 196.85, abs=1)


# ----------------------------------------------------------------------
# Advice: drop the ceiling vs add fans
# ----------------------------------------------------------------------

def test_advice_recommends_a_ceiling_drop_when_short():
    a = tg.advise_geometry(
        airflow_m3_per_h=331_000.0, house_width_m=15.0,
        current_cross_section_m2=45.0, airflow_per_fan_m3_per_h=33_100.0,
        installed_fans=10,
    )
    assert a.meets_target is False
    assert a.current_velocity_mps == pytest.approx(2.04, abs=0.02)
    assert a.required_ceiling_height_m == pytest.approx(2.04, abs=0.05)
    assert a.ceiling_drop_m > 0
    assert a.fans_needed_instead > 10          # the expensive alternative
    assert "static pressure" in a.note         # honest caveat present


def test_advice_says_nothing_needed_when_already_fast_enough():
    a = tg.advise_geometry(
        airflow_m3_per_h=331_000.0, house_width_m=15.0,
        current_cross_section_m2=23.23,
    )
    assert a.meets_target is True
    assert "No geometry change needed" in a.note


def test_both_routes_reach_the_same_velocity():
    """Dropping the ceiling and adding fans are equivalent physics."""
    q, width, area, per_fan = 331_000.0, 15.0, 45.0, 33_100.0
    a = tg.advise_geometry(airflow_m3_per_h=q, house_width_m=width,
                           current_cross_section_m2=area,
                           airflow_per_fan_m3_per_h=per_fan, installed_fans=10)
    # route 1: smaller area, same airflow
    assert tg.velocity_at(q, a.required_cross_section_m2) == pytest.approx(3.0, abs=0.02)
    # route 2: same area, more airflow
    assert tg.velocity_at(a.fans_needed_instead * per_fan, area) >= 3.0


# ----------------------------------------------------------------------
# Predicted indoor humidity
# ----------------------------------------------------------------------

def test_predicted_indoor_rh_exceeds_supply_rh():
    """Birds add moisture, so indoor is always more humid than inlet."""
    p = hmet.predict_indoor_humidity(
        indoor_t_c=27.0, supply_t_c=27.0, supply_rh_pct=74.0,
        moisture_load_kg_per_h=384.0, airflow_m3_per_h=331_000.0,
    )
    assert p is not None
    assert p.indoor_rh_pct > 74.0
    assert p.indoor_humidity_ratio_g_per_kg > p.supply_humidity_ratio_g_per_kg
    assert p.moisture_added_g_per_kg > 0


def test_more_ventilation_lowers_predicted_humidity():
    def rh(airflow):
        return hmet.predict_indoor_humidity(
            indoor_t_c=27.0, supply_t_c=27.0, supply_rh_pct=74.0,
            moisture_load_kg_per_h=384.0, airflow_m3_per_h=airflow,
        ).indoor_rh_pct
    assert rh(130_000) > rh(330_000) >= rh(500_000)


def test_matches_the_hand_calculation():
    supply_t, supply_rh, load, q = 27.0, 74.0, 384.0, 331_000.0
    w_sup = psy.humidity_ratio_from_relative_humidity(supply_t, supply_rh)
    m_da = q / psy.specific_volume(supply_t, w_sup)
    expected_w = w_sup + load / m_da
    p = hmet.predict_indoor_humidity(
        indoor_t_c=27.0, supply_t_c=supply_t, supply_rh_pct=supply_rh,
        moisture_load_kg_per_h=load, airflow_m3_per_h=q,
    )
    assert p.indoor_humidity_ratio_g_per_kg == pytest.approx(expected_w * 1000, abs=0.02)


def test_saturation_is_flagged_not_reported_above_100():
    p = hmet.predict_indoor_humidity(
        indoor_t_c=20.0, supply_t_c=19.0, supply_rh_pct=95.0,
        moisture_load_kg_per_h=500.0, airflow_m3_per_h=40_000.0,
    )
    assert p.saturated is True
    assert p.indoor_rh_pct == 100.0
    assert "condensation" in p.note


def test_zero_airflow_returns_none():
    assert hmet.predict_indoor_humidity(
        indoor_t_c=27.0, supply_t_c=27.0, supply_rh_pct=74.0,
        moisture_load_kg_per_h=384.0, airflow_m3_per_h=0.0,
    ) is None
