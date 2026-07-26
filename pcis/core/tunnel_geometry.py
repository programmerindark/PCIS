"""Tunnel geometry: what cross-section do my fans actually need?

The operator's real question when fan capacity is fixed. Tunnel air
velocity is pure continuity:

    V = Q / A          (A = cross-section the air passes through)

so with Q fixed by the fans you own, the only remaining lever is A --
which is why dropping a false ceiling is standard practice in tunnel
houses and, for a farm that cannot afford more fans, is usually the
cheapest way to reach the published air-velocity targets.

This module inverts the relationship: given the airflow the installed
fans deliver and a target velocity, it returns the cross-section (and,
for a known house width, the ceiling height) required.

Honesty notes
-------------
* The velocity targets themselves are NOT invented here -- they come
  from `target_airspeed` (Cobb 3.0 m/s tunnel target; Aviagen 2.54 m/s
  effective-wind-chill threshold).
* **Static pressure.** Restricting the cross-section raises the static
  pressure the fans work against, and fans deliver LESS air at higher
  pressure. PCIS cannot predict the new static pressure from geometry
  alone -- that depends on inlet area, pad resistance and house
  tightness, none of which we have measured data for, and guessing it
  would be inventing a number. So this module takes the airflow you give
  it and FLAGS the issue: re-run at a higher assumed static pressure
  (the fan curve will return the lower airflow) to see how much of the
  gain survives. `velocity_table` makes that comparison easy.
* The result is a NOMINAL full-profile velocity, the same caveat as
  `ventilation_solver.tunnel_airspeed`: real velocity at bird level
  varies with house design and obstructions.
"""

from __future__ import annotations

from dataclasses import dataclass

from pcis.core import target_airspeed as tas


def cross_section_for_velocity(airflow_m3_per_h: float, target_velocity_mps: float) -> float:
    """Cross-section needed to reach `target_velocity_mps`, m^2 (A = Q/V)."""
    if airflow_m3_per_h <= 0 or target_velocity_mps <= 0:
        raise ValueError("airflow and target velocity must both be positive")
    return (airflow_m3_per_h / 3600.0) / target_velocity_mps


def velocity_at(airflow_m3_per_h: float, cross_section_m2: float) -> float:
    """Nominal tunnel velocity for a given airflow and cross-section, m/s."""
    if cross_section_m2 <= 0:
        raise ValueError("cross-section must be positive")
    return (airflow_m3_per_h / 3600.0) / cross_section_m2


@dataclass(frozen=True)
class CeilingOption:
    """One candidate ceiling height and what it achieves."""

    ceiling_height_m: float
    cross_section_m2: float
    velocity_mps: float
    velocity_fpm: float
    meets_tunnel_target: bool          # >= 3.0 m/s   [Cobb]
    windchill_effective: bool          # >= 2.54 m/s  [Aviagen]


def velocity_table(
    airflow_m3_per_h: float,
    house_width_m: float,
    heights_m: list[float],
) -> list[CeilingOption]:
    """Velocity achieved at each candidate ceiling height."""
    out: list[CeilingOption] = []
    for h in heights_m:
        area = house_width_m * h
        v = velocity_at(airflow_m3_per_h, area)
        out.append(CeilingOption(
            ceiling_height_m=round(h, 2),
            cross_section_m2=round(area, 1),
            velocity_mps=round(v, 2),
            velocity_fpm=round(v * 196.85, 0),
            meets_tunnel_target=v >= tas.TUNNEL_TARGET_AIRSPEED_MPS,
            windchill_effective=v >= tas.EFFECTIVE_WINDCHILL_THRESHOLD_MPS,
        ))
    return out


@dataclass(frozen=True)
class GeometryAdvice:
    current_velocity_mps: float
    target_velocity_mps: float
    meets_target: bool
    required_cross_section_m2: float
    required_ceiling_height_m: float | None
    current_ceiling_height_m: float | None
    ceiling_drop_m: float | None
    fans_needed_instead: int | None
    note: str


def advise_geometry(
    *,
    airflow_m3_per_h: float,
    house_width_m: float,
    current_cross_section_m2: float,
    airflow_per_fan_m3_per_h: float | None = None,
    installed_fans: int | None = None,
    target_velocity_mps: float = tas.TUNNEL_TARGET_AIRSPEED_MPS,
) -> GeometryAdvice:
    """Compare 'drop the ceiling' against 'add fans' for a velocity target.

    Both routes reach the same velocity; this returns the numbers for
    each so the operator can weigh cost.
    """
    current_v = velocity_at(airflow_m3_per_h, current_cross_section_m2)
    need_area = cross_section_for_velocity(airflow_m3_per_h, target_velocity_mps)
    need_h = need_area / house_width_m if house_width_m > 0 else None
    cur_h = current_cross_section_m2 / house_width_m if house_width_m > 0 else None
    drop = (cur_h - need_h) if (cur_h is not None and need_h is not None) else None

    # The alternative: keep the geometry, add fans.
    fans_needed = None
    if airflow_per_fan_m3_per_h and airflow_per_fan_m3_per_h > 0:
        need_q = target_velocity_mps * current_cross_section_m2 * 3600.0
        import math
        fans_needed = int(math.ceil(need_q / airflow_per_fan_m3_per_h))

    meets = current_v >= target_velocity_mps - 1e-9
    if meets:
        note = (
            f"Already at {current_v:.2f} m/s ({current_v * 196.85:.0f} ft/min) — "
            f"at or above the {target_velocity_mps:g} m/s target. No geometry change needed."
        )
    else:
        parts = [
            f"At {current_v:.2f} m/s you are below the {target_velocity_mps:g} m/s target."
        ]
        if need_h is not None and drop is not None and drop > 0:
            parts.append(
                f"Lowering the ceiling to {need_h:.2f} m (a {drop:.2f} m drop, "
                f"cross-section {need_area:.1f} m2) reaches it with the fans you already have."
            )
        if fans_needed is not None and installed_fans is not None:
            extra = max(0, fans_needed - installed_fans)
            parts.append(
                f"Keeping the current ceiling would instead need {fans_needed} fans "
                f"({extra} more than the {installed_fans} installed)."
            )
        parts.append(
            "NOTE: a tighter cross-section raises static pressure and fans deliver less "
            "air against it — re-check at a higher static pressure before committing."
        )
        note = " ".join(parts)

    return GeometryAdvice(
        current_velocity_mps=round(current_v, 2),
        target_velocity_mps=target_velocity_mps,
        meets_target=meets,
        required_cross_section_m2=round(need_area, 1),
        required_ceiling_height_m=round(need_h, 2) if need_h is not None else None,
        current_ceiling_height_m=round(cur_h, 2) if cur_h is not None else None,
        ceiling_drop_m=round(drop, 2) if drop is not None else None,
        fans_needed_instead=fans_needed,
        note=note,
    )
