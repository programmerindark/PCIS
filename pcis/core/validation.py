"""Validation and calibration: compare predicted vs. measured values
and fit per-house correction factors.

Per the project's stated development plan: "The software must be
validated using real farm data. Compare predicted values against
measured temperature, humidity, static pressure, airflow, and bird
performance, then allow calibration for individual poultry houses."

This module provides the generic machinery for that -- it does not
itself contain any poultry-specific engineering constants. The error
metrics (bias, MAE, RMSE, MAPE) are standard statistical definitions
used throughout agricultural/biosystems engineering model-validation
literature (e.g. ASABE/CIGR model evaluation practice commonly reports
RMSE and mean bias error for exactly this kind of predicted-vs-
measured comparison); no external numeric citation is needed for
these formulas themselves, the same way basic conduction heat transfer
(Q=UA*dT) didn't need one in `heat_moisture_balance.py`.

Calibration here is intentionally simple and transparent: a linear
correction (measured ~= slope * predicted + intercept), fit by
ordinary least squares from paired (predicted, measured) observations.
This is a standard, interpretable first calibration model -- not a
claim that the true predicted/measured relationship is exactly linear.
If a house's residuals show clear nonlinearity or heteroscedasticity,
that is itself useful validation information (surfaced via
`residuals` and `r_squared`) and should prompt a closer look at the
underlying engineering model rather than a more complex curve fit
applied blindly.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class ErrorMetrics:
    """Standard predicted-vs-measured error metrics.

    bias : float
        Mean signed error (predicted - measured). Positive = model
        over-predicts on average; negative = under-predicts.
    mae : float
        Mean absolute error.
    rmse : float
        Root mean square error.
    mape_pct : float | None
        Mean absolute percentage error, percent. None if any measured
        value is zero (MAPE is undefined/unstable in that case).
    n : int
        Number of paired observations.
    """

    bias: float
    mae: float
    rmse: float
    mape_pct: float | None
    n: int


def error_metrics(predicted: list[float], measured: list[float]) -> ErrorMetrics:
    """Compute standard error metrics between paired predicted/measured
    values.

    Parameters
    ----------
    predicted : list[float]
        Model-predicted values.
    measured : list[float]
        Corresponding real-world measured values, same length and
        order as `predicted`.

    Returns
    -------
    ErrorMetrics
    """
    if len(predicted) != len(measured):
        raise ValueError("predicted and measured must be the same length")
    if len(predicted) == 0:
        raise ValueError("predicted/measured must contain at least one pair")

    n = len(predicted)
    errors = [p - m for p, m in zip(predicted, measured)]
    bias = sum(errors) / n
    mae = sum(abs(e) for e in errors) / n
    rmse = math.sqrt(sum(e * e for e in errors) / n)

    if any(m == 0 for m in measured):
        mape_pct = None
    else:
        mape_pct = 100.0 * sum(abs(e / m) for e, m in zip(errors, measured)) / n

    return ErrorMetrics(bias=bias, mae=mae, rmse=rmse, mape_pct=mape_pct, n=n)


@dataclass(frozen=True)
class CalibrationFactor:
    """A fitted linear calibration: measured ~= slope*predicted + intercept.

    r_squared : float
        Coefficient of determination of the fit, 0-1. Low values mean
        the linear correction isn't capturing much of the
        predicted-vs-measured relationship -- treat the calibration
        with proportionate skepticism in that case.
    n : int
        Number of observations the fit was built from.
    """

    slope: float
    intercept: float
    r_squared: float
    n: int

    def apply(self, predicted_value: float) -> float:
        """Apply this calibration to a new predicted value."""
        return self.slope * predicted_value + self.intercept


#: Minimum number of paired observations required to fit a
#: calibration. Below this, a "fit" is just connecting noise -- PCIS
#: engineering judgment (a small, defensible floor), not a literature
#: value.
MIN_CALIBRATION_POINTS = 3


def fit_calibration(predicted: list[float], measured: list[float]) -> CalibrationFactor:
    """Fit a linear calibration (measured ~= slope*predicted + intercept)
    by ordinary least squares.

    Parameters
    ----------
    predicted : list[float]
        Model-predicted values.
    measured : list[float]
        Corresponding measured values.

    Returns
    -------
    CalibrationFactor

    Raises
    ------
    ValueError
        If fewer than `MIN_CALIBRATION_POINTS` pairs are given, or if
        all predicted values are identical (slope undefined).
    """
    if len(predicted) != len(measured):
        raise ValueError("predicted and measured must be the same length")
    if len(predicted) < MIN_CALIBRATION_POINTS:
        raise ValueError(
            f"need at least {MIN_CALIBRATION_POINTS} paired observations to "
            f"fit a calibration; got {len(predicted)}"
        )

    n = len(predicted)
    mean_p = sum(predicted) / n
    mean_m = sum(measured) / n

    ss_pp = sum((p - mean_p) ** 2 for p in predicted)
    if ss_pp == 0:
        raise ValueError("all predicted values are identical; cannot fit a slope")
    ss_pm = sum((p - mean_p) * (m - mean_m) for p, m in zip(predicted, measured))

    slope = ss_pm / ss_pp
    intercept = mean_m - slope * mean_p

    predicted_measured = [slope * p + intercept for p in predicted]
    ss_res = sum((m - pm) ** 2 for m, pm in zip(measured, predicted_measured))
    ss_tot = sum((m - mean_m) ** 2 for m in measured)
    r_squared = 1.0 - (ss_res / ss_tot) if ss_tot > 0 else 1.0

    return CalibrationFactor(slope=slope, intercept=intercept, r_squared=r_squared, n=n)


def residuals(predicted: list[float], measured: list[float]) -> list[float]:
    """Per-observation residuals (predicted - measured), same order as
    input -- useful for plotting/inspecting whether errors are
    randomly scattered (good) or show a pattern (a sign the underlying
    engineering model, not just its calibration, needs attention).
    """
    if len(predicted) != len(measured):
        raise ValueError("predicted and measured must be the same length")
    return [p - m for p, m in zip(predicted, measured)]
