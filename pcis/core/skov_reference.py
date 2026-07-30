"""Commercial controller reference curves (SKOV Viper Touch).

Transcribed directly from a SKOV Viper Touch controller's configuration
screens (broiler house, day-indexed curves). SKOV is a major poultry
climate-controller manufacturer, so these are manufacturer guidance of
the same class PCIS already accepts for fan curves and cooling pads --
NOT peer-reviewed literature, and NOT breed performance objectives.

Why this matters: several of these curves fill gaps the published
breed/husbandry literature does not cover, most importantly the
**age-dependent wind-chill factor**. Aviagen states that young birds
feel more wind-chill than fully-feathered birds but publishes the
relationship only as an unlabelled graph; this controller ships an
explicit day-indexed curve for it.

Honesty notes
-------------
* These are a controller's DEFAULT curves. A real farm is expected to
  tune them. Treat them as industry-typical starting points, not as
  physical constants.
* Where these disagree with Aviagen (notably the target temperature in
  mid grow-out, and minimum ventilation), PCIS does NOT silently switch.
  The disagreement is surfaced -- see `compare_target_temperature`.
* Units are as displayed on the controller.

Reference
---------
[SKOV-Viper] SKOV A/S, Viper Touch climate controller, broiler
    configuration screens: Climate > Inside temperature, > Humidity,
    > Minimum ventilation, > Minimum/Maximum air speed in tunnel,
    > Chill curve - factor. Transcribed 2026.
"""

from __future__ import annotations

from bisect import bisect_left

#: Day -> house temperature setpoint, C  [SKOV-Viper, Climate > Inside temperature]
INSIDE_TEMPERATURE_C: dict[int, float] = {
    1: 34.0, 7: 30.0, 14: 28.0, 21: 26.0, 28: 23.0, 35: 21.0, 42: 19.0, 49: 19.0,
}

#: Day -> heat offset, C (heating setpoint sits this far BELOW the
#: ventilation setpoint, creating a dead band) [SKOV-Viper]
HEAT_OFFSET_C: dict[int, float] = {
    1: -0.1, 7: -0.2, 14: -0.5, 21: -1.0, 28: -1.0, 35: -1.5, 42: -2.0, 49: -2.0,
}

#: Day -> expected/target relative humidity, %  [SKOV-Viper, Climate > Humidity]
#: NOTE: commercial practice EXPECTS 85% RH late in the cycle. High
#: humidity at day 40+ is normal, not an anomaly -- important context for
#: the Aviagen target-temperature table, which is only tested to 70% RH.
HUMIDITY_PCT: dict[int, float] = {
    1: 50, 7: 50, 14: 60, 21: 65, 28: 70, 35: 77, 42: 85, 49: 85,
}

#: Day -> minimum ventilation, m^3/h per bird  [SKOV-Viper]
MINIMUM_VENTILATION_M3_PER_H_PER_BIRD: dict[int, float] = {
    0: 0.00, 1: 0.16, 2: 0.17, 7: 0.23, 14: 0.31, 21: 0.39, 45: 1.10, 55: 1.38,
}

#: Day -> minimum tunnel air speed, m/s  [SKOV-Viper]
MIN_TUNNEL_AIR_SPEED_MPS: dict[int, float] = {
    0: 0.20, 7: 0.33, 14: 0.47, 21: 0.60, 28: 0.73, 35: 0.87, 42: 1.00, 49: 1.00,
}

#: Maximum tunnel air speed, m/s -- flat across all ages [SKOV-Viper].
#: A hard safety ceiling PCIS previously had no value for.
MAX_TUNNEL_AIR_SPEED_MPS = 4.0

#: Day -> wind-chill factor  [SKOV-Viper, Climate > Chill curve - factor]
#: Higher = the birds feel MORE cooling from the same air speed. Day-old
#: chicks (8.0) are 3.2x as chill-sensitive as day-49 birds (2.5), which
#: is the age dependence Aviagen describes qualitatively but does not
#: tabulate.
CHILL_FACTOR: dict[int, float] = {
    1: 8.0, 7: 7.0, 14: 6.0, 21: 4.5, 28: 3.5, 35: 3.3, 42: 3.0, 49: 2.5,
}

#: The age at which the chill factor is treated as the "fully feathered"
#: reference, so the curve can be used as a RATIO against PCIS's
#: Aviagen-anchored (fully-feathered) wind-chill model rather than as an
#: absolute figure in unstated units.
FEATHERED_REFERENCE_DAY = 49


