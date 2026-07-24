"""Bird-centred status dashboard: how the birds are likely to be doing.

This is the "next level" view -- instead of only "run N fans", it turns
the already-computed climate numbers into a small set of bird-centred
readouts: a comfort score, a heat-stress risk, the estimated felt
(effective) temperature, a panting indicator, and a relative water-
intake estimate.

Honesty / sourcing -- read this before trusting any number here
------------------------------------------------------------------
Two of these readouts are well grounded and reuse already-cited PCIS
components; two are explicitly ESTIMATES and are labelled as such both
here and in what the function returns:

  * comfort_score / comfort_label -- taken straight from
    `comfort_engine.bird_comfort_index`, PCIS's own composite (itself
    flagged there as a synthesis, not a validated published index).
  * heat_stress_risk -- a direct relabel of the cited THI stress class
    [Tao & Xin 2003 / Duduyemi 2012 via comfort_engine].
  * effective_bird_temp_c -- the wind-chill felt-temperature ESTIMATE
    from `wind_chill.py`, which Aviagen states can only be estimated,
    not calculated. Reported, never a control driver.
  * panting_index -- an ESTIMATE keyed to the cited observation that
    broiler open-mouth panting "typically occurs when temperatures
    approach or exceed 30 C" [MSU/UF-IFAS heat-stress extension]. The
    band boundaries around that onset are PCIS's, disclosed.
  * water_intake_multiplier -- an ESTIMATE of intake RELATIVE to
    thermoneutral, from the cited extension figure that broiler water
    use rises ~6-7% for each degree F above ~70 F, saturating at the
    cited 2-4x range under heat stress [MSU Extension, "Water-Related
    Factors in Broiler Production"]. It is a multiplier, not an absolute
    L/min, because an absolute figure needs the flock's own measured
    baseline intake, which PCIS does not have and will not invent.

Nothing here feeds back into fan sizing; it is a read-only dashboard.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from pcis.core import comfort_engine as ce
from pcis.core import psychrometrics as psy
from pcis.core import wind_chill as wc

# --- Comfort score banding (PCIS labels, disclosed) ------------------------
_COMFORT_GOOD_MIN = 85.0
_COMFORT_FAIR_MIN = 60.0

# --- THI stress class -> plain risk label [cited class, see comfort_engine]
_HEAT_RISK_BY_THI_CLASS = {
    "comfort": "Low",
    "heat_stress": "Moderate",
    "severe_heat_stress": "High",
}

# --- Panting onset [MSU/UF-IFAS extension: ~30 C] --------------------------
PANTING_ONSET_C = 30.0

# --- Water intake vs temperature [MSU Extension] ---------------------------
#: Thermoneutral reference below which no heat-driven increase is applied.
WATER_BASE_TEMP_F = 70.0
#: Fractional intake rise per degree F above the base (~6-7%/F cited; the
#: mid value is used).
WATER_RISE_PER_F = 0.065
#: Cited ceiling: heat-stressed birds drink about 2-4x normal; capped at 4.
WATER_MAX_MULTIPLIER = 4.0


def _c_to_f(t_c: float) -> float:
    return t_c * 9.0 / 5.0 + 32.0


@dataclass(frozen=True)
class BirdStatus:
    """A read-only, bird-centred status snapshot.

    comfort_score : float
        0-100, from `comfort_engine` (PCIS composite).
    comfort_label : str
        "Good" / "Fair" / "Poor" band of ``comfort_score``.
    heat_stress_risk : str
        "Low" / "Moderate" / "High", relabelled from the cited THI class.
    effective_bird_temp_c : float | None
        Estimated felt temperature (wind-chill), or None if no air speed
        was available. An ESTIMATE.
    panting_index : str
        "Minimal" / "Mild" / "Moderate" / "Severe" -- an ESTIMATE keyed
        to the ~30 C panting-onset observation.
    water_intake_multiplier : float
        Estimated water intake relative to thermoneutral (1.0 = normal),
        an ESTIMATE; capped at the cited 4x.
    is_estimate : dict[str, bool]
        Which fields are estimates (True) vs grounded reuse (False), so
        the UI can label them honestly.
    notes : list[str]
        Cited, human-readable notes.
    """

    comfort_score: float
    comfort_label: str
    heat_stress_risk: str
    effective_bird_temp_c: float | None
    panting_index: str
    water_intake_multiplier: float
    is_estimate: dict = field(default_factory=dict)
    notes: list = field(default_factory=list)


def _comfort_label(score: float) -> str:
    if score >= _COMFORT_GOOD_MIN:
        return "Good"
    if score >= _COMFORT_FAIR_MIN:
        return "Fair"
    return "Poor"


def _panting_index(felt_temp_c: float) -> str:
    """Estimated panting severity from the temperature the birds feel.

    Anchored to the cited ~30 C open-mouth-panting onset; the +/- bands
    around it are PCIS's, disclosed.
    """
    if felt_temp_c < PANTING_ONSET_C - 3.0:      # < 27 C
        return "Minimal"
    if felt_temp_c < PANTING_ONSET_C:            # 27-30 C: approaching onset
        return "Mild"
    if felt_temp_c < PANTING_ONSET_C + 3.0:      # 30-33 C: at/above onset
        return "Moderate"
    return "Severe"                              # >= 33 C


def water_intake_multiplier(air_temp_c: float) -> float:
    """Estimated water intake relative to thermoneutral (1.0 = normal).

    From the cited extension figure of ~6.5% more intake per degree F
    above ~70 F, capped at the cited 2-4x heat-stress range. An ESTIMATE
    of the RELATIVE change; absolute L/min needs the flock's measured
    baseline (not invented here).
    """
    t_f = _c_to_f(air_temp_c)
    if t_f <= WATER_BASE_TEMP_F:
        return 1.0
    mult = 1.0 + WATER_RISE_PER_F * (t_f - WATER_BASE_TEMP_F)
    return min(mult, WATER_MAX_MULTIPLIER)


def assess(
    comfort: ce.ComfortAssessment,
    air_temp_c: float,
    effective_temp_c: float | None,
) -> BirdStatus:
    """Assemble the bird-status dashboard from already-computed climate.

    Parameters
    ----------
    comfort : ComfortAssessment
        From `comfort_engine.bird_comfort_index` -- supplies the comfort
        score and the cited THI stress class.
    air_temp_c : float
        The dry-bulb temperature the birds are in (for the water estimate
        and, as a fallback, panting).
    effective_temp_c : float | None
        The wind-chill felt temperature estimate, if available; used for
        the panting estimate (birds pant to what they FEEL, so moving air
        that lowers the felt temperature lowers panting).
    """
    score = comfort.comfort_index
    risk = _HEAT_RISK_BY_THI_CLASS.get(comfort.thi_class, "Moderate")

    felt = effective_temp_c if effective_temp_c is not None else air_temp_c
    panting = _panting_index(felt)
    water = water_intake_multiplier(air_temp_c)

    notes = [
        "Comfort score and heat-stress risk reuse PCIS's cited comfort index / "
        "THI class (comfort_engine).",
    ]
    if effective_temp_c is not None:
        notes.append(
            "Panting is estimated from the FELT (wind-chill) temperature — moving "
            "air that lowers felt temperature lowers panting."
        )
    notes.append(
        f"Panting onset anchored to ~{PANTING_ONSET_C:.0f}C [MSU/UF-IFAS extension]; "
        "band boundaries are PCIS's. ESTIMATE."
    )
    if water > 1.0:
        notes.append(
            f"Water intake est. ~{water:.1f}x thermoneutral (~6.5%/°F above 70°F, "
            "capped at the cited 2–4x) [MSU Extension]. RELATIVE estimate; absolute "
            "L/min needs your flock's measured baseline. ESTIMATE."
        )

    return BirdStatus(
        comfort_score=score,
        comfort_label=_comfort_label(score),
        heat_stress_risk=risk,
        effective_bird_temp_c=effective_temp_c,
        panting_index=panting,
        water_intake_multiplier=water,
        is_estimate={
            "comfort_score": False,
            "heat_stress_risk": False,
            "effective_bird_temp_c": True,
            "panting_index": True,
            "water_intake_multiplier": True,
        },
        notes=notes,
    )


def from_recommendation(rec) -> BirdStatus:
    """Bird status for a single `recommendation_engine.Recommendation`,
    evaluated at the REALISTIC indoor temperature.

    The engine computes comfort at the *target* indoor temperature -- the
    best case if ventilation reaches target. But ventilation can never
    cool the house below the air it is fed, so on a hot day when the
    target is unreachable the birds actually sit near the supply-air
    temperature, not the target. Reporting comfort at target there would
    read "perfect" on a 37 C day, which is exactly the misleading result
    a bird-centred dashboard must avoid. So this re-evaluates comfort,
    felt temperature, panting and water at

        realistic_indoor = max(target_temp, supply_air_temp)

    -- the coldest the house can actually be held. (Duck-typed on `rec`
    to avoid a circular import with the engine.)
    """
    target = rec.comfort.target_temp_c
    rh_pct = rec.comfort.rh_pct
    weight = rec.comfort.body_weight_kg
    realistic_t = max(target, rec.supply_air_t_c)

    if realistic_t <= target + 1e-9:
        comfort = rec.comfort  # house holds target; reuse as-is
    else:
        w = psy.humidity_ratio_from_relative_humidity(realistic_t, rh_pct)
        twb = psy.wet_bulb_temperature(realistic_t, w)
        comfort = ce.bird_comfort_index(realistic_t, twb, rh_pct, weight)

    effective = None
    if rec.air_speed_mps is not None:
        effective = wc.effective_temperature_c(realistic_t, rec.air_speed_mps)

    status = assess(comfort, realistic_t, effective)
    if realistic_t > target + 0.1:
        status.notes.append(
            f"Evaluated at the realistic {realistic_t:.1f}C the house can actually hold "
            f"(target {target:.1f}C is unreachable when supply air is warmer), not the "
            "optimistic target."
        )
    return status
