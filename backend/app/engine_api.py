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
from pcis.core import wind_chill as wc
from pcis.core import bird_status as bs
from pcis.core import comfort_engine as ce
from pcis.core import digital_twin as twin
from pcis.core import envelope_presets as ep
from pcis.core import gc_policy as gcp
from pcis.core import growth_curve as gc
from pcis.core import psychrometrics as psy
from pcis.core import heat_moisture_balance as hmb
from pcis.core import house_metrics as hmet
from pcis.core import mortality as mort
from pcis.core import recommendation_engine as re
from pcis.core import skov_reference as skov
from pcis.core import tunnel_geometry as tgeo
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
        "felt_band": (
            wc.felt_temperature_band(
                rec.achievable_indoor_t_c, rec.air_speed_mps,
                rec.bird_age_days_used, rec.comfort.rh_pct,
            )
            if (rec.air_speed_mps is not None and rec.achievable_indoor_t_c is not None)
            else None
        ),
        "vpd_kpa": round(rec.vpd_kpa, 2),
        "achievable_indoor_t_c": round(rec.achievable_indoor_t_c, 1) if rec.achievable_indoor_t_c is not None else None,
        "felt_comfort_index": round(rec.felt_comfort_index, 0) if rec.felt_comfort_index is not None else None,
        "moisture_control_limited": rec.moisture_control_limited,
        "outdoor_rh_for_drying_pct": rec.outdoor_rh_for_drying_pct,
        "skov_humidity_benchmark": rec.skov_humidity_benchmark,
        "measured_air_speed_mps": rec.measured_air_speed_mps,
        "air_speed_agreement": rec.air_speed_agreement,
        "air_speed_divergence_pct": rec.air_speed_divergence_pct,
        "heating_needed": rec.heating_needed,
        "heat_deficit_kw": round(rec.heat_deficit_w / 1000.0, 1),
        "heater_duty_fraction": rec.heater_duty_fraction,
        "heater_undersized": rec.heater_undersized,
        "target_unreachable": rec.target_unreachable,
        "confidence_score": round(rec.confidence_score, 0),
        "action_confidence": round(rec.action_confidence, 0),
        "action_basis": rec.action_basis,
        "comfort": _comfort_dict(rec.comfort),
        "bird_status": _bird_status_dict(bs.from_recommendation(rec)),
        "explanation": rec.explanation,
    }


def _recommend_obj(payload):
    """Build the engine Recommendation from a request payload.

    Source policy (SKOV fills GAPS, it does not override research):

      * Where a researched/breed-published value exists, PCIS uses it --
        target temperature (Aviagen target-temp table) and minimum
        ventilation (Aviagen 2018) both qualify.
      * Where no researched value exists, PCIS uses the SKOV Viper Touch
        controller curve -- the age-dependent chill factor and the maximum
        tunnel air speed are the real gaps it fills.

    The SKOV setpoint is still computed and returned alongside so the
    operator can see where a working commercial controller would differ.
    """
    age = float(payload.bird_age_days)
    weight = gc.ross_308_body_weight_kg(age)
    aviagen_t = ce.target_temperature(weight, payload.indoor_rh_pct)
    indoor_t = aviagen_t                                # researched value wins
    skov_min_vent = None                                # Aviagen table has this
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
        bird_age_days=age,                              # age-aware wind chill
        min_vent_per_bird_override=skov_min_vent,       # SKOV wins
        # Measured barometric pressure when a sensor supplies it; the
        # engine falls back to sea level only when nothing is measured.
        pressure_pa=(payload.pressure_hpa * 100.0
                     if getattr(payload, "pressure_hpa", None)
                     else psy.STANDARD_ATM_PRESSURE_PA),
        measured_air_speed_mps=getattr(payload, "measured_air_speed_mps", None),
    )
    return rec, weight, aviagen_t


