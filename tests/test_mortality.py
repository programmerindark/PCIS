"""Tests for the cited mortality/livability benchmark."""

import pytest

from pcis.core import mortality as m


def test_acceptable_ceiling_matches_eu_formula():
    # EU 2007/43/EC: 1% + 0.06% * age.
    assert m.acceptable_cumulative_mortality_pct(0) == pytest.approx(1.0)
    assert m.acceptable_cumulative_mortality_pct(28) == pytest.approx(1.0 + 0.06 * 28)
    assert m.acceptable_cumulative_mortality_pct(42) == pytest.approx(3.52)


def test_live_count_and_cumulative_pct():
    a = m.assess(placed=24500, cumulative_dead=1225, age_days=28)
    assert a.live_count == 24500 - 1225
    assert a.cumulative_pct == pytest.approx(5.0, abs=0.01)


def test_within_target_when_below_ceiling():
    # day 28 ceiling = 2.68%. 2% cumulative is within.
    a = m.assess(placed=20000, cumulative_dead=400, age_days=28)
    assert a.cumulative_pct == pytest.approx(2.0)
    assert a.within_target is True
    assert "within" in a.note.lower()


def test_flags_when_above_ceiling():
    # day 28 ceiling = 2.68%. 5% is above -> investigate.
    a = m.assess(placed=20000, cumulative_dead=1000, age_days=28)
    assert a.within_target is False
    assert "above" in a.note.lower()


def test_elevated_today_flag():
    # 200 dead today out of ~20000 live = 1% > 0.5% threshold.
    a = m.assess(placed=20000, cumulative_dead=300, age_days=10, dead_today=200)
    assert a.elevated_today is True
    assert a.daily_pct > m.ELEVATED_DAILY_PCT


def test_clamps_impossible_inputs():
    a = m.assess(placed=1000, cumulative_dead=5000, age_days=20)
    assert a.live_count == 0
    assert a.cumulative_pct == 100.0
