"""Digital twin: simulate fan/pad staging across time, not just "right now".

Purpose
-------
`recommendation_engine.recommend()` answers one question: "given these
exact conditions at this exact moment, how many fans and should pads
be on?" A working farm operator needs the next question answered too:

    "how many fans, at what time, should be on for how long?"

That is what this module does. It steps through a sequence of moments
(hours of a day, or days of a grow-out), evaluates the already-tested
recommendation engine at each one, and returns the resulting schedule
plus summary statistics (peak fan count, fan-hours, pad-hours, when
staging changes).

What this module does NOT invent
--------------------------------
This is the important part, and it is a deliberate design constraint
rather than an omission:

1. **Weather is caller-supplied, never synthesized.** There is no
   built-in "typical diurnal temperature curve" here, because a
   defensible one would be site-, season-, and climate-specific, and
   I have no cited source for one that would apply to your houses.
   You pass in the outdoor temperature/RH for each step (from your own
   records, a weather file, or a sensitivity scenario you want to
   test). If PCIS generated that profile itself, every number
   downstream would inherit a fabricated input -- exactly what this
   project refuses to do.

2. **Bird weight comes from the real Aviagen table.** Weight at each
   step is `growth_curve.ross_308_body_weight_kg(age_days)`
   [AviagenPO2022], not a fitted curve of my own. Ages outside the
   published 0-56 day range raise rather than extrapolate.

3. **The indoor target temperature comes from the real Aviagen
   target-temperature table** (`comfort_engine.target_temperature`),
   driven by the bird weight above. This is the mechanism that makes
   the schedule change as the flock ages: younger/lighter birds want a
   warmer house, older/heavier birds a cooler one, so the same outdoor
   weather produces different fan staging at day 7 than at day 42.

4. **No new engineering constants.** Every number this module produces
   comes from `recommendation_engine.recommend()`, which in turn
   composes the already-cited `heat_moisture_balance`,
   `ventilation_solver`, `comfort_engine`, `fan_curve`, and
   `cooling_pad` functions. This module is scheduling/orchestration
   logic only.

Two behaviours that look like bugs but are not
-----------------------------------------------
Both of these were found by the test suite while building this module,
and are recorded here because an operator reading the output would
reasonably be surprised by them.

**1. Fan requirement is NOT always monotonic in bird age.** Running a
fixed 30C / 50% RH day across a grow-out produces, for one real house
configuration, 3 fans at day 7 but only 2 at day 14 -- fewer fans for
bigger birds. That is not an error: at day 7 the governing constraint
is *moisture removal*, while from day 14 on it is *sensible heat*.
Those two requirements are computed from different physics and do not
cross over smoothly, so the total requirement can dip at the handover.
`SimulationStep.recommendation.governing_constraint` tells you which
one is in charge at every step, and it is worth looking at whenever
the schedule does something counterintuitive.

**2. Very young birds can fall below a published table's floor.** The
Aviagen growth curve starts at 0.044 kg (day 0), but the Aviagen
minimum-ventilation table starts at 0.05 kg, and PCIS refuses to
extrapolate below a published range. So day 0 (and any fractional age
below roughly day 0.4) cannot be simulated at all. This is a genuine
gap between two Aviagen publications, not a PCIS limitation I can fix
by choosing a number -- see `MIN_SIMULATABLE_AGE_DAYS` below, which
detects it up front and says so plainly instead of failing deep inside
the ventilation solver with a confusing message.

Known limitation (flagged, not hidden)
--------------------------------------
This is an **open-loop** simulation: at each step it asks "what does
the house need?", not "what would actually happen to the indoor
climate if I ran N fans for an hour?". The indoor condition at each
step is the *target* setpoint, assumed to be met. That is the correct
model for answering "what should I schedule", and it is what the
operator's question asks for.

It is NOT a closed-loop thermal simulation, which would additionally
solve the achieved indoor temperature/humidity when installed fan
capacity is insufficient to hit the target (e.g. a house with 8 fans
physically installed on a day that needs 14). `installed_fan_count`
below detects and flags that shortfall so it is never silently
ignored, but PCIS does not currently model how far the house would
actually drift above setpoint in that case -- that requires a
transient energy-balance integration over the house's thermal mass,
and PCIS has no cited thermal-mass figures for your houses. Flagging
this rather than implementing a plausible-looking approximation.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from pcis.core import comfort_engine as ce
from pcis.core import growth_curve as gc
from pcis.core import heat_moisture_balance as hmb
from pcis.core import recommendation_engine as rec_engine
from pcis.core import ventilation_solver as vs
from pcis.equipment.cooling_pad import CoolingPad
from pcis.equipment.fan_curve import FanCurve


def _min_simulatable_age_days() -> float:
    """Youngest age whose published body weight is still within the
    Aviagen minimum-ventilation table's range.

    Derived (not hardcoded) by walking the published growth curve until
    its weight reaches the minimum-ventilation table's floor, so if
    either table is ever corrected the constant follows automatically
    instead of silently going stale. See module docstring, point 2.
    """
    floor_kg = vs.AVIAGEN_MIN_VENT_MIN_WEIGHT_KG
    for day in range(gc.ROSS_308_MIN_AGE_DAYS, gc.ROSS_308_MAX_AGE_DAYS + 1):
        if gc.ross_308_body_weight_kg(float(day)) >= floor_kg:
            return float(day)
    raise RuntimeError(  # pragma: no cover - would mean the tables no longer overlap at all
        "No age in the Aviagen growth curve reaches the minimum-ventilation "
        "table's weight floor; the two published tables no longer overlap."
    )


#: Youngest bird age the twin can simulate -- see module docstring,
#: point 2. Below this the Aviagen minimum-ventilation table has no
#: published value and PCIS will not extrapolate.
MIN_SIMULATABLE_AGE_DAYS = _min_simulatable_age_days()

#: Re-exported from `recommendation_engine` so the twin's schedule
#: warning is word-for-word identical to the one the single-shot
#: Recommendation tab shows. Defined there, not here, because the
#: detection itself lives in the engine -- the twin just reports
#: `Recommendation.target_unreachable` rather than re-deriving the rule
#: (two copies of a safety check is one copy too many).
TARGET_UNREACHABLE_NOTE = rec_engine.TARGET_UNREACHABLE_WARNING


def _validate_age(age_days: float) -> None:
    """Raise a clear, self-explaining error for ages the twin cannot
    simulate, rather than letting a confusing one surface from deep
    inside the ventilation solver.
    """
    if age_days < MIN_SIMULATABLE_AGE_DAYS:
        weight_kg = gc.ross_308_body_weight_kg(age_days)
        raise ValueError(
            f"age_days={age_days:g} cannot be simulated: at that age the "
            f"published Aviagen body weight is {weight_kg:.3f} kg, which is below "
            f"the {vs.AVIAGEN_MIN_VENT_MIN_WEIGHT_KG} kg floor of the Aviagen "
            f"minimum-ventilation table. The earliest simulatable age is day "
            f"{MIN_SIMULATABLE_AGE_DAYS:g}. This is a gap between two Aviagen "
            "publications, not a value PCIS is willing to invent -- see the "
            "digital_twin.py module docstring."
        )


@dataclass(frozen=True)
class OutdoorCondition:
    """Outdoor weather at one point in the simulation.

    Supplied by the caller -- see the module docstring on why this
    module never synthesizes a weather profile of its own.

    label : str
        How this step is identified in the output schedule, e.g.
        "06:00" for an hour-of-day run or "day 21" for a grow-out run.
        Free text: the module treats it as an opaque tag, so you can
        use whatever time convention your records use.
    """

    label: str
    t_c: float
    rh_pct: float


@dataclass(frozen=True)
class SimulationStep:
    """The result of evaluating one step of the simulation.

    target_unreachable : bool
        True when the supply air entering the house is already at or
        above the target indoor temperature -- meaning NO amount of
        ventilation can bring the house to target, because ventilation
        can only move indoor conditions toward the supply-air state,
        never past it. See `TARGET_UNREACHABLE_NOTE` for why this
        matters and what the reported `fans_on` means in that case.
    """

    label: str
    age_days: float
    body_weight_kg: float
    outdoor_t_c: float
    outdoor_rh_pct: float
    target_indoor_t_c: float
    fans_on: int
    pads_on: bool
    capacity_shortfall: bool
    target_unreachable: bool
    heating_needed: bool
    heater_duty_fraction: float | None
    recommendation: rec_engine.Recommendation


@dataclass(frozen=True)
class ScheduleBlock:
    """A run of consecutive steps sharing the same fan/pad staging.

    This is the "for how long" half of the operator's question: rather
    than 24 separate hourly rows, consecutive hours needing the same
    staging are collapsed into one block.

    n_steps : int
        How many consecutive simulation steps this block spans. In
        real time that is `n_steps * step_duration_h` (the caller knows
        their own step spacing -- this module does not assume one).
    """

    fans_on: int
    pads_on: bool
    heating_needed: bool
    start_label: str
    end_label: str
    n_steps: int


@dataclass(frozen=True)
class SimulationResult:
    """A full simulated schedule plus summary statistics."""

    steps: list[SimulationStep]
    blocks: list[ScheduleBlock]
    peak_fans_on: int
    fan_steps: int
    pad_steps: int
    shortfall_steps: int
    heating_steps: int = 0
    unreachable_steps: int = 0
    notes: list[str] = field(default_factory=list)

    def fan_hours(self, step_duration_h: float) -> float:
        """Total fan-run time, in fan-hours.

        Multiplies each step's fan count by the step duration and sums,
        so 4 fans for 2 hours = 8 fan-hours. `step_duration_h` is
        caller-supplied because this module never assumes how far apart
        your steps are (hourly, 15-minute, daily).
        """
        if step_duration_h <= 0:
            raise ValueError(f"step_duration_h must be positive, got {step_duration_h}")
        return sum(s.fans_on for s in self.steps) * step_duration_h

    def pad_hours(self, step_duration_h: float) -> float:
        """Total cooling-pad run time, in hours."""
        if step_duration_h <= 0:
            raise ValueError(f"step_duration_h must be positive, got {step_duration_h}")
        return self.pad_steps * step_duration_h


def simulate_schedule(
    conditions: list[OutdoorCondition],
    age_days: float,
    bird_count: int,
    envelope_surfaces: list[hmb.Surface],
    fan: FanCurve,
    design_static_pressure_pa: float,
    delta_t_c: float,
    indoor_rh_pct: float,
    cooling_pad: CoolingPad | None = None,
    outdoor_co2_ppm: float = 420.0,
    installed_fan_count: int | None = None,
    heater_capacity_w: float | None = None,
    house_cross_section_m2: float | None = None,
) -> SimulationResult:
    """Simulate fan/pad staging across a sequence of outdoor conditions
    at a fixed bird age -- i.e. "a day in the life" of the house.

    Use this to answer "how many fans at what time today". For the
    across-the-grow-out view, see `simulate_grow_out`.

    Parameters
    ----------
    conditions : list[OutdoorCondition]
        The outdoor weather at each step, in time order. Caller-
        supplied (see module docstring).
    age_days : float
        Bird age for this simulated day. Drives body weight
        [AviagenPO2022] and therefore the indoor target temperature.
    indoor_rh_pct : float
        The indoor relative humidity to evaluate against. Held constant
        across the simulation -- PCIS does not model how indoor RH
        would itself drift over the day (that would require the same
        closed-loop model discussed in the module docstring), so this
        is your assumed/measured operating humidity.
    installed_fan_count : int, optional
        How many fans are physically installed. If given, any step
        whose required fan count exceeds it is flagged
        (`SimulationStep.capacity_shortfall`) and counted in
        `SimulationResult.shortfall_steps`. `fans_on` still reports the
        number actually NEEDED, not the capped number -- capping it
        would hide the shortfall, which is the opposite of useful.

    Returns
    -------
    SimulationResult

    Raises
    ------
    ValueError
        If `conditions` is empty, or `age_days` is outside the
        published Aviagen table range (no extrapolation -- see
        `growth_curve`).
    """
    if not conditions:
        raise ValueError("conditions must contain at least one OutdoorCondition")

    _validate_age(age_days)
    body_weight_kg = gc.ross_308_body_weight_kg(age_days)
    target_indoor_t_c = ce.target_temperature(body_weight_kg, indoor_rh_pct)

    notes: list[str] = [
        f"Bird age {age_days:g} days -> body weight {body_weight_kg:.3f} kg "
        "[Aviagen Ross 308 Performance Objectives 2022].",
        f"Indoor target temperature {target_indoor_t_c:.1f}C at {indoor_rh_pct:.0f}% RH "
        "[Aviagen target-temperature table via comfort_engine].",
        "Outdoor conditions are caller-supplied, not synthesized by PCIS.",
    ]
    if ce.target_temperature_rh_is_clamped(indoor_rh_pct):
        notes.append(
            f"NOTE: indoor RH {indoor_rh_pct:.0f}% is outside the Aviagen target-"
            f"temperature table's tested range "
            f"({ce.AVIAGEN_TARGET_TEMP_RH_MIN:.0f}-{ce.AVIAGEN_TARGET_TEMP_RH_MAX:.0f}%); "
            "the target above was clamped to the nearest tested edge. Treat this "
            "schedule as a minimum -- see comfort_engine.py docstring."
        )

    steps: list[SimulationStep] = []
    for cond in conditions:
        rec = rec_engine.recommend(
            bird_count=bird_count,
            body_weight_kg=body_weight_kg,
            indoor_t_c=target_indoor_t_c,
            indoor_rh_pct=indoor_rh_pct,
            outdoor_t_c=cond.t_c,
            outdoor_rh_pct=cond.rh_pct,
            envelope_surfaces=envelope_surfaces,
            fan=fan,
            design_static_pressure_pa=design_static_pressure_pa,
            delta_t_c=delta_t_c,
            cooling_pad=cooling_pad,
            outdoor_co2_ppm=outdoor_co2_ppm,
            heater_capacity_w=heater_capacity_w,
            house_cross_section_m2=house_cross_section_m2,
        )
        shortfall = installed_fan_count is not None and rec.fans_on > installed_fan_count
        steps.append(
            SimulationStep(
                label=cond.label,
                age_days=age_days,
                body_weight_kg=body_weight_kg,
                outdoor_t_c=cond.t_c,
                outdoor_rh_pct=cond.rh_pct,
                target_indoor_t_c=target_indoor_t_c,
                fans_on=rec.fans_on,
                pads_on=rec.pads_on,
                capacity_shortfall=shortfall,
                target_unreachable=rec.target_unreachable,
                heating_needed=rec.heating_needed,
                heater_duty_fraction=rec.heater_duty_fraction,
                recommendation=rec,
            )
        )

    return _summarize(steps, notes, installed_fan_count)


def simulate_grow_out(
    age_days_sequence: list[float],
    outdoor_t_c: float,
    outdoor_rh_pct: float,
    bird_count: int,
    envelope_surfaces: list[hmb.Surface],
    fan: FanCurve,
    design_static_pressure_pa: float,
    delta_t_c: float,
    indoor_rh_pct: float,
    cooling_pad: CoolingPad | None = None,
    outdoor_co2_ppm: float = 420.0,
    installed_fan_count: int | None = None,
    heater_capacity_w: float | None = None,
    house_cross_section_m2: float | None = None,
) -> SimulationResult:
    """Simulate staging across a grow-out: same weather, advancing bird
    age -- i.e. "how does my fan requirement grow as the flock does".

    Holding the weather fixed is deliberate here: it isolates the
    effect of bird age (heavier birds = more heat = more ventilation,
    and a lower target temperature) from the effect of weather. If you
    want both varying together, call `simulate_schedule` per day with
    that day's real weather and combine the results yourself.

    Parameters
    ----------
    age_days_sequence : list[float]
        The bird ages to evaluate, in order (e.g. `[7, 14, 21, 28, 35, 42]`
        or `list(range(0, 43))`). Each must be within the published
        Aviagen range -- no extrapolation.

    Raises
    ------
    ValueError
        If the sequence is empty, or any age is outside the published
        Aviagen table range.
    """
    if not age_days_sequence:
        raise ValueError("age_days_sequence must contain at least one age")

    notes: list[str] = [
        f"Fixed outdoor conditions {outdoor_t_c:.1f}C / {outdoor_rh_pct:.0f}% RH "
        "across the whole grow-out, to isolate the effect of bird age.",
        "Body weight at each age from the Aviagen Ross 308 Performance "
        "Objectives 2022 table; indoor target temperature derived from it "
        "via the Aviagen target-temperature table.",
    ]

    steps: list[SimulationStep] = []
    for age in age_days_sequence:
        _validate_age(age)
        body_weight_kg = gc.ross_308_body_weight_kg(age)
        target_indoor_t_c = ce.target_temperature(body_weight_kg, indoor_rh_pct)
        rec = rec_engine.recommend(
            bird_count=bird_count,
            body_weight_kg=body_weight_kg,
            indoor_t_c=target_indoor_t_c,
            indoor_rh_pct=indoor_rh_pct,
            outdoor_t_c=outdoor_t_c,
            outdoor_rh_pct=outdoor_rh_pct,
            envelope_surfaces=envelope_surfaces,
            fan=fan,
            design_static_pressure_pa=design_static_pressure_pa,
            delta_t_c=delta_t_c,
            cooling_pad=cooling_pad,
            outdoor_co2_ppm=outdoor_co2_ppm,
            heater_capacity_w=heater_capacity_w,
            house_cross_section_m2=house_cross_section_m2,
        )
        shortfall = installed_fan_count is not None and rec.fans_on > installed_fan_count
        steps.append(
            SimulationStep(
                label=f"day {age:g}",
                age_days=age,
                body_weight_kg=body_weight_kg,
                outdoor_t_c=outdoor_t_c,
                outdoor_rh_pct=outdoor_rh_pct,
                target_indoor_t_c=target_indoor_t_c,
                fans_on=rec.fans_on,
                pads_on=rec.pads_on,
                capacity_shortfall=shortfall,
                target_unreachable=rec.target_unreachable,
                heating_needed=rec.heating_needed,
                heater_duty_fraction=rec.heater_duty_fraction,
                recommendation=rec,
            )
        )

    return _summarize(steps, notes, installed_fan_count)


def _summarize(
    steps: list[SimulationStep],
    notes: list[str],
    installed_fan_count: int | None,
) -> SimulationResult:
    """Collapse consecutive same-staging steps into blocks and compute
    summary statistics. Pure bookkeeping -- no engineering logic.
    """
    blocks: list[ScheduleBlock] = []
    for step in steps:
        if (blocks and blocks[-1].fans_on == step.fans_on
                and blocks[-1].pads_on == step.pads_on
                and blocks[-1].heating_needed == step.heating_needed):
            prev = blocks[-1]
            blocks[-1] = ScheduleBlock(
                fans_on=prev.fans_on,
                pads_on=prev.pads_on,
                heating_needed=prev.heating_needed,
                start_label=prev.start_label,
                end_label=step.label,
                n_steps=prev.n_steps + 1,
            )
        else:
            blocks.append(
                ScheduleBlock(
                    fans_on=step.fans_on,
                    pads_on=step.pads_on,
                    heating_needed=step.heating_needed,
                    start_label=step.label,
                    end_label=step.label,
                    n_steps=1,
                )
            )

    shortfall_steps = sum(1 for s in steps if s.capacity_shortfall)
    peak_fans_on = max(s.fans_on for s in steps)
    if installed_fan_count is not None and shortfall_steps:
        notes.append(
            f"WARNING: {shortfall_steps} of {len(steps)} steps require more fans "
            f"than the {installed_fan_count} installed (peak requirement: "
            f"{peak_fans_on}). fans_on reports what is NEEDED, not what the house "
            "can deliver. PCIS does not model how far indoor temperature would "
            "actually drift above target during those steps -- see the "
            "digital_twin.py module docstring."
        )

    unreachable_steps = sum(1 for s in steps if s.target_unreachable)
    if unreachable_steps:
        worst = max(
            (s for s in steps if s.target_unreachable),
            key=lambda s: s.recommendation.supply_air_t_c - s.target_indoor_t_c,
        )
        gap = worst.recommendation.supply_air_t_c - worst.target_indoor_t_c
        notes.append(
            f"WARNING: at {unreachable_steps} of {len(steps)} steps the target "
            f"indoor temperature is physically unreachable (worst: {worst.label}, "
            f"supply air {worst.recommendation.supply_air_t_c:.1f}C vs target "
            f"{worst.target_indoor_t_c:.1f}C -- a {gap:.1f}C gap). "
            + TARGET_UNREACHABLE_NOTE
        )

    heating_steps = sum(1 for s in steps if s.heating_needed)
    if heating_steps:
        notes.append(
            f"HEATING: {heating_steps} of {len(steps)} steps need supplemental heat "
            "(cold enough that the birds cannot keep the house at target on their "
            "own). Minimum-ventilation fans still run for air quality even while "
            "heating -- see the per-step detail."
        )

    return SimulationResult(
        steps=steps,
        blocks=blocks,
        peak_fans_on=peak_fans_on,
        fan_steps=sum(1 for s in steps if s.fans_on > 0),
        pad_steps=sum(1 for s in steps if s.pads_on),
        heating_steps=heating_steps,
        shortfall_steps=shortfall_steps,
        unreachable_steps=unreachable_steps,
        notes=notes,
    )


def format_schedule_table(result: SimulationResult) -> str:
    """Render a `SimulationResult` as a plain-text schedule table.

    Presentation only -- no computation. Useful for the CLI, logs, and
    as the text the GUI/PDF layer can reuse verbatim.
    """
    lines = [
        f"{'Time/Age':<12} {'Outdoor':<16} {'Target':<9} {'Fans':<6} {'Pads':<6} {'Heat':<6}",
        "-" * 62,
    ]
    for s in result.steps:
        flags = ""
        if s.capacity_shortfall:
            flags += " (!capacity)"
        if s.target_unreachable:
            flags += " (!unreachable)"
        if s.heating_needed and s.heater_duty_fraction is not None:
            heat = f"{s.heater_duty_fraction*100:.0f}%"
        elif s.heating_needed:
            heat = "ON"
        else:
            heat = "off"
        lines.append(
            f"{s.label:<12} "
            f"{s.outdoor_t_c:>5.1f}C/{s.outdoor_rh_pct:>3.0f}%    "
            f"{s.target_indoor_t_c:>5.1f}C   "
            f"{s.fans_on:<6}{'ON' if s.pads_on else 'off':<6}{heat:<6}{flags}"
        )
    lines.append("")
    lines.append("Consolidated schedule:")
    for b in result.blocks:
        span = b.start_label if b.n_steps == 1 else f"{b.start_label} - {b.end_label}"
        lines.append(
            f"  {span}: {b.fans_on} fan(s), pads {'ON' if b.pads_on else 'off'}, "
            f"heat {'ON' if b.heating_needed else 'off'} "
            f"({b.n_steps} step{'s' if b.n_steps != 1 else ''})"
        )
    lines.append("")
    lines.append(f"Peak fans required: {result.peak_fans_on}")
    if result.notes:
        lines.append("")
        lines.append("Notes:")
        lines.extend(f"  - {n}" for n in result.notes)
    return "\n".join(lines)
