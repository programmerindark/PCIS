"""Target tunnel air velocity for wind-chill cooling of broilers.

This is the "how fast should the air move over the birds" half of hot-
weather control. It complements `wind_chill.py`: that module estimates
how much COOLER a given air speed makes birds feel (reported, never a
driver); this module says what air speed to AIM FOR, which -- unlike the
uncalculable felt temperature -- is a published operational setpoint and
so may legitimately size fans.

Honesty / sourcing
------------------
Per the project rule, only published air-velocity figures are used. The
graded "fpm-by-exact-age" tables that circulate informally are NOT
published by the primary sources, so this module does NOT invent them.
It anchors instead to the cited endpoints and switches regime at a
disclosed body-weight boundary:

  * Young / small chicks -- a SAFETY CEILING, not a target: floor air
    speed should stay below 0.15 m/s (30 ft/min), because young and
    small chicks are prone to wind-chill chilling.
        [Aviagen, "Environmental Management in the Broiler House" (2010):
         "actual floor/air speed should be less than 0.15 meters per
         second (30 ft per minute)" for young chicks.]

  * Effective wind-chill cooling THRESHOLD: at least 500 ft/min
    (2.54 m/s) is needed for the wind-chill effect to be useful; below
    this, moving air is not credited as cooling.
        [Aviagen, ibid.: "a velocity of at least 500 feet per minute is
         needed for most effective wind-chill cooling."]

  * Tunnel TARGET for fully-feathered birds in heat: 3.0 m/s
    (600 ft/min); and where high humidity blocks pad cooling (RH that
    cannot be brought below ~70%), maintain at least 3.0 m/s as the
    primary cooling lever.
        [Cobb, "Broiler Management Guide": tunnel air is drawn at
         3.0 m/s (600 ft/min); "if relative humidity cannot be reduced
         below 70%, the only solution is to maintain an air velocity of
         at least 3.0 m/s (600 ft/min) or more."]
        [Corroborated by USDA study reproduced in Aviagen (2010) Fig 21:
         600 fpm improved weight gain vs 400 fpm / still air after
         week 4 in hot conditions.]

The one disclosed operational choice is the young/feathered boundary,
set by BODY WEIGHT (the quantity the engine has; it does not carry age):
``FULLY_FEATHERED_WEIGHT_KG = 0.5`` kg, which is about day 14 on the
Aviagen Ross 308 growth curve -- i.e. the end of the brooding window the
0.15 m/s guidance is written for. This boundary is PCIS's, not a number
either source states, and is flagged as such.
"""

from __future__ import annotations

from dataclasses import dataclass

#: Safety ceiling on air speed for young/small chicks, m/s (30 ft/min)
#: [Aviagen 2010]. Not a target -- a limit to protect against chilling.
YOUNG_CHICK_MAX_AIRSPEED_MPS = 0.15

#: Minimum air speed for the wind-chill effect to be useful, m/s
#: (500 ft/min) [Aviagen 2010]. Below this, moving air is not credited
#: as cooling.
EFFECTIVE_WINDCHILL_THRESHOLD_MPS = 2.54

#: Target tunnel air velocity for fully-feathered birds in heat, m/s
#: (600 ft/min) [Cobb].
TUNNEL_TARGET_AIRSPEED_MPS = 3.0

#: Relative humidity above which evaporative pad cooling is impaired and
#: air velocity becomes the primary cooling lever, % [Cobb].
HIGH_RH_THRESHOLD_PCT = 70.0

#: Disclosed body-weight boundary between the young-chick regime (0.15
#: m/s ceiling, no velocity cooling) and the feathered regime (tunnel
#: velocity target when hot). ~day 14 on the Aviagen Ross 308 curve.
#: PCIS's operational choice, NOT a figure stated by Aviagen or Cobb.
FULLY_FEATHERED_WEIGHT_KG = 0.5


