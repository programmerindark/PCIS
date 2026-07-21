"""Unit tests for pcis.core.growth_curve."""

import pytest

from pcis.core.growth_curve import (
    ROSS_308_MAX_AGE_DAYS,
    ROSS_308_MIN_AGE_DAYS,
    ross_308_body_weight_kg,
)


def test_day_zero_matches_aviagen_table():
    assert ross_308_body_weight_kg(0) == pytest.approx(0.044)


def test_day_42_matches_aviagen_table():
    # A commonly used broiler market age.
    assert ross_308_body_weight_kg(42) == pytest.approx(2.998)


def test_day_56_matches_aviagen_table_max():
    assert ross_308_body_weight_kg(56) == pytest.approx(4.318)


def test_weight_is_monotonically_increasing():
    weights = [ross_308_body_weight_kg(d) for d in range(ROSS_308_MIN_AGE_DAYS, ROSS_308_MAX_AGE_DAYS + 1)]
    assert all(w1 < w2 for w1, w2 in zip(weights, weights[1:]))


def test_fractional_age_interpolates_between_days():
    w21 = ross_308_body_weight_kg(21)
    w22 = ross_308_body_weight_kg(22)
    w21_5 = ross_308_body_weight_kg(21.5)
    assert w21 < w21_5 < w22
    assert w21_5 == pytest.approx((w21 + w22) / 2, abs=1e-6)


def test_refuses_to_extrapolate_beyond_table():
    with pytest.raises(ValueError, match="refusing to extrapolate"):
        ross_308_body_weight_kg(-1)
    with pytest.raises(ValueError, match="refusing to extrapolate"):
        ross_308_body_weight_kg(57)
