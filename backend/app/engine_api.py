"""Thin adapter between the web API and the validated PCIS engine.

This module is the ONLY place the web layer touches `pcis.core`. It
translates plain JSON-friendly inputs into the engine's function calls
and translates the engine's dataclasses back into plain dicts. It adds
NO engineering of its own -- every number still comes from the cited,
tested engine (`pcis.core`), which is why the whole science stays valid
on the web without being re-derived.
"""

from __future__ import annotations

from pcis.core import advisor as adv
from pcis.core import bird_status as bs
from pcis.core import comfort_engine as ce
from pcis.core import digital_twin as twin
from pcis.core import envelope_presets as ep
from pcis.core import growth_curve as gc
from pcis.core import heat_moisture_balance as hmb
from pcis.core import house_metrics as hmet
from pcis.core import mortality as mort
from pcis.core import recommendation_engine as re
from pcis.equipment.cooling_pad import COOLING_PAD_CATALOG
from pcis.equipment.fan_curve import FAN_CATALOG

# Insulation level -> cited envelope presets (walls, ceiling).
_INSULATION = {
    "uninsulated": ("Uninsulated wall (single-skin / curtain)", "Uninsulated ceiling / roof"),
    "insulated": ("Insulated wall (R-13, heated house)", "Insulated ceiling (R-21, recommended)"),
    "well_insulated": ("Well-insulated wall (R-19)", "Well-insulated ceiling (R-30)"),
}


def list_fans() -> list[dict]:
    return [
        {"index": i, "label": f"{f.manufacturer} {f.model}"}
        for i, f in enumerate(FAN_CATALOG)
    ]


def list_pads() -> list[dict]:
    return [
        {"index": i, "label": f"{p.manufacturer} {p.model}"}
        for i, p in enumerate(COOLING_PAD_CATALOG)
    ]


def growth_curve() -> list[dict]:
    """Aviagen Ross 308 as-hatched body weight (kg) for days 0-56 [cited]."""
    return [
        {"day": d, "weight_kg": round(gc.ross_308_body_weight_kg(float(d)), 3)}
        for d in range(int(gc.ROSS_308_MIN_AGE_DAYS), int(gc.ROSS_308_MAX_AGE_DAYS) + 1)
    ]


def insulation_levels() -> list[dict]:
    """The insulation choices, with the cited U-values they resolve to."""
    out = []
    for key, (wall_lbl, ceil_lbl) in _INSULATION.items():
        out.append({
            "key": key,
            "wall_u": ep.by_label(wall_lbl).u_value,
            "ceiling_u": ep.by_label(ceil_lbl).u_value,
        })
    return out


def _surfaces(length_m: float, width_m: float, height_m: float, insulation: str):
    wall_lbl, ceil_lbl = _INSULATION[insulation]
    u_wall = ep.by_label(wall_lbl).u_value
    u_ceil = ep.by_label(ceil_lbl).u_value
    wall_area = 2.0 * (length_m + width_m) * height_m
    ceil_area = length_m * width_m
    return [
        hmb.Surface(name="walls", u_value=u_wall, area_m2=wall_area),
        hmb.Surface(name="ceiling", u_value=u_ceil, area_m2=ceil_area),
    ]


def _comfort_dict(c: ce.ComfortAssessment) -> dict:
    return {
        "target_temp_c": round(c.target_temp_c, 2),
        "deviation_c": round(c.deviation_c, 2),
        "thi": round(c.thi, 1),
        "thi_class": c.thi_class,
        "comfort_index": round(c.comfort_index, 0),
    }


def _bird_status_dict(status: bs.BirdStatus) -> dict:
    return {
        "comfort_score": round(status.comfort_score, 0),
        "comfort_label": status.comfort_label,
        "heat_stress_risk": status.heat_stress_risk,
        "effective_bird_temp_c": (
            round(status.effective_bird_temp_c, 1)
            if status.effective_bird_temp_c is not None else None
        ),
        "panting_index": status.panting_index,
        "water_intake_multiplier": round(status.water_intake_multiplier, 2),
        "estimates": status.is_estimate,
    }


def _rec_dict(rec: re.Recommendation) -> dict:
    return {
        "fans_on": rec.fans_on,
        "pads_on": rec.pads_on,
        "governing_constraint": rec.governing_constraint,
        "required_airflow_m3_per_h": round(rec.required_airflow_m3_per_h, 0),
        "air_speed_mps": round(rec.air_speed_mps, 2) if rec.air_speed_mps is not None else None,
        "target_airspeed_mps": rec.target_airspeed_mps,
        "effective_temp_c": round(rec.effective_temp_c, 1) if rec.effective_temp_c is not None else None,
        "vpd_kpa": round(rec.vpd_kpa, 2),
        "heating_needed": rec.heating_needed,
        "heat_deficit_kw": round(rec.heat_deficit_w / 1000.0, 1),
        "heater_duty_fraction": rec.heater_duty_fraction,
        "heater_undersized": rec.heater_undersized,
        "target_unreachable": rec.target_unreachable,
        "confidence_score": round(rec.confidence_score, 0),
        "comfort": _comfort_dict(rec.comfort),
        "bird_status": _bird_status_dict(bs.from_recommendation(rec)),
        "explanation": rec.explanation,
    }