@dataclass(frozen=True)
class TargetAirspeed:
    """A target/ceiling air velocity with its cited reasoning.

    target_mps : float
        The air speed to size fans for, m/s. 0.0 when velocity cooling
        is not indicated (young birds, or feathered birds not in heat).
    ceiling_mps : float | None
        A safety maximum, m/s. Set only for young chicks (0.15 m/s); the
        caller should warn if the delivered air speed exceeds it. None
        when no ceiling applies.
    windchill_effective : bool
        Whether ``target_mps`` reaches the cited 2.54 m/s effectiveness
        threshold.
    reason : str
        Human-readable, cited explanation of the regime chosen.
    """

    target_mps: float
    ceiling_mps: float | None
    windchill_effective: bool
    reason: str


def recommended_airspeed(
    body_weight_kg: float,
    air_temp_c: float,
    target_temp_c: float,
    indoor_rh_pct: float,
) -> TargetAirspeed:
    """Target tunnel air velocity for the given bird and conditions.

    Parameters
    ----------
    body_weight_kg : float
        Representative live body weight. Used as the feathering proxy
        (see ``FULLY_FEATHERED_WEIGHT_KG``); the engine carries weight,
        not age.
    air_temp_c : float
        The temperature of the air the birds are in / being fed (e.g.
        the post-pad supply air, or indoor dry-bulb). Compared against
        ``target_temp_c`` to decide whether it is hot enough that
        wind-chill cooling is indicated.
    target_temp_c : float
        The comfort target temperature for these birds (from
        ``comfort_engine.target_temperature``).
    indoor_rh_pct : float
        Indoor relative humidity, % -- used only to note the high-RH
        case where velocity, not pads, must do the cooling [Cobb].

    Returns
    -------
    TargetAirspeed
    """
    # --- Young / small chicks: ceiling, never a cooling target ----------
    if body_weight_kg < FULLY_FEATHERED_WEIGHT_KG:
        return TargetAirspeed(
            target_mps=0.0,
            ceiling_mps=YOUNG_CHICK_MAX_AIRSPEED_MPS,
            windchill_effective=False,
            reason=(
                f"Young/small birds ({body_weight_kg:.3f} kg, below the ~0.5 kg / "
                "~day-14 feathering boundary): keep floor air speed BELOW "
                f"{YOUNG_CHICK_MAX_AIRSPEED_MPS:g} m/s (30 ft/min) — they are prone to "
                "wind-chill chilling [Aviagen 2010]. No velocity cooling target is set; "
                "minimum ventilation for air quality governs instead."
            ),
        )

    # --- Feathered birds: velocity cooling only when it is hot ----------
    if air_temp_c < target_temp_c:
        return TargetAirspeed(
            target_mps=0.0,
            ceiling_mps=None,
            windchill_effective=False,
            reason=(
                f"Air ({air_temp_c:.1f}C) is at/below the target temperature "
                f"({target_temp_c:.1f}C): no wind-chill cooling velocity required. "
                "Ventilation is sized for heat/moisture/air-quality, not air speed."
            ),
        )

    reason = (
        f"Fully-feathered birds with air at {air_temp_c:.1f}C, above the "
        f"{target_temp_c:.1f}C target: aim for {TUNNEL_TARGET_AIRSPEED_MPS:g} m/s "
        "(600 ft/min) tunnel velocity for wind-chill cooling [Cobb]; this is only "
        f"effective at/above {EFFECTIVE_WINDCHILL_THRESHOLD_MPS:g} m/s (500 ft/min) "
        "[Aviagen 2010]."
    )
    if indoor_rh_pct > HIGH_RH_THRESHOLD_PCT:
        reason += (
            f" RH {indoor_rh_pct:.0f}% is above {HIGH_RH_THRESHOLD_PCT:g}% — evaporative "
            "pad cooling is impaired, so air velocity is the primary cooling lever [Cobb]."
        )
    return TargetAirspeed(
        target_mps=TUNNEL_TARGET_AIRSPEED_MPS,
        ceiling_mps=None,
        windchill_effective=True,
        reason=reason,
    )


def required_airflow_for_airspeed(target_mps: float, cross_section_m2: float) -> float:
    """Airflow needed to move air across the house at ``target_mps``,
    m^3/h, by continuity (Q = V.A).

    The inverse of the reported tunnel air speed V = Q / A. Returns 0.0
    when there is no target or no cross-section.
    """
    if target_mps <= 0.0 or cross_section_m2 <= 0.0:
        return 0.0
    return target_mps * cross_section_m2 * 3600.0
