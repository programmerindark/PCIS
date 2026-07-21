"""Unit tests for pcis.core.recommendation_engine."""

import pytest

from pcis.core import heat_moisture_balance as hmb
from pcis.core import recommendation_engine as re
from pcis.equipment.cooling_pad import CELDEK_7090_15_150MM
from pcis.equipment.fan_curve import FAN_CATALOG

SURFACES = [
    hmb.Surface("sidewalls", u_value=0.6, area_m2=350.0),
    hmb.Surface("ceiling", u_value=0.4, area_m2=1500.0),
]
FAN = FAN_CATALOG[1]  # V130-3-1.5 PS


def test_hot_day_recommends_pads_on():
    result = re.recommend(
        bird_count=20000,
        body_weight_kg=2.5,
        indoor_t_c=29.0,
        indoor_rh_pct=60.0,
        outdoor_t_c=38.0,
        outdoor_rh_pct=30.0,
        envelope_surfaces=SURFACES,
        fan=FAN,
        design_static_pressure_pa=30.0,
        delta_t_c=3.0,
        cooling_pad=CELDEK_7090_15_150MM,
    )
    assert result.pads_on is True
    assert result.fans_on > 0
    assert result.supply_air_t_c < 38.0  # pad cooled the supply air
    assert 0.0 <= result.confidence_score <= 100.0
    assert any("pad" in line.lower() for line in result.explanation)


# ---------------------------------------------------------------------------
# Physically-unreachable target
#
# Ventilation moves the house toward the supply-air state; it can never
# cool below it. When supply air is already at/above target, the fan
# count is still a number but it no longer means "this achieves target",
# and the engine must say so -- this is the single most misleading thing
# the app could otherwise report.
# ---------------------------------------------------------------------------


def test_extreme_heat_flags_target_as_unreachable():
    result = re.recommend(
        bird_count=20000,
        body_weight_kg=2.5,
        indoor_t_c=29.0,
        indoor_rh_pct=60.0,
        outdoor_t_c=45.0,
        outdoor_rh_pct=40.0,
        envelope_surfaces=SURFACES,
        fan=FAN,
        design_static_pressure_pa=30.0,
        delta_t_c=3.0,
        cooling_pad=CELDEK_7090_15_150MM,
    )
    assert result.target_unreachable is True
    assert result.supply_air_t_c >= result.comfort.target_temp_c
    warning = next(line for line in result.explanation if "TARGET NOT REACHABLE" in line)
    # It must tell the operator what will NOT help, not just that
    # something is wrong.
    assert "More fans will not do it." in warning


def test_cool_day_target_is_reachable():
    result = re.recommend(
        bird_count=20000,
        body_weight_kg=2.5,
        indoor_t_c=20.0,
        indoor_rh_pct=60.0,
        outdoor_t_c=5.0,
        outdoor_rh_pct=70.0,
        envelope_surfaces=SURFACES,
        fan=FAN,
        design_static_pressure_pa=30.0,
        delta_t_c=3.0,
    )
    assert result.target_unreachable is False
    assert not any("TARGET NOT REACHABLE" in line for line in result.explanation)


def test_unreachable_flag_does_not_change_the_confidence_score():
    # Unreachability is a physical certainty, not an uncertainty in the
    # inputs -- folding it into the confidence score would make the app
    # look LESS sure exactly when it is MOST sure something is wrong.
    # See the Recommendation docstring.
    common = dict(
        bird_count=20000,
        body_weight_kg=2.5,
        indoor_rh_pct=60.0,
        envelope_surfaces=SURFACES,
        fan=FAN,
        design_static_pressure_pa=30.0,
        delta_t_c=3.0,
        outdoor_co2_ppm=500.0,  # non-default, so no CO2 deduction either way
    )
    reachable = re.recommend(indoor_t_c=20.0, outdoor_t_c=5.0, outdoor_rh_pct=70.0, **common)
    unreachable = re.recommend(indoor_t_c=29.0, outdoor_t_c=45.0, outdoor_rh_pct=40.0, **common)

    assert reachable.target_unreachable is False
    assert unreachable.target_unreachable is True
    # Neither run uses pads, so the only deduction in play is the shared
    # composite-comfort-index one -- the scores should match exactly.
    assert unreachable.confidence_score == pytest.approx(reachable.confidence_score)


def test_pads_reduce_but_may_not_eliminate_the_unreachable_gap():
    # Same brutal conditions with and without a pad: the pad must lower
    # the supply-air temperature (narrowing the gap) even if it cannot
    # close it entirely.
    common = dict(
        bird_count=20000,
        body_weight_kg=2.5,
        indoor_t_c=29.0,
        indoor_rh_pct=60.0,
        outdoor_t_c=45.0,
        outdoor_rh_pct=40.0,
        envelope_surfaces=SURFACES,
        fan=FAN,
        design_static_pressure_pa=30.0,
        delta_t_c=3.0,
    )
    without = re.recommend(**common)
    with_pad = re.recommend(cooling_pad=CELDEK_7090_15_150MM, **common)

    assert with_pad.supply_air_t_c < without.supply_air_t_c
    assert without.target_unreachable is True


def test_mild_day_does_not_recommend_pads():
    result = re.recommend(
        bird_count=20000,
        body_weight_kg=2.5,
        indoor_t_c=18.0,
        indoor_rh_pct=60.0,
        outdoor_t_c=15.0,
        outdoor_rh_pct=55.0,
        envelope_surfaces=SURFACES,
        fan=FAN,
        design_static_pressure_pa=30.0,
        delta_t_c=3.0,
        cooling_pad=CELDEK_7090_15_150MM,
    )
    assert result.pads_on is False
    assert result.supply_air_t_c == pytest.approx(15.0)


