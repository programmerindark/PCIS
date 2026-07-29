"""Birds removed alive are not dead birds.

Broiler flocks are routinely thinned: a portion is caught and sent to
slaughter days before the rest. On this farm that is called "lifting".

Before depletion was modelled, the only way to tell PCIS the house had
emptied was to reduce the live count, which wrote the difference into the
mortality log. The EU ceiling is ~3% at market age and a thin removes
20-40% in a morning, so the app reported a catastrophic welfare breach on
a day when nothing had gone wrong -- and corrupted the outcome history at
the same time.

These tests exist so that cannot come back.
"""
from __future__ import annotations

import pytest

from pcis.core import mortality as m

PLACED = 21940
AGE = 37.0
LIFT = 6000
REAL_DEATHS = 180


def test_a_thin_does_not_look_like_a_welfare_breach():
    r = m.assess(placed=PLACED, cumulative_dead=REAL_DEATHS, age_days=AGE, depleted=LIFT)
    assert r.within_target
    assert r.cumulative_pct < 1.0


def test_the_old_behaviour_would_have_failed_this_flock():
    """Guards the regression: thin-as-deaths must look wrong."""
    wrong = m.assess(placed=PLACED, cumulative_dead=REAL_DEATHS + LIFT, age_days=AGE)
    assert not wrong.within_target
    assert wrong.cumulative_pct > 25.0


def test_live_count_excludes_both_the_dead_and_the_lifted():
    r = m.assess(placed=PLACED, cumulative_dead=REAL_DEATHS, age_days=AGE, depleted=LIFT)
    assert r.live_count == PLACED - REAL_DEATHS - LIFT


def test_mortality_percentage_ignores_the_lifted_birds():
    with_lift = m.assess(placed=PLACED, cumulative_dead=REAL_DEATHS, age_days=AGE, depleted=LIFT)
    without = m.assess(placed=PLACED, cumulative_dead=REAL_DEATHS, age_days=AGE)
    assert with_lift.cumulative_pct == without.cumulative_pct


def test_depletion_is_reported_so_the_operator_sees_why_the_count_dropped():
    r = m.assess(placed=PLACED, cumulative_dead=REAL_DEATHS, age_days=AGE, depleted=LIFT)
    assert r.depleted == LIFT
    assert "removed alive" in r.note
    assert "15,760" in r.note


def test_todays_rate_is_measured_against_the_birds_still_present():
    """After a thin, 50 deaths is a bigger share of a smaller flock."""
    before = m.assess(placed=PLACED, cumulative_dead=REAL_DEATHS, age_days=AGE, dead_today=50)
    after = m.assess(placed=PLACED, cumulative_dead=REAL_DEATHS, age_days=AGE,
                     dead_today=50, depleted=LIFT)
    assert after.daily_pct > before.daily_pct


def test_deaths_cannot_exceed_the_birds_actually_in_the_house():
    r = m.assess(placed=1000, cumulative_dead=999, age_days=40, depleted=900)
    assert r.cumulative_dead <= 100
    assert r.live_count >= 0


def test_full_depletion_empties_the_house_without_erroring():
    r = m.assess(placed=PLACED, cumulative_dead=0, age_days=42, depleted=PLACED)
    assert r.live_count == 0
    assert r.within_target


def test_no_depletion_behaves_exactly_as_before():
    """The default path must be untouched for flocks that never thin."""
    a = m.assess(placed=PLACED, cumulative_dead=REAL_DEATHS, age_days=AGE)
    b = m.assess(placed=PLACED, cumulative_dead=REAL_DEATHS, age_days=AGE, depleted=0)
    assert a == b
    assert "removed alive" not in a.note


@pytest.mark.parametrize("depleted", [-5, 0, 100, PLACED, PLACED * 2])
def test_depletion_is_clamped_to_something_physical(depleted):
    r = m.assess(placed=PLACED, cumulative_dead=10, age_days=AGE, depleted=depleted)
    assert 0 <= r.depleted <= PLACED
    assert r.live_count >= 0
