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
