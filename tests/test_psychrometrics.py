"""Unit tests for pcis.core.psychrometrics.

Reference values used below are cross-checked against standard steam-table
saturation pressures and commonly published ASHRAE psychrometric-chart
reference points (e.g. NIST/ASHRAE steam tables at 20 C and 30 C, and
chart readings at 24 C / 50% RH). Tolerances are set at 1-2% relative
error to account for the difference between the Buck (1996) correlation
used here and the Hyland-Wexler correlation ASHRAE tabulates -- these are
sanity/cross-checks, not bit-for-bit reproductions of a published table.
"""

import math

import pytest

from pcis.core import psychrometrics as psy


# ---------------------------------------------------------------------------
# Saturation vapor pressure
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "t_c, expected_pa, rel_tol",
    [
        (0.0, 611.2, 0.01),      # triple point, ~611 Pa
        (20.0, 2338.8, 0.01),    # steam table
        (30.0, 4245.2, 0.01),    # steam table
        (35.0, 5628.0, 0.02),    # steam table (typical poultry-house extreme)
    ],
)
def test_saturation_vapor_pressure_matches_steam_table(t_c, expected_pa, rel_tol):
    result = psy.saturation_vapor_pressure(t_c)
    assert result == pytest.approx(expected_pa, rel=rel_tol)


def test_saturation_vapor_pressure_increases_with_temperature():
    values = [psy.saturation_vapor_pressure(t) for t in range(-10, 41, 5)]
    assert all(b > a for a, b in zip(values, values[1:]))


def test_saturation_vapor_pressure_ice_vs_water_continuity_near_zero():
    # The water-phase and ice-phase curves should be close (not identical)
    # right at 0 C where the implementation switches branches.
    just_above = psy.saturation_vapor_pressure(0.0001)
    just_below = psy.saturation_vapor_pressure(-0.0001)
    assert just_above == pytest.approx(just_below, rel=0.01)


# ---------------------------------------------------------------------------
# Dew point (inverse of saturation vapor pressure)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("t_c", [-10.0, 0.0, 5.0, 15.0, 24.0, 30.0, 40.0])
def test_dew_point_round_trip(t_c):
    pws = psy.saturation_vapor_pressure(t_c)
    recovered_t = psy.dew_point_temperature(pws)
    assert recovered_t == pytest.approx(t_c, abs=0.05)


def test_dew_point_requires_positive_pressure():
    with pytest.raises(ValueError):
        psy.dew_point_temperature(0.0)


# ---------------------------------------------------------------------------
# Humidity ratio / relative humidity
# ---------------------------------------------------------------------------

def test_humidity_ratio_reference_point_20c_50rh():
    # Known ASHRAE chart point: 20 C, 50% RH, sea level -> W ~ 0.00727 kg/kg
    w = psy.humidity_ratio_from_relative_humidity(20.0, 50.0)
    assert w == pytest.approx(0.00727, rel=0.02)


def test_humidity_ratio_reference_point_30c_60rh():
    # Known ASHRAE chart point: 30 C, 60% RH, sea level -> W ~ 0.0160 kg/kg
    w = psy.humidity_ratio_from_relative_humidity(30.0, 60.0)
    assert w == pytest.approx(0.0160, rel=0.02)


def test_relative_humidity_round_trip():
    for t_c in (10.0, 20.0, 24.0, 32.0):
        for rh in (20.0, 50.0, 80.0, 100.0):
            w = psy.humidity_ratio_from_relative_humidity(t_c, rh)
            rh_recovered = psy.relative_humidity_from_humidity_ratio(t_c, w)
            assert rh_recovered == pytest.approx(rh, abs=0.05)


def test_humidity_ratio_rejects_out_of_range_rh():
    with pytest.raises(ValueError):
        psy.humidity_ratio_from_relative_humidity(20.0, 150.0)
    with pytest.raises(ValueError):
        psy.humidity_ratio_from_relative_humidity(20.0, -5.0)


# ---------------------------------------------------------------------------
# Wet bulb temperature
# ---------------------------------------------------------------------------

def test_wet_bulb_equals_dry_bulb_at_saturation():
    # At 100% RH, thermodynamic wet bulb == dry bulb == dew point.
    t_c = 25.0
    w = psy.humidity_ratio_from_relative_humidity(t_c, 100.0)
    twb = psy.wet_bulb_temperature(t_c, w)
    assert twb == pytest.approx(t_c, abs=0.05)


def test_wet_bulb_below_dry_bulb_when_unsaturated():
    t_c = 30.0
    w = psy.humidity_ratio_from_relative_humidity(t_c, 50.0)
    twb = psy.wet_bulb_temperature(t_c, w)
    tdp = psy.dew_point_temperature(w * psy.STANDARD_ATM_PRESSURE_PA /
                                     (psy.WATER_TO_DRY_AIR_MOLAR_MASS_RATIO + w))
    assert tdp < twb < t_c


