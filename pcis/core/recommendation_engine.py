"""Recommendation engine: fan staging and cooling-pad on/off decisions.

Ties together the engineering core (psychrometrics, bird metabolism,
heat/moisture balance, ventilation solver, comfort engine) and the
equipment database (fan curves, cooling pads) into a single
recommendation: how many fans to run, whether pads should be on, and
why -- with a transparent, explainable confidence score.

Design logic
------------
1. Compute the house's net sensible/latent/moisture/CO2 loads
   (`heat_moisture_balance`).
2. Decide whether evaporative cooling is needed at all: plain
   ventilation can only pull indoor temperature down toward outdoor
   ambient temperature, never below it. So if the outdoor dry-bulb
   temperature already exceeds the comfort target temperature (from
   `comfort_engine.target_temperature`) by more than a margin, no
   amount of ventilation alone can hit the target -- pads are needed.
   This is a real, standard piece of ventilation engineering logic
   (not a fabricated rule), though the specific margin constant is
   PCIS engineering judgment -- see `PAD_ACTIVATION_MARGIN_C` below.
3. If pads are on, the air entering the sensible-heat ventilation
   calculation is the pad's leaving-air state
   (`cooling_pad.leaving_air_state`), not raw outdoor air.
4. Required airflow is the governing (largest) of the sensible-heat,
   moisture, CO2, and Aviagen-minimum-ventilation requirements
   (`ventilation_solver`).
5. Fan count is sized from the loaded `FanCurve` catalog at a
   caller-specified design static pressure (this module does not
   invent a "typical" static pressure -- it must be supplied, since I
   do not have a verified generic figure for it).
6. A confidence score (0-100) is computed transparently: it starts at
   100 and specific, named deductions are applied for each place the
   recommendation had to lean on an assumption rather than a
   precisely cited number (e.g. the cooling pad's single design-point
   efficiency assumption, rather than a full manufacturer curve -- see
   `pcis.equipment.cooling_pad` module docstring). Every deduction is
   returned in the `Recommendation.explanation` list, so the score is
   never a black box.

This module does not introduce new engineering constants of its own;
it composes the already-cited functions in `heat_moisture_balance`,
`ventilation_solver`, `comfort_engine`, `fan_curve`, and `cooling_pad`.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from pcis.core import comfort_engine as ce
from pcis.core import heat_moisture_balance as hmb
from pcis.core import psychrometrics as psy
from pcis.core import ventilation_solver as vs
from pcis.equipment.cooling_pad import CoolingPad, leaving_air_state
from pcis.equipment.fan_curve import FanCurve

#: Degrees C by which outdoor temperature must exceed the comfort
#: target before pads are recommended. PCIS engineering judgment
#: (a small buffer so pads don't cycle on right at the boundary), not
#: a literature value.
PAD_ACTIVATION_MARGIN_C = 1.0

#: Confidence-score deductions. PCIS engineering judgment, not
#: literature values -- see module docstring.
CONFIDENCE_DEDUCTION_PAD_150MM_DESIGN_POINT = 15.0
CONFIDENCE_DEDUCTION_PAD_100MM_DESIGN_POINT = 25.0
CONFIDENCE_DEDUCTION_CO2_DEFAULT_OUTDOOR_PPM = 10.0
CONFIDENCE_DEDUCTION_COMPOSITE_COMFORT_INDEX = 5.0


@dataclass(frozen=True)
class Recommendation:
    """A fan-staging / pad on/off recommendation with explanation.

    fans_on : int
        Number of fans to run at the given static pressure.
    pads_on : bool
        Whether evaporative cooling pads should be active.
    required_airflow_m3_per_h : float
        The governing (largest) airflow requirement.
    governing_constraint : str
        Which requirement governs: "sensible_heat", "moisture", "co2",
        or "minimum_ventilation".
    supply_air_t_c, supply_air_rh_pct : float
        The temperature/RH of the air actually entering the house
        (post-pad if pads_on, else outdoor conditions).
    comfort : ComfortAssessment
        Full comfort breakdown at the current indoor conditions (see
        `pcis.core.comfort_engine`).
    confidence_score : float
        0-100, see module docstring.
    explanation : list[str]
        Human-readable engineering explanation, including every
        confidence deduction and its reason.
    """

    fans_on: int
    pads_on: bool
    required_airflow_m3_per_h: float
    governing_constraint: str
    supply_air_t_c: float
    supply_air_rh_pct: float
    comfort: ce.ComfortAssessment
    confidence_score: float
    explanation: list[str] = field(default_factory=list)


def recommend(
    bird_count: int,
    body_weight_kg: float,
    indoor_t_c: float,
    indoor_rh_pct: float,
    outdoor_t_c: float,
    outdoor_rh_pct: float,
    envelope_surfaces: list[hmb.Surface],
    fan: FanCurve,
    design_static_pressure_pa: float,
    delta_t_c: float,
    cooling_pad: CoolingPad | None = None,
    outdoor_co2_ppm: float = 420.0,
) -> Recommendation:
    """Produce a fan-staging / pad on/off recommendation.

    Parameters
    ----------
    bird_count : int
        Number of birds in the house.
    body_weight_kg : float
        Representative live body weight, kg.
    indoor_t_c, indoor_rh_pct : float
        Current/target indoor conditions.
    outdoor_t_c, outdoor_rh_pct : float
        Current outdoor conditions.
    envelope_surfaces : list[Surface]
        House envelope for conduction-loss calculation (see
        `heat_moisture_balance.Surface`).
    fan : FanCurve
        The fan model to size against (see `pcis.equipment.fan_curve`).
    design_static_pressure_pa : float
        The static pressure to evaluate the fan curve at. Not
        defaulted -- must reflect your actual house's static pressure
        design point.
    delta_t_c : float
        Allowed temperature rise across the house (indoor target minus
        supply air temperature) used for the sensible-heat ventilation
        calculation.
    cooling_pad : CoolingPad, optional
        If provided, used both to decide whether pads should activate
        and, if so, to compute the pad-leaving air state. If None,
        pads are never recommended (the house is assumed to have none
        installed).
    outdoor_co2_ppm : float, optional
        Ambient outdoor CO2, ppm. Defaults to 420 ppm -- see
        `ventilation_solver.co2_ventilation_requirement` for the same
        caveat about this drifting over time/location.

    Returns
    -------
    Recommendation
    """
    explanation: list[str] = []
    confidence = 100.0

    flock = hmb.flock_load(bird_count, body_weight_kg, indoor_t_c)
    envelope_loss = hmb.total_envelope_conduction_loss(envelope_surfaces, indoor_t_c, outdoor_t_c)
    net = hmb.net_house_load(flock, envelope_loss)

    explanation.append(
        f"Flock of {bird_count} birds @ {body_weight_kg} kg produces "
        f"{flock.sensible_heat_w/1000:.1f} kW sensible / "
        f"{flock.latent_heat_w/1000:.1f} kW latent heat and "
        f"{flock.moisture_kg_per_h:.1f} kg/h moisture "
        "[CIGR (2002) via bird_metabolism.py]."
    )
    explanation.append(
        f"Envelope conduction: {envelope_loss/1000:+.2f} kW "
        "(positive = loss to outside, negative = heat gain from outside)."
    )
    explanation.append(f"Net sensible load ventilation must handle: {net.net_sensible_w/1000:.1f} kW.")

    # --- Decide whether pads are needed ---------------------------------
    target_temp = ce.target_temperature(body_weight_kg, indoor_rh_pct)
    pads_needed = (
        cooling_pad is not None and outdoor_t_c > target_temp + PAD_ACTIVATION_MARGIN_C
    )

    if pads_needed:
        pad_state = leaving_air_state(outdoor_t_c, outdoor_rh_pct, cooling_pad.assumed_saturation_efficiency)
        supply_t_c, supply_rh_pct = pad_state.t_c, pad_state.rh_pct
        explanation.append(
            f"Outdoor temp ({outdoor_t_c:.1f}C) exceeds the comfort target "
            f"({target_temp:.1f}C) by more than {PAD_ACTIVATION_MARGIN_C}C -- "
            "plain ventilation cannot reach target, so pads are recommended ON. "
            f"Pad-leaving supply air: {supply_t_c:.1f}C / {supply_rh_pct:.0f}% RH "
            f"(assumed {cooling_pad.assumed_saturation_efficiency*100:.0f}% "
            "saturation efficiency)."
        )
        if cooling_pad.depth_mm >= 150.0:
            confidence -= CONFIDENCE_DEDUCTION_PAD_150MM_DESIGN_POINT
            explanation.append(
                f"-{CONFIDENCE_DEDUCTION_PAD_150MM_DESIGN_POINT:.0f} confidence: "
                "pad efficiency is a single design-point assumption from MSU "
                "Extension guidance, not a manufacturer velocity-dependent "
                "curve (see cooling_pad.py docstring)."
            )
        else:
            confidence -= CONFIDENCE_DEDUCTION_PAD_100MM_DESIGN_POINT
            explanation.append(
                f"-{CONFIDENCE_DEDUCTION_PAD_100MM_DESIGN_POINT:.0f} confidence: "
                "this pad depth's efficiency figure is an unverified "
                "interpolated estimate, not a cited value (see "
                "cooling_pad.py docstring)."
            )
    else:
        supply_t_c, supply_rh_pct = outdoor_t_c, outdoor_rh_pct
        reason = "no cooling pad supplied" if cooling_pad is None else "outdoor temp within comfort margin of target"
        explanation.append(f"Pads not recommended ({reason}).")

    # --- Governing airflow requirement ----------------------------------
    requirements: dict[str, float] = {}
    if net.net_sensible_w > 0:
        requirements["sensible_heat"] = vs.required_airflow_for_sensible_heat(
            net.net_sensible_w, delta_t_c, supply_t_c, supply_rh_pct
        )
    if indoor_rh_pct > supply_rh_pct or indoor_t_c != supply_t_c:
        try:
            requirements["moisture"] = vs.required_airflow_for_moisture(
                net.moisture_kg_per_h, indoor_t_c, indoor_rh_pct, supply_t_c, supply_rh_pct
            )
        except ValueError:
            pass  # supply air already more humid than indoor target; moisture doesn't govern
    requirements["co2"] = vs.co2_ventilation_requirement(flock.co2_m3_per_h, outdoor_ppm=outdoor_co2_ppm)
    if outdoor_co2_ppm == 420.0:
        confidence -= CONFIDENCE_DEDUCTION_CO2_DEFAULT_OUTDOOR_PPM
        explanation.append(
            f"-{CONFIDENCE_DEDUCTION_CO2_DEFAULT_OUTDOOR_PPM:.0f} confidence: "
            "using the default 420 ppm outdoor CO2 background rather than a "
            "locally measured value."
        )
    min_vent_per_bird = vs.minimum_ventilation_rate_aviagen(body_weight_kg)
    requirements["minimum_ventilation"] = min_vent_per_bird * bird_count

    governing_constraint = max(requirements, key=requirements.get)
    required_airflow = requirements[governing_constraint]
    explanation.append(
        "Airflow requirements (m3/h): "
        + ", ".join(f"{k}={v:,.0f}" for k, v in requirements.items())
        + f" -> governing constraint: {governing_constraint} "
        f"({required_airflow:,.0f} m3/h)."
    )

    fan_flow = fan.airflow_at_static_pressure(design_static_pressure_pa)
    fans_on = vs.required_fan_count(required_airflow, fan_flow)
    explanation.append(
        f"{fan.manufacturer} {fan.model} delivers {fan_flow:,.0f} m3/h at "
        f"{design_static_pressure_pa:.0f} Pa -> {fans_on} fan(s) needed."
    )

    # --- Comfort assessment ---------------------------------------------
    w_indoor = psy.humidity_ratio_from_relative_humidity(indoor_t_c, indoor_rh_pct)
    twb_indoor = psy.wet_bulb_temperature(indoor_t_c, w_indoor)
    comfort = ce.bird_comfort_index(indoor_t_c, twb_indoor, indoor_rh_pct, body_weight_kg)
    confidence -= CONFIDENCE_DEDUCTION_COMPOSITE_COMFORT_INDEX
    explanation.append(
        f"-{CONFIDENCE_DEDUCTION_COMPOSITE_COMFORT_INDEX:.0f} confidence: "
        "comfort_index is PCIS's own composite synthesis, not a validated "
        "published instrument (see comfort_engine.py docstring)."
    )
    explanation.append(
        f"Comfort assessment: target={comfort.target_temp_c:.1f}C, "
        f"deviation={comfort.deviation_c:+.1f}C, THI={comfort.thi:.1f} "
        f"({comfort.thi_class}), comfort_index={comfort.comfort_index:.0f}/100."
    )

    confidence = max(0.0, min(100.0, confidence))

    return Recommendation(
        fans_on=fans_on,
        pads_on=pads_needed,
        required_airflow_m3_per_h=required_airflow,
        governing_constraint=governing_constraint,
        supply_air_t_c=supply_t_c,
        supply_air_rh_pct=supply_rh_pct,
        comfort=comfort,
        confidence_score=confidence,
        explanation=explanation,
    )
