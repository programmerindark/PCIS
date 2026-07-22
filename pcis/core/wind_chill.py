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
