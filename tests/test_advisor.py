"""Tests for the AI Advisor decision layer.

The advisor is deterministic rules over the engine's Recommendation, so
these check that the right action is chosen in each regime and that the
predicted before/after is engine-consistent (and honest -- wind-chill
fades in extreme heat).
"""

import pytest

from pcis.core import advisor
from pcis.core import heat_moisture_balance as hmb
from pcis.core import comfort_engine as ce
from pcis.core import recommendation_engine as re
from pcis.equipment.fan_curve import FAN_CATALOG

SURF = [hmb.Surface("w", 0.41, 350.0), hmb.Surface("c", 0.26, 1500.0)]


def _rec(**kw):
    d = dict(
        bird_count=20000, body_weight_kg=2.3,
        indoor_t_c=ce.target_temperature(2.3, 60), indoor_rh_pct=60,
        outdoor_t_c=37, outdoor_rh_pct=45, envelope_surfaces=SURF,
        fan=FAN_CATALOG[0], design_static_pressure_pa=40, delta_t_c=3,
        cooling_pad=None, house_cross_section_m2=25, heater_capacity_w=None,
    )
    d.update(kw)
    return re.recommend(**d)


def test_hot_feathered_recommends_airspeed_cooling():
    a = advisor.advise(_rec(outdoor_t_c=31), installed_fans=15, pads_installed=False)
    assert a.category == "cooling_airspeed"
    assert "fans" in a.headline.lower()
    # At moderate heat, running fans measurably lowers felt temp + panting.
    assert a.feel_after_c < a.feel_before_c


def test_extreme_heat_windchill_is_honest():
    # Above ~37C wind-chill has essentially faded; the advisor must NOT
    # claim a big felt-temperature drop.
    a = advisor.advise(_rec(outdoor_t_c=38), installed_fans=15, pads_installed=False)
    assert (a.feel_before_c - a.feel_after_c) < 2.0


def test_fan_shortfall_is_flagged():
    a = advisor.advise(_rec(outdoor_t_c=34), installed_fans=4, pads_installed=False)
    assert a.category == "capacity"
    assert "capacity" in a.headline.lower() or "short" in a.headline.lower()


def test_cold_prioritises_heating():
    a = advisor.advise(
        _rec(outdoor_t_c=-2, outdoor_rh_pct=80, heater_capacity_w=60000),
        installed_fans=10, pads_installed=False,
    )
    assert a.category == "heating"


def test_mild_conditions_hold():
    a = advisor.advise(_rec(outdoor_t_c=18), installed_fans=10, pads_installed=False)
    assert a.category == "hold"


def test_confidence_passes_through():
    r = _rec(outdoor_t_c=31)
    a = advisor.advise(r, installed_fans=15, pads_installed=False)
    assert a.confidence == r.confidence_score