def _recommend_obj(payload):
    """Build the engine Recommendation from a request payload."""
    weight = gc.ross_308_body_weight_kg(float(payload.bird_age_days))
    indoor_t = ce.target_temperature(weight, payload.indoor_rh_pct)
    rec = re.recommend(
        bird_count=payload.bird_count,
        body_weight_kg=weight,
        indoor_t_c=indoor_t,
        indoor_rh_pct=payload.indoor_rh_pct,
        outdoor_t_c=payload.outdoor_t_c,
        outdoor_rh_pct=payload.outdoor_rh_pct,
        envelope_surfaces=_surfaces(payload.length_m, payload.width_m, payload.height_m, payload.insulation),
        fan=FAN_CATALOG[payload.fan_index],
        design_static_pressure_pa=payload.static_pressure_pa,
        delta_t_c=3.0,
        cooling_pad=COOLING_PAD_CATALOG[0] if payload.cooling_pads else None,
        house_cross_section_m2=payload.width_m * payload.height_m,
        heater_capacity_w=(payload.heater_kw * 1000.0) if payload.heater_kw > 0 else None,
    )
    return rec, weight


def recommend(payload) -> dict:
    """Single-moment recommendation. `payload` is a validated request
    model with attribute access (Pydantic)."""
    rec, weight = _recommend_obj(payload)
    out = _rec_dict(rec)
    out["body_weight_kg"] = round(weight, 3)

    # Derived house metrics: stocking density, estimated CO2, air changes.
    flock = hmb.flock_load(payload.bird_count, weight, rec.comfort.target_temp_c)
    metrics = hmet.assess(
        bird_count=payload.bird_count,
        body_weight_kg=weight,
        floor_area_m2=payload.length_m * payload.width_m,
        house_volume_m3=payload.length_m * payload.width_m * payload.height_m,
        delivered_airflow_m3_per_h=rec.delivered_airflow_m3_per_h,
        co2_production_m3_per_h=flock.co2_m3_per_h,
    )
    out["house_metrics"] = {
        "stocking_density_kg_m2": metrics.stocking_density_kg_m2,
        "density_limit_kg_m2": metrics.density_limit_kg_m2,
        "density_pct_of_limit": metrics.density_pct_of_limit,
        "density_within_limit": metrics.density_within_limit,
        "estimated_co2_ppm": metrics.estimated_co2_ppm,
        "co2_within_guideline": metrics.co2_within_guideline,
        "air_changes_per_hour": metrics.air_changes_per_hour,
        "airflow_per_bird_m3_h": metrics.airflow_per_bird_m3_h,
        "note": metrics.note,
    }
    return out


def mortality(payload) -> dict:
    """Assess a flock's mortality against the cited EU benchmark."""
    a = mort.assess(payload.placed, payload.cumulative_dead, payload.age_days, payload.dead_today)
    return {
        "live_count": a.live_count,
        "cumulative_dead": a.cumulative_dead,
        "cumulative_pct": a.cumulative_pct,
        "acceptable_pct": a.acceptable_pct,
        "within_target": a.within_target,
        "elevated_today": a.elevated_today,
        "daily_pct": a.daily_pct,
        "note": a.note,
    }


def advise(payload) -> dict:
    """The AI Advisor: one prioritised action + its predicted effect."""
    rec, _ = _recommend_obj(payload)
    a = adv.advise(rec, installed_fans=payload.installed_fans, pads_installed=payload.cooling_pads)
    return {
        "category": a.category,
        "headline": a.headline,
        "detail": a.detail,
        "why": a.why,
        "confidence": round(a.confidence, 0),
        "feel_before_c": round(a.feel_before_c, 1) if a.feel_before_c is not None else None,
        "feel_after_c": round(a.feel_after_c, 1) if a.feel_after_c is not None else None,
        "panting_before": a.panting_before,
        "panting_after": a.panting_after,
        "comfort_score": round(a.comfort_score, 0),
        "heat_stress_risk": a.heat_stress_risk,
    }


def schedule(payload) -> dict:
    """Day schedule from an entered weather profile."""
    weight = gc.ross_308_body_weight_kg(float(payload.bird_age_days))
    conditions = [
        twin.OutdoorCondition(label=p.label, t_c=p.t_c, rh_pct=p.rh_pct)
        for p in payload.profile
    ]
    result = twin.simulate_schedule(
        conditions=conditions,
        age_days=float(payload.bird_age_days),
        bird_count=payload.bird_count,
        envelope_surfaces=_surfaces(payload.length_m, payload.width_m, payload.height_m, payload.insulation),
        fan=FAN_CATALOG[payload.fan_index],
        design_static_pressure_pa=payload.static_pressure_pa,
        delta_t_c=3.0,
        indoor_rh_pct=payload.indoor_rh_pct,
        cooling_pad=COOLING_PAD_CATALOG[0] if payload.cooling_pads else None,
        installed_fan_count=payload.installed_fans if payload.installed_fans > 0 else None,
        heater_capacity_w=(payload.heater_kw * 1000.0) if payload.heater_kw > 0 else None,
        house_cross_section_m2=payload.width_m * payload.height_m,
    )
    step_h = payload.step_hours
    blocks = [
        {
            "start": b.start_label,
            "end": b.end_label,
            "hours": round(b.n_steps * step_h, 2),
            "fans_on": b.fans_on,
            "pads_on": b.pads_on,
            "heating_needed": b.heating_needed,
        }
        for b in result.blocks
    ]
    return {
        "blocks": blocks,
        "peak_fans_on": result.peak_fans_on,
        "fan_hours": round(result.fan_hours(step_h), 1),
        "heating_steps": result.heating_steps,
        "shortfall_steps": result.shortfall_steps,
        "unreachable_steps": result.unreachable_steps,
        "notes": result.notes,
        "body_weight_kg": round(weight, 3),
    }
