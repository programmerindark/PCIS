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
from pcis.core import heating as htg
from pcis.core import psychrometrics as psy
from pcis.core import target_airspeed as tas
from pcis.core import ventilation_solver as vs
from pcis.core import wind_chill as wc
from pcis.equipment.cooling_pad import CoolingPad, leaving_air_state
from pcis.equipment.fan_curve import FanCurve

#: Degrees C by which outdoor temperature must exceed the comfort
#: target before pads are recommended. PCIS engineering judgment
#: (a small buffer so pads don't cycle on right at the boundary), not
#: a literature value.
PAD_ACTIVATION_MARGIN_C = 1.0

#: Minimum humidity-ratio difference (kg water / kg dry air) between the
#: target indoor state and the incoming supply air for ventilation to be
#: a PRACTICAL moisture-removal mechanism.
#:
#: The moisture mass balance is airflow = load / (W_indoor - W_supply),
#: so as the supply air approaches the indoor absolute humidity the
#: required airflow tends to infinity. Mathematically correct, but
#: operationally meaningless: it produced a spike where a house needing
#: 8 fans at 26 C appeared to need 20 fans at 20 C, purely because the
#: incoming air happened to sit just below the target humidity ratio.
#: Below this threshold PCIS reports that ventilation cannot control
#: moisture at these conditions (the humidity analogue of
#: TARGET_UNREACHABLE) instead of demanding unbounded airflow.
#: 0.5 g/kg is PCIS engineering judgment, not a literature value.
MOISTURE_MIN_HUMIDITY_RATIO_DIFF = 0.0005

#: Explanation attached whenever the target indoor temperature cannot
#: be reached by ventilation at the current supply-air state. Kept as a
#: named constant so the GUI, PDF report, digital twin, and CLI all
#: state this identically rather than paraphrasing a safety-relevant
#: caveat differently in four places.
TARGET_UNREACHABLE_WARNING = (
    "WARNING -- TARGET NOT REACHABLE: the air entering the house is at or above "
    "the target indoor temperature, so no amount of ventilation can bring the "
    "house to target. Ventilation moves indoor conditions toward the supply-air "
    "state; it cannot cool below it. The fan count above is what the sensible-"
    "heat equation returns for the assumed temperature rise -- read it as "
    "'run what you have', NOT as a setting that will achieve target. Closing "
    "this gap needs more evaporative cooling capacity, a lower supply-air "
    "temperature, or accepting a higher indoor temperature. More fans will not "
    "do it."
)