def test_no_cooling_pad_supplied_never_activates_pads():
    result = re.recommend(
        bird_count=20000,
        body_weight_kg=2.5,
        indoor_t_c=29.0,
        indoor_rh_pct=60.0,
        outdoor_t_c=40.0,
        outdoor_rh_pct=25.0,
        envelope_surfaces=SURFACES,
        fan=FAN,
        design_static_pressure_pa=30.0,
        delta_t_c=3.0,
        cooling_pad=None,
    )
    assert result.pads_on is False
    assert any("no cooling pad supplied" in line for line in result.explanation)


def test_governing_constraint_is_a_known_category():
    result = re.recommend(
        bird_count=20000,
        body_weight_kg=2.5,
        indoor_t_c=29.0,
        indoor_rh_pct=60.0,
        outdoor_t_c=38.0,
        outdoor_rh_pct=30.0,
        envelope_surfaces=SURFACES,
        fan=FAN,
        design_static_pressure_pa=30.0,
        delta_t_c=3.0,
        cooling_pad=CELDEK_7090_15_150MM,
    )
    assert result.governing_constraint in {"sensible_heat", "moisture", "co2", "minimum_ventilation"}


def test_confidence_score_deducted_for_pad_and_composite_index():
    result = re.recommend(
        bird_count=20000,
        body_weight_kg=2.5,
        indoor_t_c=29.0,
        indoor_rh_pct=60.0,
        outdoor_t_c=38.0,
        outdoor_rh_pct=30.0,
        envelope_surfaces=SURFACES,
        fan=FAN,
        design_static_pressure_pa=30.0,
        delta_t_c=3.0,
        cooling_pad=CELDEK_7090_15_150MM,
    )
    # 100 - 15 (pad) - 10 (default CO2 outdoor ppm) - 5 (composite index) = 70
    assert result.confidence_score == pytest.approx(70.0)


def test_confidence_score_higher_without_pads():
    result = re.recommend(
        bird_count=20000,
        body_weight_kg=2.5,
        indoor_t_c=18.0,
        indoor_rh_pct=60.0,
        outdoor_t_c=15.0,
        outdoor_rh_pct=55.0,
        envelope_surfaces=SURFACES,
        fan=FAN,
        design_static_pressure_pa=30.0,
        delta_t_c=3.0,
        cooling_pad=CELDEK_7090_15_150MM,
    )
    # 100 - 10 (default CO2 outdoor ppm) - 5 (composite index) = 85
    assert result.confidence_score == pytest.approx(85.0)


def test_custom_outdoor_co2_avoids_default_deduction():
    result = re.recommend(
        bird_count=20000,
        body_weight_kg=2.5,
        indoor_t_c=18.0,
        indoor_rh_pct=60.0,
        outdoor_t_c=15.0,
        outdoor_rh_pct=55.0,
        envelope_surfaces=SURFACES,
        fan=FAN,
        design_static_pressure_pa=30.0,
        delta_t_c=3.0,
        cooling_pad=CELDEK_7090_15_150MM,
        outdoor_co2_ppm=410.0,
    )
    # 100 - 5 (composite index only)
    assert result.confidence_score == pytest.approx(95.0)


def test_high_indoor_humidity_does_not_crash_and_flags_confidence():
    # Real farm indoor RH can exceed the Aviagen table's 70% tested
    # max (e.g. 80% in humid weather) -- this used to raise a
    # ValueError and crash the whole recommendation. It should now
    # produce a result with a flagged confidence deduction instead.
    result = re.recommend(
        bird_count=20000,
        body_weight_kg=2.5,
        indoor_t_c=18.0,
        indoor_rh_pct=80.0,
        outdoor_t_c=15.0,
        outdoor_rh_pct=70.0,
        envelope_surfaces=SURFACES,
        fan=FAN,
        design_static_pressure_pa=30.0,
        delta_t_c=3.0,
        cooling_pad=CELDEK_7090_15_150MM,
        outdoor_co2_ppm=410.0,
    )
    assert result.pads_on is False  # mild outdoor temp -- isolates the RH deduction
    assert result.comfort.target_temp_rh_clamped is True
    # 100 - 5 (composite index) - 10 (RH outside table range) = 85
    assert result.confidence_score == pytest.approx(85.0)
    assert any("outside the Aviagen target-temperature table" in line for line in result.explanation)


def test_indoor_humidity_within_table_range_has_no_rh_deduction():
    result = re.recommend(
        bird_count=20000,
        body_weight_kg=2.5,
        indoor_t_c=18.0,
        indoor_rh_pct=60.0,
        outdoor_t_c=15.0,
        outdoor_rh_pct=55.0,
        envelope_surfaces=SURFACES,
        fan=FAN,
        design_static_pressure_pa=30.0,
        delta_t_c=3.0,
        cooling_pad=CELDEK_7090_15_150MM,
        outdoor_co2_ppm=410.0,
    )
    assert result.comfort.target_temp_rh_clamped is False
    assert not any("outside the Aviagen target-temperature table" in line for line in result.explanation)


def test_explanation_is_nonempty_and_readable():
    result = re.recommend(
        bird_count=20000,
        body_weight_kg=2.5,
        indoor_t_c=29.0,
        indoor_rh_pct=60.0,
        outdoor_t_c=38.0,
        outdoor_rh_pct=30.0,
        envelope_surfaces=SURFACES,
        fan=FAN,
        design_static_pressure_pa=30.0,
        delta_t_c=3.0,
        cooling_pad=CELDEK_7090_15_150MM,
    )
    assert len(result.explanation) >= 5
    assert all(isinstance(line, str) and line for line in result.explanation)