def recommend(payload) -> dict:
    """Single-moment recommendation. `payload` is a validated request
    model with attribute access (Pydantic)."""
    rec, weight, aviagen_t = _recommend_obj(payload)
    out = _rec_dict(rec)
    out["body_weight_kg"] = round(weight, 3)

    # Derived house metrics: stocking density, estimated CO2, air changes.
    # Evaluated at the ACHIEVABLE indoor temperature (what the house can
    # actually hold), not the target -- bird moisture and CO2 output both
    # depend on the real temperature, and using the target understated
    # them on hot days.
    flock = hmb.flock_load(
        payload.bird_count, weight,
        rec.achievable_indoor_t_c if rec.achievable_indoor_t_c is not None else rec.comfort.target_temp_c,
    )
    metrics = hmet.assess(
        bird_count=payload.bird_count,
        body_weight_kg=weight,
        floor_area_m2=payload.length_m * payload.width_m,
        house_volume_m3=payload.length_m * payload.width_m * payload.height_m,
        delivered_airflow_m3_per_h=rec.delivered_airflow_m3_per_h,
        co2_production_m3_per_h=flock.co2_m3_per_h,
    )
    # Predicted indoor humidity from the moisture mass balance.
    pred = hmet.predict_indoor_humidity(
        indoor_t_c=rec.achievable_indoor_t_c,
        supply_t_c=rec.supply_air_t_c,
        supply_rh_pct=rec.supply_air_rh_pct,
        moisture_load_kg_per_h=flock.moisture_kg_per_h,
        airflow_m3_per_h=rec.delivered_airflow_m3_per_h or 0.0,
    )
    out["predicted_humidity"] = None if pred is None else {
        "indoor_rh_pct": pred.indoor_rh_pct,
        "indoor_humidity_ratio_g_per_kg": pred.indoor_humidity_ratio_g_per_kg,
        "supply_humidity_ratio_g_per_kg": pred.supply_humidity_ratio_g_per_kg,
        "moisture_added_g_per_kg": pred.moisture_added_g_per_kg,
        "saturated": pred.saturated,
        "note": pred.note,
    }

    # Tunnel geometry: what ceiling height would reach the velocity target?
    xs = payload.width_m * payload.height_m
    per_fan = FAN_CATALOG[payload.fan_index].airflow_at_static_pressure(payload.static_pressure_pa)
    geo = tgeo.advise_geometry(
        airflow_m3_per_h=rec.delivered_airflow_m3_per_h or 0.0,
        house_width_m=payload.width_m,
        current_cross_section_m2=xs,
        airflow_per_fan_m3_per_h=per_fan,
        installed_fans=payload.installed_fans,
    )
    heights = [payload.height_m, payload.height_m - 0.3, payload.height_m - 0.5,
               payload.height_m - 0.8, payload.height_m - 1.0]
    # Per-fan airflow at the design static pressure, so each ceiling option
    # can report the fan count it would need -- the figure that decides
    # whether a drop ceiling is worth building.
    _fan = FAN_CATALOG[payload.fan_index]
    _per_fan = _fan.airflow_at_static_pressure(payload.static_pressure_pa)
    table = tgeo.velocity_table(rec.delivered_airflow_m3_per_h or 0.0, payload.width_m,
                                [h for h in heights if h >= 1.2],
                                airflow_per_fan_m3_per_h=_per_fan)
    out["tunnel_geometry"] = {
        "current_velocity_mps": geo.current_velocity_mps,
        "target_velocity_mps": geo.target_velocity_mps,
        "meets_target": geo.meets_target,
        "required_cross_section_m2": geo.required_cross_section_m2,
        "required_ceiling_height_m": geo.required_ceiling_height_m,
        "current_ceiling_height_m": geo.current_ceiling_height_m,
        "ceiling_drop_m": geo.ceiling_drop_m,
        "fans_needed_instead": geo.fans_needed_instead,
        "note": geo.note,
        "options": [
            {"ceiling_height_m": o.ceiling_height_m, "cross_section_m2": o.cross_section_m2,
             "velocity_mps": o.velocity_mps, "velocity_fpm": o.velocity_fpm,
             "fans_needed": o.fans_needed,
             "meets_tunnel_target": o.meets_tunnel_target,
             "windchill_effective": o.windchill_effective}
            for o in table
        ],
    }

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
    # Show where PCIS's two sources disagree (SKOV is being followed).
    out["setpoint_sources"] = skov.compare_target_temperature(
        float(payload.bird_age_days), aviagen_target_c=aviagen_t
    )
    out["setpoint_sources"]["using"] = "aviagen"
    out["setpoint_sources"]["policy"] = (
        "Researched values win; SKOV controller curves fill gaps only "
        "(age chill factor, max tunnel air speed)."
    )
    out["min_vent_source"] = rec.min_vent_source
    out["min_vent_per_bird_m3_h"] = rec.min_vent_per_bird_m3_h

    # SAFETY CROSS-CHECK: the controller's minimum ventilation is well
    # below Aviagen's. Air quality is the reason min-vent exists, so the
    # estimated CO2 is the check on whether that lower rate is safe here.
    co2 = out["house_metrics"]["estimated_co2_ppm"]
    if co2 is not None and not out["house_metrics"]["co2_within_guideline"]:
        out["house_metrics"]["note"] += (
            f" WARNING: at the controller's lower minimum-ventilation rate the estimated "
            f"CO2 is {co2:.0f} ppm, above the 3000 ppm guideline — raise minimum ventilation."
        )

    return out


