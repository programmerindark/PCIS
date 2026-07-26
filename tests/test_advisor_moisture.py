"""The advisor must not go quiet when ventilation cannot fix the problem.

A decision-support tool earns its place by being useful in the awkward
cases, not the easy ones. When outside air is as wet as house air, more
fans cannot dry anything -- but that is precisely when an operator most
needs to be told what WILL work, and roughly how long the condition lasts.
"""
from __future__ import annotations

import pytest

from backend.app.engine_api import _surfaces
from pcis.core import advisor
from pcis.core import recommendation_engine as re
from pcis.core import ventilation_solver as vs
from pcis.equipment.fan_curve import FAN_CATALOG

MEASURED_PA = 94620.0


def _rec(indoor_rh, outdoor_t, outdoor_rh):
    return re.recommend(
        bird_count=21940, body_weight_kg=2.496, indoor_t_c=21.0,
        indoor_rh_pct=indoor_rh, outdoor_t_c=outdoor_t,
        outdoor_rh_pct=outdoor_rh,
        envelope_surfaces=_surfaces(120.0, 15.0, 3.0, "insulated"),
        fan=FAN_CATALOG[0], design_static_pressure_pa=30.0, delta_t_c=3.0,
        cooling_pad=None, house_cross_section_m2=45.0,
        heater_capacity_w=None, bird_age_days=37, pressure_pa=MEASURED_PA,
    )


# --- the farm's actual measured state ------------------------------------

def test_saturated_outside_air_triggers_the_moisture_branch():
    a = advisor.advise(_rec(96.0, 24.7, 99.0), installed_fans=10, pads_installed=False)
    assert a.category == "moisture_limited"


def test_it_does_not_tell_the_operator_to_buy_fans():
    """Capex is not an answer to a question asked this afternoon."""
    a = advisor.advise(_rec(96.0, 24.7, 99.0), installed_fans=10, pads_installed=False)
    assert "add capacity" not in a.detail.lower()


def test_it_still_says_to_run_the_fans():
    """Moisture may be stuck, but CO2 and ammonia removal never stops."""
    a = advisor.advise(_rec(96.0, 24.7, 99.0), installed_fans=10, pads_installed=False)
    assert "10 fans" in a.headline
    assert "air quality" in a.headline


def test_it_names_actions_that_actually_work():
    a = advisor.advise(_rec(96.0, 24.7, 99.0), installed_fans=10, pads_installed=False)
    assert "drinker" in a.detail.lower()
    assert "litter" in a.detail.lower()


def test_it_says_when_the_condition_lifts():
    """A watchable threshold beats an open-ended dead end."""
    a = advisor.advise(_rec(96.0, 24.7, 99.0), installed_fans=10, pads_installed=False)
    assert "outdoor humidity falls below" in a.detail


# --- the branch must not swallow more urgent problems ---------------------

def test_heat_stress_still_outranks_moisture():
    """If birds are cooking, cooling advice must win regardless."""
    rec = _rec(96.0, 40.0, 85.0)
    a = advisor.advise(rec, installed_fans=10, pads_installed=False)
    if a.heat_stress_risk in ("High", "Severe"):
        assert a.category != "moisture_limited"


def test_normal_humid_day_does_not_trigger_it():
    a = advisor.advise(_rec(65.0, 24.0, 55.0), installed_fans=20, pads_installed=False)
    assert a.category != "moisture_limited"


# --- the threshold itself -------------------------------------------------

def test_threshold_is_below_current_outdoor_humidity():
    """Otherwise it would claim drying works when it demonstrably does not."""
    rec = _rec(96.0, 24.7, 99.0)
    assert rec.moisture_control_limited
    assert rec.outdoor_rh_for_drying_pct is not None
    assert rec.outdoor_rh_for_drying_pct < 99.0


def test_threshold_actually_restores_drying():
    """Cross-check the solver against the engine's own gating rule."""
    rec = _rec(96.0, 24.7, 99.0)
    thr = rec.outdoor_rh_for_drying_pct
    assert not _rec(96.0, 24.7, min(thr - 2.0, 99.0)).moisture_control_limited


def test_no_threshold_reported_when_drying_already_works():
    assert vs.outdoor_rh_threshold_for_drying(24.9, 96.0, 5.0, MEASURED_PA) is None


@pytest.mark.parametrize("outdoor_rh", [99.0, 97.0])
def test_threshold_is_a_plausible_humidity(outdoor_rh):
    thr = _rec(96.0, 24.7, outdoor_rh).outdoor_rh_for_drying_pct
    assert thr is None or 0.0 <= thr <= 100.0
