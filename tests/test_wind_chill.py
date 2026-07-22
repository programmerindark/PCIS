"""Tests for pcis.core.wind_chill.

Every expected value here traces to the Aviagen worked example the
module is built on (90 F at 500 ft/min feels like 80 F to fully-
feathered birds), or to a bound Aviagen states in words. Nothing is
checked against the module's own arithmetic alone.
"""

from __future__ import annotations

import pytest

from pcis.core import wind_chill as wc


def test_reproduces_the_aviagen_anchor():
    # 90 F = 32.2 C, 500 ft/min = 2.54 m/s, feels like ~80 F = 26.7 C.
    drop = wc.effective_temperature_drop_c(32.2, 2.54)
    assert drop == pytest.approx(5.6, abs=0.05)
    assert wc.effective_temperature_c(32.2, 2.54) == pytest.approx(26.6, abs=0.1)


def test_still_air_gives_no_cooling():
    assert wc.effective_temperature_drop_c(29.0, 0.0) == 0.0
    assert wc.effective_temperature_c(29.0, 0.0) == 29.0


def test_cooling_increases_with_air_speed_up_to_the_cap():
    slow = wc.effective_temperature_drop_c(29.0, 1.0)
    med = wc.effective_temperature_drop_c(29.0, 2.0)
    assert med > slow


def test_cooling_is_capped_at_the_cited_ceiling():
    # "as much as 10-12 degrees F" -> 6.7 C cap; very fast air can't exceed it.
    assert wc.effective_temperature_drop_c(29.0, 8.0) == pytest.approx(wc.MAX_COOLING_C)
    assert wc.effective_temperature_drop_c(29.0, 20.0) <= wc.MAX_COOLING_C


def test_effect_fades_as_ambient_rises_above_90F():
    # Same speed, hotter air -> less credited cooling ("less pronounced
    # much above 90 F").
    at_90 = wc.effective_temperature_drop_c(32.2, 2.54)
    at_95 = wc.effective_temperature_drop_c(35.0, 2.54)
    assert at_95 < at_90
    assert at_95 > 0.0


def test_no_cooling_credited_above_100F():
    # "above 100 F the air begins to warm instead of cool" -> PCIS holds
    # the estimate at zero rather than inventing a warming magnitude.
    assert wc.effective_temperature_drop_c(37.8, 3.0) == 0.0
    assert wc.effective_temperature_drop_c(40.0, 5.0) == 0.0
    assert wc.effective_temperature_c(40.0, 5.0) == 40.0


def test_effective_temperature_never_exceeds_dry_bulb():
    for t in (10.0, 25.0, 32.0, 38.0, 45.0):
        for v in (0.0, 1.5, 3.0, 6.0):
            assert wc.effective_temperature_c(t, v) <= t + 1e-9


def test_drop_is_never_negative():
    for t in (5.0, 30.0, 39.0):
        for v in (0.0, 2.0, 5.0):
            assert wc.effective_temperature_drop_c(t, v) >= 0.0