def mortality(payload) -> dict:
    """Assess a flock's mortality against the cited EU benchmark."""
    a = mort.assess(
        payload.placed, payload.cumulative_dead, payload.age_days,
        payload.dead_today, depleted=getattr(payload, "depleted", 0),
    )
    return {
        "live_count": a.live_count,
        "cumulative_dead": a.cumulative_dead,
        "cumulative_pct": a.cumulative_pct,
        "acceptable_pct": a.acceptable_pct,
        "within_target": a.within_target,
        "elevated_today": a.elevated_today,
        "daily_pct": a.daily_pct,
        "depleted": a.depleted,
        "note": a.note,
    }


def gc_position(payload) -> dict:
    """Where the crop currently sits against the IB Group GC policy.

    A POSITION, not a projection: the contract formula applied to what has
    been measured and entered so far. It says nothing about the days
    remaining, because weight will rise and FCR will worsen and both move
    cFCR in opposite directions.

    This is the one endpoint that returns money, and it is allowed to
    because the slab tables are a published contract rather than a model
    -- see the header of pcis.core.gc_policy. As everywhere else, the web
    layer adds no engineering: it unpacks the payload and formats the
    result.
    """
    a = gcp.project_in_crop(
        chicks_housed=payload.chicks_housed,
        birds_alive=payload.birds_alive,
        avg_weight_kg=payload.avg_weight_kg,
        feed_consumed_kg=payload.feed_consumed_kg,
        shed_type=getattr(payload, "shed_type", "other_ec") or "other_ec",
        depleted_birds=getattr(payload, "depleted_birds", 0) or 0,
        depleted_weight_kg=getattr(payload, "depleted_weight_kg", 0.0) or 0.0,
    )
    d = a.distance
    return {
        # `incomplete_reason` is first because a caller that ignores it
        # will render a payout PCIS has said it cannot stand behind.
        "incomplete_reason": a.incomplete_reason,
        "mortality_pct": a.mortality_pct,
        "birds_delivered": a.birds_lifted,
        "avg_weight_kg": a.avg_weight_kg,
        "total_weight_kg": a.total_weight_kg,
        "fcr": a.fcr,
        "cbw_kg": a.cbw_kg,
        "cfcr": a.cfcr,
        "cbw_penalised": a.cbw_penalised,
        "rate_per_kg": a.rate_per_kg,
        "rearing_charge": a.rearing_charge,
        "shed_type": a.shed_type,
        "mortality_threshold_pct": gcp.CBW_MORTALITY_THRESHOLD_PCT,
        "slab": {
            "next_better_cfcr": d.next_better_cfcr,
            "next_better_rate": d.next_better_rate,
            "gain_per_kg": d.gain_per_kg,
            "margin_to_worse_cfcr": d.margin_to_worse_cfcr,
            "next_worse_rate": d.next_worse_rate,
            "loss_per_kg": d.loss_per_kg,
        },
        "notes": a.notes,
    }


def advise(payload) -> dict:
    """The AI Advisor: one prioritised action + its predicted effect."""
    rec, _, _ = _recommend_obj(payload)
    a = adv.advise(rec, installed_fans=payload.installed_fans, pads_installed=payload.cooling_pads)
    return {
        "category": a.category,
        "headline": a.headline,
        "detail": a.detail,
        "why": a.why,
        "confidence": round(a.confidence, 0),
        "metric_confidence": round(a.metric_confidence, 0),
        "confidence_basis": a.confidence_basis,
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
    series = [
        {
            "label": s.label,
            "outdoor_t_c": round(s.outdoor_t_c, 1),
            "outdoor_rh_pct": round(s.outdoor_rh_pct, 0),
            "target_t_c": round(s.target_indoor_t_c, 1),
            "fans_on": s.fans_on,
            "air_speed_mps": round(s.recommendation.air_speed_mps, 2) if s.recommendation.air_speed_mps is not None else None,
            "effective_temp_c": round(s.recommendation.effective_temp_c, 1) if s.recommendation.effective_temp_c is not None else None,
            "vpd_kpa": round(s.recommendation.vpd_kpa, 2),
        }
        for s in result.steps
    ]
    return {
        "blocks": blocks,
        "series": series,
        "peak_fans_on": result.peak_fans_on,
        "fan_hours": round(result.fan_hours(step_h), 1),
        "heating_steps": result.heating_steps,
        "shortfall_steps": result.shortfall_steps,
        "unreachable_steps": result.unreachable_steps,
        "notes": result.notes,
        "body_weight_kg": round(weight, 3),
    }
