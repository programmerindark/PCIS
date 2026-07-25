"""Broiler mortality / livability benchmark.

Two honest notes up front, because this is exactly the kind of number
that must not be invented:

1. Aviagen's Ross 308 Broiler *Performance Objectives* booklet -- the
   source PCIS cites for body weight -- does NOT contain a day-by-day
   mortality or livability curve. It carries body weight, gain, feed
   intake, FCR and carcass yield only (its FCR note even states it "does
   not account for mortality"). So there is no "Aviagen livability
   curve" to transcribe, and PCIS does not fabricate one.

2. Instead, the acceptable-mortality line used here is a real, cited,
   day-by-day regulatory benchmark: the EU broiler welfare directive's
   cumulative-mortality formula. It is what the industry already uses to
   judge whether a flock's mortality is within normal limits.

References
----------
[EU2007/43]  Council Directive 2007/43/EC laying down minimum rules for
    the protection of chickens kept for meat production. The cumulative
    daily mortality condition (used for the higher stocking-density
    allowance) is: cumulative mortality must not exceed
        1% + 0.06% x age_of_flock_in_days.
    PCIS uses this as the "acceptable ceiling" a flock should stay under.
[FirstWeek]  Field/'review data (e.g. first-week broiler mortality
    studies) put a good first-week target near 1% and typical whole-cycle
    cumulative mortality around 3% under good management; early daily
    mortality peaks around day 3-4 and should stay under ~0.5%/day, then
    fall below ~0.05%/day after ~day 10. Used only for the "elevated
    today" flag, and labelled as guidance, not a genetic standard.
"""

from __future__ import annotations

from dataclasses import dataclass

#: EU 2007/43/EC cumulative-mortality ceiling: 1% + 0.06% per day.
ACCEPTABLE_BASE_PCT = 1.0
ACCEPTABLE_PER_DAY_PCT = 0.06

#: Guidance threshold for flagging an unusually high single day, % of the
#: live flock [FirstWeek]. Conservative early-life ceiling used generally.
ELEVATED_DAILY_PCT = 0.5


def acceptable_cumulative_mortality_pct(age_days: float) -> float:
    """The acceptable cumulative-mortality ceiling at a given age, %
    [EU2007/43]. A flock at or below this is within normal limits; above
    it warrants investigation."""
    return ACCEPTABLE_BASE_PCT + ACCEPTABLE_PER_DAY_PCT * max(0.0, age_days)


@dataclass(frozen=True)
class MortalityAssessment:
    live_count: int
    cumulative_dead: int
    cumulative_pct: float
    acceptable_pct: float
    within_target: bool
    elevated_today: bool
    daily_pct: float
    note: str


def assess(
    placed: int,
    cumulative_dead: int,
    age_days: float,
    dead_today: int = 0,
) -> MortalityAssessment:
    """Assess a flock's mortality against the cited benchmarks.

    Parameters
    ----------
    placed : int
        Birds originally placed.
    cumulative_dead : int
        Total deaths so far.
    age_days : float
        Flock age in days (drives the EU ceiling).
    dead_today : int
        Deaths logged for the current day (for the "elevated today" flag).
    """
    placed = max(1, placed)
    cumulative_dead = max(0, min(cumulative_dead, placed))
    live = placed - cumulative_dead
    cum_pct = 100.0 * cumulative_dead / placed
    ceiling = acceptable_cumulative_mortality_pct(age_days)

    # Daily rate is relative to the live birds at the start of today.
    live_before_today = max(1, placed - (cumulative_dead - dead_today))
    daily_pct = 100.0 * dead_today / live_before_today
    elevated = daily_pct > ELEVATED_DAILY_PCT

    within = cum_pct <= ceiling
    if not within:
        note = (
            f"Cumulative mortality {cum_pct:.1f}% is ABOVE the acceptable "
            f"{ceiling:.1f}% for day {age_days:g} [EU 2007/43/EC] — investigate "
            "(heat stress, disease, water/feed)."
        )
    elif elevated:
        note = (
            f"Today's loss ({daily_pct:.2f}% of the flock) is elevated "
            f"(> {ELEVATED_DAILY_PCT:g}%/day) — watch closely."
        )
    else:
        note = (
            f"Cumulative {cum_pct:.1f}% is within the acceptable {ceiling:.1f}% "
            f"for day {age_days:g} [EU 2007/43/EC]."
        )

    return MortalityAssessment(
        live_count=live,
        cumulative_dead=cumulative_dead,
        cumulative_pct=round(cum_pct, 2),
        acceptable_pct=round(ceiling, 2),
        within_target=within,
        elevated_today=elevated,
        daily_pct=round(daily_pct, 2),
        note=note,
    )
