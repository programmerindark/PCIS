"""Tests for the SKOV Viper Touch reference curves and the
age-dependent wind-chill they enable."""

import pytest

from pcis.core import skov_reference as skov
from pcis.core import wind_chill as wc


# ----------------------------------------------------------------------
# Curve transcription + interpolation
# ----------------------------------------------------------------------

def test_curves_match_the_controller_screens():
    assert skov.INSIDE_TEMPERATURE_C[1] == 34.0
    assert skov.INSIDE_TEMPERATURE_C[42] == 19.0
    assert skov.HUMIDITY_PCT[42] == 85
    assert skov.CHILL_FACTOR[1] == 8.0
    assert skov.CHILL_FACTOR[49] == 2.5
    assert skov.MAX_TUNNEL_AIR_SPEED_MPS == 4.0


def test_interpolation_between_table_days():
    # halfway between day 21 (26.0) and day 28 (23.0)
    assert skov.inside_temperature_c(24.5) == pytest.approx(24.5, abs=0.1)


def test_curves_clamp_outside_the_table():
    assert skov.inside_temperature_c(0) == 34.0
    assert skov.inside_temperature_c(99) == 19.0
    assert skov.chill_factor(0) == 8.0
    assert skov.chill_factor(99) == 2.5


def test_temperature_setpoint_falls_with_age():
    temps = [skov.inside_temperature_c(d) for d in [1, 7, 14, 21, 28, 35, 42]]
    assert temps == sorted(temps, reverse=True)


def test_expected_humidity_rises_with_age():
    rh = [skov.expected_humidity_pct(d) for d in [1, 14, 28, 42]]
    assert rh == sorted(rh)
    # commercial practice EXPECTS >70% late — the Aviagen table's limit
    assert skov.expected_humidity_pct(42) > 70


def test_min_air_speed_rises_with_age_and_stays_under_max():
    speeds = [skov.min_tunnel_air_speed_mps(d) for d in [0, 14, 28, 42]]
    assert speeds == sorted(speeds)
    assert all(s < skov.MAX_TUNNEL_AIR_SPEED_MPS for s in speeds)


# ----------------------------------------------------------------------
# Chill sensitivity ratio — the gap this data fills
# ----------------------------------------------------------------------

def test_chill_ratio_is_one_at_the_feathered_reference():
    assert skov.chill_sensitivity_ratio(skov.FEATHERED_REFERENCE_DAY) == pytest.approx(1.0)


def test_young_birds_are_more_chill_sensitive():
    assert skov.chill_sensitivity_ratio(1) == pytest.approx(3.2, abs=0.01)
    ratios = [skov.chill_sensitivity_ratio(d) for d in [1, 14, 28, 42, 49]]
    assert ratios == sorted(ratios, reverse=True)


# ----------------------------------------------------------------------
# Age-aware wind chill
# ----------------------------------------------------------------------

def test_age_aware_chill_exceeds_feathered_estimate_for_chicks():
    # Low air speed, so the cited ceiling does not bind and the age
    # ratio applies in full.
    t, v = 30.0, 0.4
    feathered = wc.effective_temperature_drop_c(t, v)
    chick = wc.effective_temperature_drop_for_age_c(t, v, age_days=1)
    assert chick > feathered
    assert chick == pytest.approx(feathered * 3.2, rel=1e-6)


def test_age_scaling_never_exceeds_the_cited_ceiling():
    """REGRESSION: scaling Aviagen's published 10-12 F ceiling by the age
    ratio produced 9.3 C at day 29 — an estimate larger than the only
    source we have permits. The ratio must act BELOW the ceiling only."""
    for age in [1, 7, 14, 21, 29, 42, 49]:
        for speed in [1.0, 2.0, 3.0, 4.0]:
            drop = wc.effective_temperature_drop_for_age_c(28.0, speed, age)
            assert drop <= wc.MAX_COOLING_C + 1e-9, f"day {age} @ {speed} m/s -> {drop:.1f} C"


def test_age_aware_chill_matches_base_model_at_reference_age():
    t, v = 30.0, 2.0
    assert wc.effective_temperature_drop_for_age_c(t, v, 49) == pytest.approx(
        wc.effective_temperature_drop_c(t, v)
    )


def test_age_aware_felt_temperature_is_colder_for_chicks():
    t, v = 30.0, 1.5
    assert wc.effective_temperature_for_age_c(t, v, 1) < wc.effective_temperature_for_age_c(t, v, 49)


def test_age_scaled_chill_is_bounded():
    """Scaling the cited ceiling by 3.2x would imply ~21 C of chill —
    not a defensible estimate. The result must stay bounded."""
    drop = wc.effective_temperature_drop_for_age_c(28.0, 3.0, age_days=1)
    assert drop <= wc.MAX_COOLING_C + 1e-9


def test_chill_is_modest_at_realistic_young_bird_speeds():
    """Young birds are held at low air speed, where the estimate should
    stay small and credible."""
    for age, speed in [(1, 0.20), (7, 0.33), (14, 0.47), (21, 0.60)]:
        drop = wc.effective_temperature_drop_for_age_c(30.0, speed, age)
        assert 0.5 < drop < 4.0, f"day {age} @ {speed} m/s gave {drop:.1f} C"


def test_age_aware_chill_still_fades_in_extreme_heat():
    """The Aviagen heat taper must survive the age scaling."""
    assert wc.effective_temperature_drop_for_age_c(39.0, 3.0, age_days=1) == pytest.approx(0.0, abs=0.01)


# ----------------------------------------------------------------------
# Disagreement with Aviagen is surfaced, not hidden
# ----------------------------------------------------------------------

def test_target_temperature_disagreement_is_flagged():
    # PCIS/Aviagen gives ~22.0 C at day 21; SKOV says 26.0 C.
    cmp = skov.compare_target_temperature(21, aviagen_target_c=22.0)
    assert cmp["skov_controller_c"] == 26.0
    assert cmp["materially_different"] is True
    assert "colder" in cmp["note"]


def test_close_agreement_is_reported_as_such():
    cmp = skov.compare_target_temperature(42, aviagen_target_c=19.3)
    assert cmp["materially_different"] is False
    assert "agree" in cmp["note"]
