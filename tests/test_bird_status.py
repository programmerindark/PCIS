"""Tests for the bird-status dashboard (comfort, heat-stress risk,
panting and water estimates).

Pure logic -- no Qt. The physics/comfort come from already-tested
modules; these tests check the labelling, the cited thresholds, and the
honest is_estimate flags.
"""

import pytest

from pcis.core import bird_status as bs
from pcis.core import comfort_engine as ce
from pcis.core import psychrometrics as psy


def _comfort(t_c, rh_pct, weight):
    w = psy.humidity_ratio_from_relative_humidity(t_c, rh_pct)
    twb = psy.wet_bulb_temperature(t_c, w)
    return ce.bird_comfort_index(t_c, twb, rh_pct, weight)


def test_comfort_label_bands():
    assert bs._comfort_label(95.0) == "Good"
    assert bs._comfort_label(70.0) == "Fair"
    assert bs._comfort_label(40.0) == "Poor"


def test_heat_risk_relabels_the_cited_thi_class():
    # A comfortable state -> Low risk; a hot state -> higher risk.
    cool = _comfort(24.0, 55.0, 2.3)
    hot = _comfort(38.0, 55.0, 2.3)
    assert bs.assess(cool, 24.0, None).heat_stress_risk == "Low"
    assert bs.assess(hot, 38.0, None).heat_stress_risk in ("Moderate", "High")


def test_panting_index_tracks_cited_30c_onset():
    assert bs._panting_index(24.0) == "Minimal"
    assert bs._panting_index(28.5) == "Mild"
    assert bs._panting_index(31.0) == "Moderate"
    assert bs._panting_index(35.0) == "Severe"


def test_panting_uses_felt_temperature_when_available():
    # Same dry-bulb, but air movement lowers the felt temp below onset,
    # so the panting estimate should ease.
    comfort = _comfort(32.0, 55.0, 2.3)
    hot_still = bs.assess(comfort, 32.0, effective_temp_c=32.0)
    hot_moving = bs.assess(comfort, 32.0, effective_temp_c=26.0)
    assert hot_still.panting_index in ("Moderate", "Severe")
    assert hot_moving.panting_index in ("Minimal", "Mild")


def test_water_multiplier_matches_cited_relationship():
    # 1.0x at/below 70 F (21.1 C); rises ~6.5%/F above it; capped at 4x.
    assert bs.water_intake_multiplier(21.0) == pytest.approx(1.0)
    # 95 F = 35 C -> 1 + 0.065*(95-70) = 2.625x
    assert bs.water_intake_multiplier(35.0) == pytest.approx(2.625, abs=0.02)
    assert bs.water_intake_multiplier(60.0) == bs.WATER_MAX_MULTIPLIER  # capped


def test_from_recommendation_evaluates_at_realistic_temp_not_target():
    # Hot, unreachable day with grown birds: the engine's comfort is at
    # the (optimistic) target, but from_recommendation must re-evaluate
    # at the realistic temperature the house can actually hold and report
    # real heat stress.
    from pcis.core import recommendation_engine as re
    from pcis.core import heat_moisture_balance as hmb
    from pcis.equipment.fan_curve import FAN_CATALOG

    surfaces = [hmb.Surface("w", 0.41, 350.0), hmb.Surface("c", 0.26, 1500.0)]
    rec = re.recommend(
        bird_count=20000, body_weight_kg=2.3, indoor_t_c=21.0, indoor_rh_pct=60.0,
        outdoor_t_c=38.0, outdoor_rh_pct=45.0, envelope_surfaces=surfaces,
        fan=FAN_CATALOG[0], design_static_pressure_pa=40.0, delta_t_c=3.0,
        cooling_pad=None, house_cross_section_m2=25.0,
    )
    assert rec.target_unreachable  # 38C outside, target ~20.7C
    status = bs.from_recommendation(rec)
    # Evaluated at ~38C, not the 20.7C target -> real heat stress.
    assert status.comfort_label == "Poor"
    assert status.heat_stress_risk in ("Moderate", "High")
    assert any("realistic" in n for n in status.notes)


def test_estimate_flags_are_honest():
    status = bs.assess(_comfort(30.0, 60.0, 2.3), 30.0, effective_temp_c=27.0)
    # Grounded reuse vs estimates are labelled correctly.
    assert status.is_estimate["comfort_score"] is False
    assert status.is_estimate["heat_stress_risk"] is False
    assert status.is_estimate["panting_index"] is True
    assert status.is_estimate["water_intake_multiplier"] is True
    assert status.notes  # cited notes present
