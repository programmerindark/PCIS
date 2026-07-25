"""The AI Advisor: turn a Recommendation into one prioritised action.

The dashboard shows many numbers; the advisor answers the operator's
real question -- "what is the single most important thing to do right
now, and what will it achieve?". It is NOT a black box and NOT machine
learning: it is a small, transparent decision layer over the already-
cited engine. Every action it names and every predicted number comes
from `recommendation_engine` / `bird_status` -- so it inherits the
engine's honesty (including the rule that air speed changes the FELT
temperature and panting, but not the THI-based comfort score, because
Aviagen says felt temperature cannot be calculated).

Bird-first: it prefers the most impactful SAFE action. It will not, for
example, push air speed on young chicks (the engine already flags the
0.15 m/s chill ceiling), and it treats cold (heating) as more urgent
than fine-tuning cooling.
"""

from __future__ import annotations

from dataclasses import dataclass

from pcis.core import bird_status as bs
from pcis.core import comfort_engine as ce
from pcis.core import psychrometrics as psy


@dataclass(frozen=True)
class Advice:
    """One prioritised action plus its predicted, engine-computed effect.

    category : str
        heating | capacity | cooling_airspeed | cooling_pads |
        ventilation | chill_guard | hold
    headline : str
        The action, in a few words (e.g. "Run 8 of 10 fans").
    detail : str
        One sentence of operator-facing context.
    why : str
        The engine's reason (governing factor / key warning).
    confidence : float
        The engine's confidence score for the underlying numbers.
    feel_before_c / feel_after_c : float | None
        Felt (wind-chill) temperature with NO added air movement vs. with
        the recommended fans -- the honest benefit of acting.
    panting_before / panting_after : str
        Estimated panting at those two states.
    comfort_score : float
        The (temperature/THI-based) comfort score at the realistic indoor
        temperature. Shown for context; unchanged by air speed by design.
    heat_stress_risk : str
    """

    category: str
    headline: str
    detail: str
    why: str
    confidence: float
    feel_before_c: float | None
    feel_after_c: float | None
    panting_before: str
    panting_after: str
    comfort_score: float
    heat_stress_risk: str


def _comfort_at(realistic_t: float, rec) -> ce.ComfortAssessment:
    target = rec.comfort.target_temp_c
    if realistic_t <= target + 1e-9:
        return rec.comfort
    rh = rec.comfort.rh_pct
    w = psy.humidity_ratio_from_relative_humidity(realistic_t, rh)
    twb = psy.wet_bulb_temperature(realistic_t, w)
    return ce.bird_comfort_index(realistic_t, twb, rh, rec.comfort.body_weight_kg)


def advise(rec, installed_fans: int, pads_installed: bool) -> Advice:
    """Choose the single best action for a Recommendation `rec`.

    `installed_fans` and `pads_installed` describe the equipment the
    operator actually has, so the advice is grounded in what they can do.
    """
    target = rec.comfort.target_temp_c
    realistic_t = max(target, rec.supply_air_t_c)
    comfort = _comfort_at(realistic_t, rec)

    # Two honest states, BOTH evaluated at the realistic indoor
    # temperature: still air (no fans) vs the recommended air movement.
    # `from_recommendation` computes the felt temperature at the realistic
    # temperature (so wind-chill correctly fades in extreme heat) rather
    # than at the optimistic target.
    before = bs.assess(comfort, realistic_t, effective_temp_c=realistic_t)
    after = bs.from_recommendation(rec)

    why = f"Governing factor: {rec.governing_constraint.replace('_', ' ')}."
    if rec.target_unreachable:
        why += " Ventilation cannot cool below the air it is fed — this is a physical limit, not a fan-count issue."

    base = dict(
        confidence=rec.confidence_score,
        feel_before_c=before.effective_bird_temp_c,
        feel_after_c=after.effective_bird_temp_c,
        panting_before=before.panting_index,
        panting_after=after.panting_index,
        comfort_score=after.comfort_score,
        heat_stress_risk=after.heat_stress_risk,
    )

    fans = rec.fans_on
    short = installed_fans > 0 and fans > installed_fans

    # 1) Cold weather wins: heating is the priority.
    if rec.heating_needed:
        kw = rec.heat_deficit_w / 1000.0
        if rec.heater_duty_fraction is not None and not rec.heater_undersized:
            head = f"Run the heater (~{rec.heater_duty_fraction * 100:.0f}% of the time)"
        elif rec.heater_undersized:
            head = f"Add heater capacity — need ~{kw:.0f} kW"
        else:
            head = f"Add supplemental heat (~{kw:.0f} kW)"
        return Advice(category="heating", headline=head,
                      detail=f"The house is losing more heat than the birds make; heat is needed to hold {target:.1f}°C.",
                      why=why, **base)

    # 2) Fan shortfall: name it, but still say what to run now.
    if short:
        return Advice(category="capacity",
                      headline=f"Run all {installed_fans} fans — capacity short",
                      detail=f"Conditions call for {fans} fans but only {installed_fans} are installed; add capacity to fully cool the birds.",
                      why=why, **base)

    # 3) Comfortable and safe: hold.
    comfortable = after.heat_stress_risk == "Low" and after.comfort_label in ("Good", "Fair") and not rec.target_unreachable
    if comfortable and not rec.pads_on and (rec.target_airspeed_mps is None):
        return Advice(category="hold",
                      headline="Hold — conditions are on target",
                      detail=f"Run {fans} fan(s); comfort is {after.comfort_score:.0f}% and heat-stress is low.",
                      why=why, **base)

    # 4) Tunnel cooling by air speed (feathered birds in heat).
    if rec.target_airspeed_mps and rec.target_airspeed_mps > 0:
        return Advice(category="cooling_airspeed",
                      headline=f"Run {fans} of {installed_fans} fans for tunnel cooling",
                      detail=f"Push air over the birds at ~{rec.target_airspeed_mps:g} m/s — wind-chill drops the felt temperature.",
                      why=why, **base)

    # 5) Evaporative pad cooling is doing the work.
    if rec.pads_on:
        return Advice(category="cooling_pads",
                      headline=f"Run cooling pads + {fans} fans",
                      detail="Humidity is low enough that evaporative pads cool effectively.",
                      why=why, **base)

    # 6) Plain ventilation.
    return Advice(category="ventilation",
                  headline=f"Run {fans} of {installed_fans} fans",
                  detail="Ventilate for heat, moisture and air quality.",
                  why=why, **base)
