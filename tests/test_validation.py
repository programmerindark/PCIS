"""Unit tests for pcis.core.validation."""

import math

import pytest

from pcis.core import validation as val


# ---------------------------------------------------------------------------
# error_metrics
# ---------------------------------------------------------------------------

def test_error_metrics_hand_computed():
    predicted = [10.0, 20.0, 30.0]
    measured = [9.0, 22.0, 31.0]
    m = val.error_metrics(predicted, measured)

    assert m.n == 3
    assert m.bias == pytest.approx(-2.0 / 3.0)
    assert m.mae == pytest.approx(4.0 / 3.0)
    assert m.rmse == pytest.approx(math.sqrt(2.0))
    assert m.mape_pct == pytest.approx(7.8093, abs=1e-3)


def test_error_metrics_zero_bias_when_symmetric_errors():
    predicted = [10.0, 20.0]
    measured = [11.0, 19.0]
    m = val.error_metrics(predicted, measured)
    assert m.bias == pytest.approx(0.0)


def test_error_metrics_perfect_prediction():
    predicted = [5.0, 6.0, 7.0]
    measured = [5.0, 6.0, 7.0]
    m = val.error_metrics(predicted, measured)
    assert m.bias == pytest.approx(0.0)
    assert m.mae == pytest.approx(0.0)
    assert m.rmse == pytest.approx(0.0)
    assert m.mape_pct == pytest.approx(0.0)


def test_error_metrics_mape_none_when_measured_has_zero():
    predicted = [1.0, 2.0]
    measured = [0.0, 2.0]
    m = val.error_metrics(predicted, measured)
    assert m.mape_pct is None


def test_error_metrics_rejects_mismatched_lengths():
    with pytest.raises(ValueError):
        val.error_metrics([1.0, 2.0], [1.0])


def test_error_metrics_rejects_empty_input():
    with pytest.raises(ValueError):
        val.error_metrics([], [])


# ---------------------------------------------------------------------------
# fit_calibration
# ---------------------------------------------------------------------------

def test_fit_calibration_recovers_perfect_linear_relationship():
    predicted = [1.0, 2.0, 3.0, 4.0]
    measured = [2.0 * p + 1.0 for p in predicted]  # true slope=2, intercept=1
    fit = val.fit_calibration(predicted, measured)

    assert fit.slope == pytest.approx(2.0)
    assert fit.intercept == pytest.approx(1.0)
    assert fit.r_squared == pytest.approx(1.0)
    assert fit.n == 4


def test_fit_calibration_apply():
    predicted = [1.0, 2.0, 3.0, 4.0]
    measured = [2.0 * p + 1.0 for p in predicted]
    fit = val.fit_calibration(predicted, measured)
    assert fit.apply(10.0) == pytest.approx(21.0)


def test_fit_calibration_r_squared_less_than_one_with_noise():
    predicted = [1.0, 2.0, 3.0, 4.0, 5.0]
    measured = [2.1, 3.9, 6.2, 7.8, 10.3]  # roughly measured ~= 2*predicted, with noise
    fit = val.fit_calibration(predicted, measured)
    assert 0.0 < fit.r_squared < 1.0


def test_fit_calibration_requires_minimum_points():
    with pytest.raises(ValueError):
        val.fit_calibration([1.0, 2.0], [1.0, 2.0])


def test_fit_calibration_rejects_identical_predicted_values():
    with pytest.raises(ValueError):
        val.fit_calibration([5.0, 5.0, 5.0], [1.0, 2.0, 3.0])


def test_fit_calibration_rejects_mismatched_lengths():
    with pytest.raises(ValueError):
        val.fit_calibration([1.0, 2.0, 3.0], [1.0, 2.0])


# ---------------------------------------------------------------------------
# residuals
# ---------------------------------------------------------------------------

def test_residuals_basic():
    predicted = [10.0, 20.0, 30.0]
    measured = [9.0, 22.0, 31.0]
    r = val.residuals(predicted, measured)
    assert r == [pytest.approx(1.0), pytest.approx(-2.0), pytest.approx(-1.0)]


def test_residuals_rejects_mismatched_lengths():
    with pytest.raises(ValueError):
        val.residuals([1.0, 2.0], [1.0])