def test_humidity_ratio_from_wet_bulb_round_trips_with_wet_bulb_temperature():
    for t_c in (15.0, 24.0, 30.0, 35.0):
        for rh in (30.0, 50.0, 80.0):
            w = psy.humidity_ratio_from_relative_humidity(t_c, rh)
            twb = psy.wet_bulb_temperature(t_c, w)
            w_recovered = psy.humidity_ratio_from_wet_bulb(t_c, twb)
            assert w_recovered == pytest.approx(w, abs=1e-6)


def test_humidity_ratio_from_wet_bulb_at_saturation_equals_ws():
    # When T == Twb (saturated air), W should equal the saturation
    # humidity ratio at that temperature.
    t_c = 22.0
    ws = psy.humidity_ratio_from_partial_pressure(psy.saturation_vapor_pressure(t_c), psy.STANDARD_ATM_PRESSURE_PA)
    w = psy.humidity_ratio_from_wet_bulb(t_c, t_c)
    assert w == pytest.approx(ws, rel=1e-6)


def test_wet_bulb_reference_point_evaporative_cooling_case():
    # A typical tunnel-ventilated house design case: 35 C dry bulb, 40% RH.
    # Evaporative-cooling wet bulb depression should be substantial
    # (roughly 10-14 C depression is typical at this state on a
    # psychrometric chart) -- this is a sanity bound, not a precise
    # published figure.
    t_c = 35.0
    w = psy.humidity_ratio_from_relative_humidity(t_c, 40.0)
    twb = psy.wet_bulb_temperature(t_c, w)
    depression = t_c - twb
    assert 8.0 < depression < 16.0


# ---------------------------------------------------------------------------
# Enthalpy
# ---------------------------------------------------------------------------

def test_enthalpy_reference_point_20c_50rh():
    w = psy.humidity_ratio_from_relative_humidity(20.0, 50.0)
    h = psy.enthalpy(20.0, w)
    assert h == pytest.approx(38.6, rel=0.02)


def test_enthalpy_zero_humidity_is_sensible_heat_only():
    h = psy.enthalpy(25.0, 0.0)
    assert h == pytest.approx(1.006 * 25.0, rel=1e-9)


def test_enthalpy_increases_with_humidity_ratio():
    h_dry = psy.enthalpy(25.0, 0.005)
    h_humid = psy.enthalpy(25.0, 0.015)
    assert h_humid > h_dry


# ---------------------------------------------------------------------------
# Specific volume / density
# ---------------------------------------------------------------------------

def test_specific_volume_dry_air_at_standard_conditions():
    # Dry air (W=0) at 0 C, 101325 Pa: v = R*T/P = 287.055*273.15/101325
    v = psy.specific_volume(0.0, 0.0)
    expected = psy.R_DRY_AIR * psy.c_to_k(0.0) / psy.STANDARD_ATM_PRESSURE_PA
    assert v == pytest.approx(expected, rel=1e-9)
    # Known ideal-gas molar volume check: ~0.7734 m3/kg at 0 C, 1 atm
    assert v == pytest.approx(0.7733, rel=0.01)


def test_density_dry_air_at_standard_conditions():
    # Dry air density at 0 C, 101325 Pa should be ~1.292 kg/m3
    rho = psy.moist_air_density(0.0, 0.0)
    assert rho == pytest.approx(1.292, rel=0.01)


def test_density_decreases_with_temperature():
    rho_cold = psy.moist_air_density(0.0, 0.005)
    rho_hot = psy.moist_air_density(35.0, 0.005)
    assert rho_hot < rho_cold


def test_density_decreases_with_humidity_ratio_at_fixed_temperature():
    # Moist air is less dense than dry air at the same T, P (water vapor
    # is lighter than dry air on a molar basis) -- classic psychrometric
    # fact, important for exhaust-fan sizing at high humidity.
    rho_dry = psy.moist_air_density(30.0, 0.0)
    rho_humid = psy.moist_air_density(30.0, 0.020)
    assert rho_humid < rho_dry


# ---------------------------------------------------------------------------
# PsychrometricState convenience wrapper
# ---------------------------------------------------------------------------

def test_psychrometric_state_internal_consistency():
    state = psy.PsychrometricState(t_c=28.0, rh_pct=65.0)
    assert state.w == pytest.approx(
        psy.humidity_ratio_from_relative_humidity(28.0, 65.0)
    )
    assert state.enthalpy_kj_per_kg == pytest.approx(psy.enthalpy(28.0, state.w))
    assert state.wet_bulb_c < state.t_c
    assert state.dew_point_c < state.wet_bulb_c


def test_psychrometric_state_repr_does_not_raise():
    state = psy.PsychrometricState(t_c=24.0, rh_pct=55.0)
    assert "PsychrometricState" in repr(state)
