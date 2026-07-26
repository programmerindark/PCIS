"""Wind-chill / effective-temperature estimate for broilers.

Moving air makes birds feel cooler than the thermometer reads. This
module estimates that effect from air speed, so the recommendation can
report the temperature the birds actually experience -- not just the
dry-bulb reading.

Source and the honesty it forces
--------------------------------
Everything here is anchored to one cited worked example from Aviagen,
quoted verbatim:

    "if you have air in the house at 90 F (and average humidity) moving
     at 500 feet per minute (about 5.7 mph), it will feel to fully-
     feathered birds like about 80 F air."
        -- Aviagen, "Ross Environmental Management in the Broiler
           House", section on tunnel/wind-chill cooling.

That is the whole of the hard data: 500 ft/min (2.54 m/s) gives about a
10 F (5.6 C) reduction for fully-feathered birds at 90 F ambient. The
same source adds three bounds, also quoted:

  * ceiling -- the effect can reach "as much as 10-12 degrees F";
  * heat limit -- it "becomes less pronounced as air temperatures rise
    much above 90 F, and above 100 F the air begins to warm instead of
    cool the birds";
  * threshold -- "a velocity of at least 500 feet per minute is needed
    for most effective wind-chill cooling."

And, most important, Aviagen's own disclaimer:

    "the 'effective' temperature can only be ESTIMATED, not read from a
     thermometer or CALCULATED. Bird behaviour must be the guide."

So this module does NOT pretend to compute a precise felt temperature.
It returns an estimate tied to the cited anchor, and the shape between
the anchor points (linear from still air to the 2.54 m/s anchor, the
heat taper between 90 and 100 F) is PCIS's interpolation, disclosed as
such -- not Aviagen's. It is deliberately conservative: fully-feathered
birds only, because the greater cooling younger birds feel is shown by
Aviagen only as a graph (Figure 16), with no numbers I can transcribe
honestly, and over-stating cooling for young birds could hide a real
chill-stress risk.

Consequently the recommendation REPORTS effective temperature as an
estimate for the operator; it does not use it to size fans. Aviagen
says bird behaviour is the guide, so auto-driving fans off a number the
manufacturer itself calls uncalculable would over-trust it.
"""

from __future__ import annotations

# --- Cited anchor and bounds (Aviagen, see module docstring) ---------------

#: Air speed of the cited worked example: 500 ft/min. 500 / 197 = 2.538 m/s
#: (Aviagen's own conversion factor, "feet per minute / 197 = m/s").
ANCHOR_AIR_SPEED_MPS = 2.54

#: Effective-temperature reduction at the anchor speed for fully-feathered
#: birds: 90 F -> 80 F = 10 F = 5.56 C.
ANCHOR_COOLING_C = 5.6

#: Upper bound from "as much as 10-12 degrees F" (12 F = 6.67 C). The
#: estimate is capped here; faster air is not assumed to keep cooling
#: linearly without limit.
MAX_COOLING_C = 6.7

#: Above this ambient the effect starts to fade ("less pronounced ... much
#: above 90 F"). 90 F = 32.2 C.
HEAT_FADE_START_C = 32.2

#: At/above this ambient no wind-chill cooling is credited ("above 100 F
#: the air begins to warm instead of cool"). 100 F = 37.8 C. PCIS holds
#: the estimate at zero here rather than modelling warming, which has no
#: cited magnitude.
HEAT_FADE_END_C = 37.8


def effective_temperature_drop_c(air_temp_c: float, air_speed_mps: float) -> float:
    """Estimated wind-chill temperature reduction, C, for FULLY-FEATHERED
    birds. Always >= 0.

    Anchored to Aviagen's worked example (see module docstring). The
    speed response is linear from still air (0 C) to the cited anchor
    (2.54 m/s -> 5.6 C), capped at the cited 6.7 C ceiling, and tapered
    to zero between 90 F and 100 F ambient. It is an ESTIMATE, not a
    measurement.
    """
    if air_speed_mps <= 0.0:
        return 0.0

    base = ANCHOR_COOLING_C * (air_speed_mps / ANCHOR_AIR_SPEED_MPS)
    base = min(base, MAX_COOLING_C)

    if air_temp_c >= HEAT_FADE_END_C:
        heat_factor = 0.0
    elif air_temp_c <= HEAT_FADE_START_C:
        heat_factor = 1.0
    else:
        span = HEAT_FADE_END_C - HEAT_FADE_START_C
        heat_factor = (HEAT_FADE_END_C - air_temp_c) / span

    return max(0.0, base * heat_factor)


def effective_temperature_c(air_temp_c: float, air_speed_mps: float) -> float:
    """The temperature fully-feathered birds are estimated to FEEL:
    dry-bulb air temperature minus the wind-chill reduction.

    An estimate to inform the operator, not a driver of the fan
    recommendation -- see module docstring.
    """
    return air_temp_c - effective_temperature_drop_c(air_temp_c, air_speed_mps)


# ---------------------------------------------------------------------------
# Age dependence
# ---------------------------------------------------------------------------
# The module above is deliberately fully-feathered-only, because Aviagen
# shows the younger-bird relationship as an unlabelled graph (Figure 16)
# with no transcribable numbers. A SKOV Viper Touch controller ships an
# explicit day-indexed "chill curve factor", which supplies exactly that
# missing shape -- see `pcis.core.skov_reference`.
#
# PCIS uses the RATIO between ages (unit-free), not the raw factor, and
# applies it to the Aviagen-anchored drop. So the magnitude stays
# anchored to the cited Aviagen worked example while the age dependence
# comes from the controller curve.


