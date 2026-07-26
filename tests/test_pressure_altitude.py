"""Barometric pressure must reach the psychrometrics.

Discovered from live sensor data: the farm's Ecowitt gateway reports
946 hPa, not the 1013.25 hPa PCIS assumed. Air at that pressure is
about 7% thinner, so each cubic metre a fan moves carries ~7% less
mass and therefore ~7% less heat. Assuming sea level silently
UNDER-ventilates a house at altitude, which is the dangerous direction.

These tests pin the correction so it cannot regress.
"""
from __future__ import annotations

import pytest

from pcis.core import psychrometrics as psy
from pcis.core import recommendation_engine as re
from pcis.equipment.fan_curve import FAN_CATALOG

from backend.app.engine_api import _surfaces as _mk_surfaces


def _surfaces():
    return _mk_surfaces(120.0, 15.0, 3.0, "insulated")

MEASURED_PA = 94620.0   # 946.2 hPa, read off the farm's WittBoy


def _rec(pressure_pa):
    fan = FAN_CATALOG[0]
    return re.recommend(
        bird_count=21940, body_weight_kg=2.3, indoor_t_c=21.0,
        indoor_rh_pct=70.0, outdoor_t_c=18.0, outdoor_rh_pct=60.0,
        envelope_surfaces=_surfaces(), fan=fan,
        design_static_pressure_pa=30.0, delta_t_c=3.0, cooling_pad=None,
        house_cross_section_m2=15 * 3, heater_capacity_w=None,
        bird_age_days=37, pressure_pa=pressure_pa,
    )


def test_lower_pressure_demands_more_airflow():
    """Thinner air carries less heat per m3, so more m3 are needed."""
    sea = _rec(psy.STANDARD_ATM_PRESSURE_PA)
    alt = _rec(MEASURED_PA)
    assert alt.governing_constraint == "sensible_heat"
    assert alt.required_airflow_m3_per_h > sea.required_airflow_m3_per_h
    # ~7% thinner air => ~7% more volume flow, within a tolerance that
    # allows for the humidity-ratio shift riding along with it.
    ratio = alt.required_airflow_m3_per_h / sea.required_airflow_m3_per_h
    assert 1.03 < ratio < 1.12


def test_assuming_sea_level_would_under_ventilate():
    """The error is in the unsafe direction, which is why this matters."""
    assert _rec(MEASURED_PA).fans_on >= _rec(psy.STANDARD_ATM_PRESSURE_PA).fans_on


def test_default_is_still_sea_level():
    """Callers that measure nothing keep the documented old behaviour."""
    fan = FAN_CATALOG[0]
    kw = dict(
        bird_count=21940, body_weight_kg=2.3, indoor_t_c=21.0,
        indoor_rh_pct=70.0, outdoor_t_c=18.0, outdoor_rh_pct=60.0,
        envelope_surfaces=_surfaces(), fan=fan,
        design_static_pressure_pa=30.0, delta_t_c=3.0, cooling_pad=None,
        house_cross_section_m2=15 * 3, heater_capacity_w=None,
        bird_age_days=37,
    )
    assert (re.recommend(**kw).required_airflow_m3_per_h
            == re.recommend(**kw, pressure_pa=psy.STANDARD_ATM_PRESSURE_PA)
            .required_airflow_m3_per_h)


def test_pressure_correction_is_disclosed_to_the_user():
    """A silent correction is not acceptable in a safety-relevant tool."""
    assert any("barometric" in e.lower() for e in _rec(MEASURED_PA).explanation)


@pytest.mark.parametrize("t,rh", [(24.9, 96.0), (24.7, 99.0)])
def test_humidity_ratio_rises_at_altitude(t, rh):
    """Same temperature and RH hold MORE water per kg dry air up high."""
    lo = psy.humidity_ratio_from_relative_humidity(t, rh, MEASURED_PA)
    hi = psy.humidity_ratio_from_relative_humidity(t, rh, psy.STANDARD_ATM_PRESSURE_PA)
    assert lo > hi


def test_pcis_vpd_agrees_with_the_sensor_own_vpd():
    """Independent cross-check: the gateway computes VPD itself.

    Ecowitt reported 0.037 inHg (0.125 kPa) at 24.9 C / 96% RH.
    PCIS computes this from Buck (1996) with no knowledge of Ecowitt's
    method, so agreement is real external validation, not circularity.
    """
    ecowitt_kpa = 0.037 * 3.386389
    assert psy.vapor_pressure_deficit(24.9, 96.0) == pytest.approx(ecowitt_kpa, abs=0.01)
