"""Pure (Qt-free) logic behind the guided single-page schedule flow.

Everything here is deliberately free of any GUI import so it can be
unit-tested headlessly and reused. It does no engineering of its own:
the target-temperature curve comes straight from the Aviagen table via
`comfort_engine`, the body weights from the Aviagen growth curve, and
the schedule from the already-tested `digital_twin`. This module only
*arranges* those results for a one-screen presentation.
"""

from __future__ import annotations

from dataclasses import dataclass

from pcis.core import comfort_engine as ce
from pcis.core import digital_twin as twin
from pcis.core import growth_curve as gc


@dataclass(frozen=True)
class TargetTempPoint:
    """One point on the day-wise target-house-temperature chart."""

    day: int
    body_weight_kg: float
    target_temp_c: float


def target_temperature_curve(
    indoor_rh_pct: float,
    day_min: int | None = None,
    day_max: int | None = None,
) -> list[TargetTempPoint]:
    """Day-by-day target house temperature across the grow-out.

    For each day in the published Aviagen Ross 308 range, the bird's
    body weight is looked up [AviagenPO2022] and the target house
    temperature derived from it at the given indoor RH [Aviagen target-
    temperature table via `comfort_engine`]. No extrapolation: the range
    is clamped to what the published tables cover.

    Parameters
    ----------
    indoor_rh_pct : float
        Indoor relative humidity the target is evaluated at. If this is
        outside the Aviagen table's tested RH band the returned targets
        are clamped to the nearest tested column -- see
        `comfort_engine.target_temperature_rh_is_clamped`.
    day_min, day_max : int, optional
        Restrict the returned range. Defaults to the full published
        Ross 308 range (0..56 days). Values outside the published range
        are silently clamped to it rather than extrapolated.

    Returns
    -------
    list[TargetTempPoint]
        One entry per whole day, ascending.
    """
    lo = gc.ROSS_308_MIN_AGE_DAYS if day_min is None else max(day_min, gc.ROSS_308_MIN_AGE_DAYS)
    hi = gc.ROSS_308_MAX_AGE_DAYS if day_max is None else min(day_max, gc.ROSS_308_MAX_AGE_DAYS)
    points: list[TargetTempPoint] = []
    for day in range(int(lo), int(hi) + 1):
        weight = gc.ross_308_body_weight_kg(float(day))
        target = ce.target_temperature(weight, indoor_rh_pct)
        points.append(TargetTempPoint(day=day, body_weight_kg=weight, target_temp_c=target))
    return points


def target_rh_is_clamped(indoor_rh_pct: float) -> bool:
    """Whether the target-temp curve was clamped to the tested RH band."""
    return ce.target_temperature_rh_is_clamped(indoor_rh_pct)


@dataclass(frozen=True)
class ScheduleSummary:
    """Headline numbers distilled from a `SimulationResult` for the
    guided page's summary strip. Presentation bookkeeping only.
    """

    peak_fans_on: int
    fan_hours: float
    pad_hours: float
    heating_hours: float
    n_steps: int
    step_duration_h: float
    fans_undersized: bool
    heater_undersized: bool
    target_unreachable: bool

    @property
    def total_hours(self) -> float:
        return self.n_steps * self.step_duration_h


def summarize(result: twin.SimulationResult, step_duration_h: float) -> ScheduleSummary:
    """Distil a simulated schedule into the guided page's headline stats.

    `step_duration_h` is how long each entered outdoor-conditions row
    represents (caller-supplied, exactly as `digital_twin` requires --
    it never assumes a step spacing).
    """
    heater_undersized = any(
        s.recommendation.heater_undersized for s in result.steps
    )
    return ScheduleSummary(
        peak_fans_on=result.peak_fans_on,
        fan_hours=result.fan_hours(step_duration_h),
        pad_hours=result.pad_hours(step_duration_h),
        heating_hours=result.heating_steps * step_duration_h,
        n_steps=len(result.steps),
        step_duration_h=step_duration_h,
        fans_undersized=result.shortfall_steps > 0,
        heater_undersized=heater_undersized,
        target_unreachable=result.unreachable_steps > 0,
    )


def describe_block(block: twin.ScheduleBlock, step_duration_h: float) -> str:
    """A one-line, plain-language description of a consolidated block.

    e.g. "06:00 – 09:00  (3.0 h):  4 fans, pads OFF, heat OFF".
    Purely a string helper so both the GUI and tests format blocks the
    same way.
    """
    span_h = block.n_steps * step_duration_h
    if block.start_label == block.end_label:
        when = block.start_label
    else:
        when = f"{block.start_label} – {block.end_label}"
    fans = f"{block.fans_on} fan" + ("" if block.fans_on == 1 else "s")
    pads = "pads ON" if block.pads_on else "pads off"
    heat = "heat ON" if block.heating_needed else "heat off"
    return f"{when}  ({span_h:g} h):  {fans}, {pads}, {heat}"