#: How far the wind-chill CEILING may grow for age-sensitive (young)
#: birds, as a multiple of the cited fully-feathered ceiling. PCIS
#: engineering judgment: the SKOV chill curve implies up to 3.2x, but
#: applying that to the ceiling would imply ~21 C of chill, which is not
#: a defensible estimate. Bounded to 2x and disclosed.
AGE_CAP_MULTIPLIER = 2.0


def effective_temperature_drop_for_age_c(
    air_temp_c: float, air_speed_mps: float, age_days: float
) -> float:
    """Wind-chill reduction adjusted for bird age, C.

    Young birds feel substantially MORE chill from the same air speed
    (a day-old chick roughly 3.2x a day-49 bird). Ignoring that is why
    a single fully-feathered figure understates chill risk for chicks.

    Still an ESTIMATE: the magnitude is Aviagen's, the age shape is a
    controller default, and Aviagen's own caveat (bird behaviour is the
    guide) continues to apply.
    """
    from pcis.core import skov_reference as skov

    base_uncapped = ANCHOR_COOLING_C * (air_speed_mps / ANCHOR_AIR_SPEED_MPS) if air_speed_mps > 0 else 0.0
    ratio = skov.chill_sensitivity_ratio(age_days)

    # Age scales the RESPONSE to air speed, but must NOT break the cited
    # ceiling. Aviagen states the effect reaches "as much as 10-12 F"
    # (MAX_COOLING_C) -- that is the only published bound we have, and
    # multiplying it by the age ratio produced 9.3 C at day 29, i.e. an
    # estimate larger than the source permits. The ratio therefore only
    # acts below the ceiling (which is exactly where young birds operate,
    # at 0.2-0.6 m/s); the ceiling itself stays as published.
    scaled = min(base_uncapped * ratio, MAX_COOLING_C)

    # Re-apply the cited high-temperature taper.
    if air_temp_c >= HEAT_FADE_END_C:
        heat_factor = 0.0
    elif air_temp_c <= HEAT_FADE_START_C:
        heat_factor = 1.0
    else:
        heat_factor = (HEAT_FADE_END_C - air_temp_c) / (HEAT_FADE_END_C - HEAT_FADE_START_C)
    return max(0.0, scaled * heat_factor)


#: Relative humidity above which the wind-chill estimate is flagged as
#: OPTIMISTIC. Aviagen's anchor is explicitly measured at "(and average
#: humidity)". Birds shed heat by panting, which is evaporative, so in
#: near-saturated air a given air speed delivers LESS relief than the
#: anchor implies. PCIS does not invent a correction factor -- no source
#: publishes one -- it flags the estimate and deducts confidence.
WINDCHILL_HUMIDITY_CAVEAT_RH_PCT = 70.0


def windchill_estimate_is_optimistic(rh_pct: float) -> bool:
    """True when RH is above the humidity the cited anchor was measured
    at, so the felt-temperature estimate should be read as optimistic."""
    return rh_pct > WINDCHILL_HUMIDITY_CAVEAT_RH_PCT


def effective_temperature_for_age_c(
    air_temp_c: float, air_speed_mps: float, age_days: float
) -> float:
    """Felt temperature accounting for bird age (see above)."""
    return air_temp_c - effective_temperature_drop_for_age_c(
        air_temp_c, air_speed_mps, age_days
    )


# ---------------------------------------------------------------------------
# Uncertainty band
# ---------------------------------------------------------------------------
# Felt temperature is the ONLY output that responds to fan speed -- THI and
# the comfort index ignore air movement entirely -- so it is operationally
# essential even though it is an estimate. The honest presentation is
# therefore a RANGE rather than a falsely precise single figure.
#
# The band's width reflects the two known unmodelled effects:
#   * humidity  -- the cited anchor is at "average humidity"; in
#     near-saturated air panting fails and the birds feel WARMER than the
#     estimate (so the band opens upward, toward dry-bulb);
#   * age/feathering -- the SKOV chill curve is a controller default.
# PCIS does not invent a correction; it states how far the true value could
# plausibly sit from the estimate, and which way.


def felt_temperature_band(
    air_temp_c: float,
    air_speed_mps: float,
    age_days: float | None = None,
    rh_pct: float = 60.0,
) -> dict:
    """Felt temperature as a range: (likely, warm bound, cool bound).

    `warm_c` is the pessimistic end (birds feel hotter than estimated) and
    is capped at the dry-bulb temperature -- moving air cannot make birds
    feel warmer than still air at the same temperature.
    """
    if age_days is None:
        drop = effective_temperature_drop_c(air_temp_c, air_speed_mps)
    else:
        drop = effective_temperature_drop_for_age_c(air_temp_c, air_speed_mps, age_days)
    likely = air_temp_c - drop

    # Above the anchor's humidity, credit progressively less of the drop.
    # At saturation, assume as little as half the estimated benefit.
    if rh_pct > WINDCHILL_HUMIDITY_CAVEAT_RH_PCT:
        span = max(1e-6, 100.0 - WINDCHILL_HUMIDITY_CAVEAT_RH_PCT)
        over = min(1.0, (rh_pct - WINDCHILL_HUMIDITY_CAVEAT_RH_PCT) / span)
        credited = 1.0 - 0.5 * over          # 100% -> 50% of the drop
    else:
        credited = 1.0
    warm = air_temp_c - drop * credited
    cool = likely - 0.5                       # small downside allowance

    return {
        "likely_c": round(likely, 1),
        "warm_bound_c": round(min(warm, air_temp_c), 1),
        "cool_bound_c": round(cool, 1),
        "band_width_c": round(min(warm, air_temp_c) - cool, 1),
        "widened_by_humidity": rh_pct > WINDCHILL_HUMIDITY_CAVEAT_RH_PCT,
    }