#: Confidence-score deductions. PCIS engineering judgment, not
#: literature values -- see module docstring.
CONFIDENCE_DEDUCTION_PAD_150MM_DESIGN_POINT = 15.0
CONFIDENCE_DEDUCTION_PAD_100MM_DESIGN_POINT = 25.0
CONFIDENCE_DEDUCTION_CO2_DEFAULT_OUTDOOR_PPM = 10.0
CONFIDENCE_DEDUCTION_COMPOSITE_COMFORT_INDEX = 5.0
CONFIDENCE_DEDUCTION_RH_OUTSIDE_TABLE_RANGE = 10.0


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
    target_unreachable : bool
        True when `supply_air_t_c` is at or above the comfort target
        temperature, meaning ventilation physically cannot bring the
        house to target regardless of fan count. When this is True,
        `fans_on` should be read as "run what you have", not as a
        setting that achieves target -- see `TARGET_UNREACHABLE_WARNING`,
        which is also appended to `explanation`.

        Deliberately NOT folded into `confidence_score`: the confidence
        score means "how well-sourced are the numbers behind this",
        and unreachability is not an uncertainty -- it is a physical
        fact the model is entirely confident about. Deducting for it
        would blur a well-defined meaning and would also, perversely,
        make the app look *less* sure exactly when it is *most* sure
        something is wrong. It gets its own flag instead.
    confidence_score : float
        0-100, see module docstring.
    delivered_airflow_m3_per_h : float | None
        What the recommended fans actually move (fans_on x per-fan
        airflow at the design static pressure). This is >= the required
        airflow, because fan count is rounded up -- so it, not the
        requirement, is what the birds actually experience.
    cross_section_area_m2 : float | None
        The tunnel end-profile the air passes through (house width x
        height). Only set when the caller supplies house geometry.
    effective_temp_c : float | None
        Estimated temperature the (fully-feathered) birds FEEL at the
        indoor dry-bulb temperature and the computed air speed -- the
        wind-chill effect (see `pcis.core.wind_chill`). NONE unless an
        air speed was computed.

        An ESTIMATE for the operator, anchored to Aviagen's worked
        example, NOT a driver of the fan recommendation: Aviagen states
        this figure "can only be estimated, not calculated", so the fan
        sizing stays on the solid airflow/heat-balance physics and this
        is reported alongside.
    air_speed_mps : float | None
        Bulk tunnel air velocity = delivered airflow / cross-section
        (the continuity equation Q = V.A). NONE unless a cross-section
        was supplied.

        Reported, NOT yet acted on. This is the number that differs for
        the same airflow in a wide vs. a narrow house, which the earlier
        airflow-only output could not show. Its cooling EFFECT on the
        birds (effective/felt temperature) needs a cited wind-chill
        table and is deliberately not modelled here -- adding the felt-
        temperature effect without that source would be inventing it.

        It is a NOMINAL figure: it assumes air fills the full width x
        height profile uniformly. Real velocity at bird level varies
        with house design and obstructions. Flagged, not fudged.
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
    target_unreachable: bool = False
    delivered_airflow_m3_per_h: float | None = None
    cross_section_area_m2: float | None = None
    air_speed_mps: float | None = None
    effective_temp_c: float | None = None
    target_airspeed_mps: float | None = None
    vpd_kpa: float = 0.0
    achievable_indoor_t_c: float | None = None
    moisture_control_limited: bool = False
    felt_comfort_index: float | None = None
    heating_needed: bool = False
    heat_deficit_w: float = 0.0
    heater_duty_fraction: float | None = None
    heater_undersized: bool = False
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
    house_cross_section_m2: float | None = None,
    heater_capacity_w: float | None = None,
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
    if ce.target_temperature_rh_is_clamped(indoor_rh_pct):
        confidence -= CONFIDENCE_DEDUCTION_RH_OUTSIDE_TABLE_RANGE
        explanation.append(
            f"-{CONFIDENCE_DEDUCTION_RH_OUTSIDE_TABLE_RANGE:.0f} confidence: "
            f"indoor RH ({indoor_rh_pct:.0f}%) is outside the Aviagen target-"
            f"temperature table's tested range ({ce.AVIAGEN_TARGET_TEMP_RH_MIN:.0f}-"
            f"{ce.AVIAGEN_TARGET_TEMP_RH_MAX:.0f}%). The target temperature below "
            "was computed using the nearest tested RH as a floor, not the real "
            "value -- at RH above 70% the true target is likely LOWER than shown "
            "(more cooling needed), so treat pad/fan sizing here as a minimum, "
            "and lean on the THI reading (unaffected by this limitation) as the "
            "more trustworthy heat-stress signal at high humidity."
        )
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

    # --- Is the target physically achievable at all? ---------------------
    # Checked here, after the supply-air state is settled (post-pad if
    # pads are on), because that is the coldest air the house can
    # possibly be fed. If even that is at/above target, no fan count
    # reaches target and saying so is more useful than a number.
    target_unreachable = supply_t_c >= target_temp
    # The coldest the house can actually be held: ventilation can never
    # cool below the supply air it is fed. Every bird-facing readout
    # (felt temperature, comfort, THI) is evaluated here, NOT at the
    # requested target, so a hot day reports what the birds really get.
    achievable_indoor_t_c = max(indoor_t_c, supply_t_c)
    if target_unreachable:
        explanation.append(
            f"{TARGET_UNREACHABLE_WARNING} (supply air {supply_t_c:.1f}C vs "
            f"target {target_temp:.1f}C -- a {supply_t_c - target_temp:.1f}C gap.)"
        )

    # --- Governing airflow requirement ----------------------------------
    requirements: dict[str, float] = {}
    if net.net_sensible_w > 0:
        requirements["sensible_heat"] = vs.required_airflow_for_sensible_heat(
            net.net_sensible_w, delta_t_c, supply_t_c, supply_rh_pct
        )
    # Moisture: evaluated at the achievable indoor state (the exhaust air
    # is at the temperature the house actually holds), and guarded against
    # the near-singularity described at MOISTURE_MIN_HUMIDITY_RATIO_DIFF.
    w_target = psy.humidity_ratio_from_relative_humidity(achievable_indoor_t_c, indoor_rh_pct)
    w_supply = psy.humidity_ratio_from_relative_humidity(supply_t_c, supply_rh_pct)
    moisture_control_limited = (w_target - w_supply) < MOISTURE_MIN_HUMIDITY_RATIO_DIFF
    if moisture_control_limited:
        explanation.append(
            f"Moisture: incoming air ({w_supply * 1000:.1f} g/kg) is nearly as humid as "
            f"the target indoor state ({w_target * 1000:.1f} g/kg), so ventilation cannot "
            "practically remove moisture here -- each m3 of fresh air carries almost as "
            "much water in as the air it replaces. The moisture constraint is therefore "
            "NOT used to size fans at these conditions (it would demand unbounded "
            "airflow); dehumidification or warmer supply air is the real lever."
        )
    else:
        try:
            requirements["moisture"] = vs.required_airflow_for_moisture(
                net.moisture_kg_per_h, achievable_indoor_t_c, indoor_rh_pct,
                supply_t_c, supply_rh_pct,
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
    min_ventilation_m3_per_h = min_vent_per_bird * bird_count
    requirements["minimum_ventilation"] = min_ventilation_m3_per_h

    # --- Target tunnel air speed (wind-chill cooling) -------------------
    # Unlike the felt/effective temperature (which Aviagen says cannot be
    # calculated, so PCIS only reports it), a target air VELOCITY is a
    # published operational setpoint and so may legitimately size fans.
    # When it governs, the fans are staged to move air fast enough over
    # the birds, not merely to exchange heat. See target_airspeed.py.
    target_air = tas.recommended_airspeed(
        body_weight_kg, supply_t_c, target_temp, indoor_rh_pct
    )
    if (
        house_cross_section_m2 is not None
        and house_cross_section_m2 > 0
        and target_air.target_mps > 0
    ):
        requirements["target_airspeed"] = tas.required_airflow_for_airspeed(
            target_air.target_mps, house_cross_section_m2
        )
        explanation.append(target_air.reason)

    # --- Heating (cold-weather / brooding) ------------------------------
    # The cold-weather counterpart of the cooling decision. Uses the same
    # flock heat and envelope loss already computed, plus the heat to warm
    # the minimum-ventilation air (which you must still run for air
    # quality). See pcis.core.heating for the energy balance.
    heat_req = htg.heating_requirement(
        flock, envelope_loss, min_ventilation_m3_per_h,
        indoor_t_c, outdoor_t_c, outdoor_rh_pct,
        heater_capacity_w=heater_capacity_w,
    )
    if heat_req.heating_needed:
        msg = (
            f"HEATING NEEDED: the house loses {(heat_req.envelope_loss_w + heat_req.ventilation_loss_w)/1000:.1f} kW "
            f"(envelope {heat_req.envelope_loss_w/1000:.1f} + warming ventilation air "
            f"{heat_req.ventilation_loss_w/1000:.1f}) but the birds make only "
            f"{heat_req.bird_sensible_heat_w/1000:.1f} kW, so heaters must supply "
            f"{heat_req.heat_deficit_w/1000:.1f} kW to hold {indoor_t_c:.1f}C "
            "[house energy balance, see heating.py]."
        )
        if heat_req.heater_duty_fraction is not None:
            if heat_req.heater_undersized:
                msg += (
                    f" WARNING: the installed heater cannot meet this even running "
                    f"continuously (needs {heat_req.heater_duty_fraction*100:.0f}% of a "
                    "bigger heater)."
                )
            else:
                msg += f" Run the heater about {heat_req.heater_duty_fraction*100:.0f}% of the time."
        explanation.append(msg)

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

    # --- Tunnel air speed (continuity: V = Q / A) -----------------------
    # The airflow the recommended fans actually push -- >= required,
    # because fan count is rounded up. This, not the requirement, is
    # what moves past the birds.
    delivered_airflow = fans_on * fan_flow
    air_speed_mps: float | None = None
    effective_temp_c: float | None = None
    if house_cross_section_m2 is not None and house_cross_section_m2 > 0:
        air_speed_mps = vs.tunnel_airspeed(delivered_airflow, house_cross_section_m2)
        explanation.append(
            f"Tunnel air speed: {delivered_airflow:,.0f} m3/h through a "
            f"{house_cross_section_m2:.1f} m2 cross-section = {air_speed_mps:.2f} m/s "
            "(continuity, V = airflow / area). Note: for the SAME airflow a "
            "narrower house gives a higher velocity -- this is why cross-section, "
            "not airflow alone, sets the air speed the birds feel. This is a "
            "NOMINAL full-profile figure; real velocity at bird level varies with "
            "house design and obstructions."
        )
        # Wind-chill / effective temperature -- an estimate for the
        # operator, NOT a driver of the fan decision.
        #
        # IMPORTANT: this is evaluated at the temperature the house can
        # ACTUALLY hold (`achievable_indoor_t_c`), not at the requested
        # target. Ventilation cannot cool below the air it is fed, so on
        # a hot day the target is unreachable and reporting the felt
        # temperature relative to it would understate what the birds
        # experience by many degrees.
        effective_temp_c = wc.effective_temperature_c(achievable_indoor_t_c, air_speed_mps)
        drop = achievable_indoor_t_c - effective_temp_c
        if drop > 0.05:
            explanation.append(
                f"Wind-chill estimate: at {air_speed_mps:.2f} m/s, fully-feathered "
                f"birds feel about {effective_temp_c:.1f}C rather than the {achievable_indoor_t_c:.1f}C "
                f"dry-bulb ({drop:.1f}C cooler) [Aviagen Ross Environmental Management, "
                "500 ft/min ~= 10F anchor]. This is an ESTIMATE, not a measurement -- "
                "Aviagen states effective temperature can only be estimated, not "
                "calculated, and bird behaviour must be the guide. Younger/part-"
                "feathered birds feel MORE and can be chill-stressed. It is reported "
                "here, not used to size fans."
            )
        else:
            explanation.append(
                f"Wind-chill estimate: negligible at {air_speed_mps:.2f} m/s and "
                f"{achievable_indoor_t_c:.1f}C (the effect fades above ~32C and reverses above "
                "~38C) [Aviagen]."
            )
        # Young-chick chill guard: the delivered velocity must stay below
        # the cited 0.15 m/s ceiling for small birds.
        if target_air.ceiling_mps is not None and air_speed_mps > target_air.ceiling_mps:
            explanation.append(
                f"WARNING: delivered air speed {air_speed_mps:.2f} m/s exceeds the "
                f"{target_air.ceiling_mps:g} m/s young-chick ceiling — risk of chilling "
                "small birds [Aviagen 2010]. Reduce fan staging or run minimum "
                "ventilation only."
            )

    # --- Comfort assessment ---------------------------------------------
    w_indoor = psy.humidity_ratio_from_relative_humidity(achievable_indoor_t_c, indoor_rh_pct)
    twb_indoor = psy.wet_bulb_temperature(achievable_indoor_t_c, w_indoor)
    vpd_kpa = psy.vapor_pressure_deficit(achievable_indoor_t_c, indoor_rh_pct)
    explanation.append(
        f"Vapor-pressure deficit (VPD) at {achievable_indoor_t_c:.1f}C/{indoor_rh_pct:.0f}% RH = "
        f"{vpd_kpa:.2f} kPa (air's drying power). Low VPD = humid = weak evaporative "
        "cooling, so lean on air velocity rather than pads [Cobb; VPD from psychrometrics.py]."
    )
    comfort = ce.bird_comfort_index(achievable_indoor_t_c, twb_indoor, indoor_rh_pct, body_weight_kg)
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

    # Comfort re-scored at the FELT temperature (what moving air actually
    # buys the birds). Reported alongside the dry-bulb comfort index; it
    # inherits the wind-chill ESTIMATE caveat, so it is a second opinion,
    # not a replacement.
    if effective_temp_c is not None:
        w_felt = psy.humidity_ratio_from_relative_humidity(effective_temp_c, indoor_rh_pct)
        twb_felt = psy.wet_bulb_temperature(effective_temp_c, w_felt)
        felt_comfort_index = ce.bird_comfort_index(
            effective_temp_c, twb_felt, indoor_rh_pct, body_weight_kg
        ).comfort_index
    else:
        felt_comfort_index = comfort.comfort_index

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
        target_unreachable=target_unreachable,
        delivered_airflow_m3_per_h=delivered_airflow,
        cross_section_area_m2=house_cross_section_m2,
        air_speed_mps=air_speed_mps,
        effective_temp_c=effective_temp_c,
        target_airspeed_mps=(
            target_air.target_mps
            if (house_cross_section_m2 and target_air.target_mps > 0)
            else None
        ),
        vpd_kpa=vpd_kpa,
        achievable_indoor_t_c=achievable_indoor_t_c,
        moisture_control_limited=moisture_control_limited,
        felt_comfort_index=felt_comfort_index,
        heating_needed=heat_req.heating_needed,
        heat_deficit_w=heat_req.heat_deficit_w,
        heater_duty_fraction=heat_req.heater_duty_fraction,
        heater_undersized=heat_req.heater_undersized,
        explanation=explanation,
    )