def _interp(table: dict[int, float], day: float) -> float:
    """Linear interpolation over a day-indexed curve, clamped at the ends."""
    days = sorted(table)
    if day <= days[0]:
        return table[days[0]]
    if day >= days[-1]:
        return table[days[-1]]
    i = bisect_left(days, day)
    d0, d1 = days[i - 1], days[i]
    y0, y1 = table[d0], table[d1]
    return y0 + (y1 - y0) * (day - d0) / (d1 - d0)


def inside_temperature_c(age_days: float) -> float:
    """SKOV house temperature setpoint at this age, C."""
    return _interp(INSIDE_TEMPERATURE_C, age_days)


def expected_humidity_pct(age_days: float) -> float:
    """Humidity a commercial controller EXPECTS at this age, %."""
    return _interp(HUMIDITY_PCT, age_days)


def compare_humidity(age_days: float, indoor_rh_pct: float) -> dict:
    """Measured humidity against what a SKOV Viper Touch would expect.

    Why this is worth having, given SKOV's curve cannot fix the real gap:

    Aviagen's target-temperature table stops at 70% RH, so above that PCIS
    clamps and warns that the target it shows is a floor. That warning is
    honest but abstract -- "outside the tested range" does not tell an
    operator whether 96% is slightly unusual or wildly wrong.

    SKOV's curve answers a DIFFERENT question (what humidity is acceptable
    at this age, not what temperature to hold), so it cannot extend the
    Aviagen table. But it is a working commercial controller's own
    judgement, which makes it a legitimate BENCHMARK: it converts "we have
    no data up here" into "a real controller would consider you N points
    past its limit". Same data, and the second form is actionable.

    Deliberately not fed into any calculation -- it changes no fan count
    and no setpoint. It is context for the operator, and reported as such.
    """
    expected = expected_humidity_pct(age_days)
    excess = indoor_rh_pct - expected
    return {
        "expected_pct": round(expected, 0),
        "measured_pct": round(indoor_rh_pct, 0),
        "excess_pct": round(excess, 0),
        "above_controller_limit": excess > 0.0,
        "source": "SKOV Viper Touch humidity curve",
    }


def minimum_ventilation_m3_per_h_per_bird(age_days: float) -> float:
    return _interp(MINIMUM_VENTILATION_M3_PER_H_PER_BIRD, age_days)


def min_tunnel_air_speed_mps(age_days: float) -> float:
    return _interp(MIN_TUNNEL_AIR_SPEED_MPS, age_days)


def chill_factor(age_days: float) -> float:
    """Wind-chill factor at this age [SKOV-Viper]."""
    return _interp(CHILL_FACTOR, age_days)


def chill_sensitivity_ratio(age_days: float) -> float:
    """How much MORE wind-chill this age feels than a fully-feathered
    bird, as a multiplier (1.0 at day 49, ~3.2 for a day-old chick).

    This ratio -- not the raw factor -- is what PCIS uses, because the
    raw factor's units are not stated on the controller, whereas the
    RATIO between ages is unit-free and is exactly the age dependence
    the Aviagen model is missing.
    """
    return chill_factor(age_days) / CHILL_FACTOR[FEATHERED_REFERENCE_DAY]


def compare_target_temperature(age_days: float, aviagen_target_c: float) -> dict:
    """Compare PCIS's Aviagen-derived target with SKOV's day-based curve.

    They disagree by up to ~4 C in mid grow-out (PCIS colder). PCIS does
    not silently adopt either -- this returns both so the operator can
    see the spread and decide, which is the honest handling of two
    credible sources that differ.
    """
    skov = inside_temperature_c(age_days)
    diff = aviagen_target_c - skov
    return {
        "pcis_aviagen_c": round(aviagen_target_c, 1),
        "skov_controller_c": round(skov, 1),
        "difference_c": round(diff, 1),
        "materially_different": abs(diff) >= 1.5,
        "note": (
            f"PCIS (Aviagen weight-based) says {aviagen_target_c:.1f}C; a SKOV Viper "
            f"controller's default day-curve says {skov:.1f}C — a {abs(diff):.1f}C "
            f"{'colder' if diff < 0 else 'warmer'} setpoint. Aviagen's table flattens "
            "above 1.53 kg while the controller keeps stepping down with age. Use bird "
            "behaviour to settle it; neither figure is wrong for every house."
        ) if abs(diff) >= 1.5 else (
            f"PCIS {aviagen_target_c:.1f}C and SKOV {skov:.1f}C agree within "
            f"{abs(diff):.1f}C."
        ),
    }
