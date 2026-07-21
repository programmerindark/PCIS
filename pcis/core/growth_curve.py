"""Broiler weight-for-age growth curve.

STATUS: Real, primary-source data -- transcribed directly from the
current Aviagen Ross 308/308 FF Performance Objectives booklet (see
citation below), not estimated or fabricated.

Scope note (deliberate, per your instruction to skip the Cobb variety
for now): this module carries **Ross 308/308 FF, as-hatched (mixed
sex) performance only**. There is no Cobb 500 growth table in PCIS and
no code path assumes one -- `FlockRecord.breed` (see `pcis/db/models.py`)
remains a free-text, informational-only field; growth-curve-driven
features (the digital twin) are Ross-308-specific until/unless Cobb
data is added later.

References
----------
[AviagenPO2022]  Aviagen, "Ross 308 / Ross 308 FF: Broiler Performance
    Objectives 2022", As-Hatched Performance table (page 3, metric
    section). Day-by-day on-farm body weight (i.e. feed present in
    intestinal tract), days 0-56, under "good management and
    environmental conditions" per the document's own caveat --
    real-world performance may be lower.
    https://aviagen.com/assets/Tech_Center/Ross_Broiler/RossxRoss308-BroilerPerformanceObjectives2022-EN.pdf
    Retrieved 2026-07-20.
"""

from __future__ import annotations

#: Day -> as-hatched on-farm body weight, grams [AviagenPO2022,
#: As-Hatched Performance table, days 0-56]. Transcribed exactly;
#: values are rounded in the source itself (source's own caveat).
_ROSS_308_AS_HATCHED_WEIGHT_G: dict[int, float] = {
    0: 44, 1: 62, 2: 81, 3: 102, 4: 125, 5: 151, 6: 181, 7: 213,
    8: 249, 9: 288, 10: 330, 11: 376, 12: 425, 13: 477, 14: 533,
    15: 592, 16: 655, 17: 720, 18: 789, 19: 860, 20: 935, 21: 1012,
    22: 1092, 23: 1174, 24: 1258, 25: 1345, 26: 1434, 27: 1524,
    28: 1616, 29: 1710, 30: 1805, 31: 1901, 32: 1999, 33: 2097,
    34: 2196, 35: 2296, 36: 2396, 37: 2496, 38: 2597, 39: 2697,
    40: 2798, 41: 2898, 42: 2998, 43: 3097, 44: 3197, 45: 3295,
    46: 3393, 47: 3490, 48: 3586, 49: 3681, 50: 3776, 51: 3869,
    52: 3961, 53: 4052, 54: 4142, 55: 4230, 56: 4318,
}

#: Valid age range for this table, days.
ROSS_308_MIN_AGE_DAYS = min(_ROSS_308_AS_HATCHED_WEIGHT_G)
ROSS_308_MAX_AGE_DAYS = max(_ROSS_308_AS_HATCHED_WEIGHT_G)


def ross_308_body_weight_kg(age_days: float) -> float:
    """As-hatched Ross 308/308 FF body weight at a given age, kg.

    Linear interpolation between the published daily values
    [AviagenPO2022] for fractional ages; exact table lookup at integer
    days. Refuses to extrapolate outside the published range
    [0, 56] days, matching the "never invent a number" policy used
    throughout PCIS -- if you need a longer grow-out, you would need a
    later-age Aviagen table (not currently loaded) rather than a
    guessed extrapolation.

    Parameters
    ----------
    age_days : float
        Bird age, days since placement (day 0 = day-old chick).

    Returns
    -------
    float
        Body weight, kg.
    """
    if age_days < ROSS_308_MIN_AGE_DAYS or age_days > ROSS_308_MAX_AGE_DAYS:
        raise ValueError(
            f"age_days={age_days} is outside the published Aviagen "
            f"Ross 308 as-hatched table range [{ROSS_308_MIN_AGE_DAYS}, "
            f"{ROSS_308_MAX_AGE_DAYS}] days; refusing to extrapolate"
        )
    lower = int(age_days)
    upper = lower + 1
    if upper > ROSS_308_MAX_AGE_DAYS or lower == age_days:
        return _ROSS_308_AS_HATCHED_WEIGHT_G[lower] / 1000.0
    w_lower = _ROSS_308_AS_HATCHED_WEIGHT_G[lower]
    w_upper = _ROSS_308_AS_HATCHED_WEIGHT_G[upper]
    frac = age_days - lower
    return (w_lower + frac * (w_upper - w_lower)) / 1000.0
