"""Unit tests for pcis.core.digital_twin.

These tests do NOT re-verify the underlying engineering (fan sizing,
heat balance, comfort scoring) -- that is the job of
test_recommendation_engine.py and friends. What they verify is the
twin's own contract: that it drives bird weight and target temperature
from the real Aviagen tables, that the schedule it produces actually
reflects the recommendations it computed, that consecutive same-staging
steps collapse into blocks correctly, and -- importantly -- that its
documented refusals (no weather synthesis, no age extrapolation, no
silent capping of an over-capacity requirement) actually hold.
"""

from __future__ import annotations

import pytest

from pcis.core import digital_twin as dt
from pcis.core import growth_curve as gc
from pcis.core import heat_moisture_balance as hmb
from pcis.equipment.cooling_pad import CELDEK_7090_15_150MM
from pcis.equipment.fan_curve import FAN_CATALOG

SURFACES = [
    hmb.Surface("sidewalls", u_value=0.6, area_m2=350.0),
    hmb.Surface("ceiling", u_value=0.4, area_m2=1500.0),
]

FAN = FAN_CATALOG[1]

COMMON = dict(
    bird_count=20000,
    envelope_surfaces=SURFACES,
    fan=FAN,
    design_static_pressure_pa=30.0,
    delta_t_c=3.0,
    indoor_rh_pct=60.0,
)


def _day_profile() -> list[dt.OutdoorCondition]:
    """A cool-night / hot-afternoon profile. These are illustrative
    test inputs, NOT a PCIS-published weather curve -- the module
    deliberately has no built-in profile (see its docstring).
    """
    return [
        dt.OutdoorCondition("00:00", 22.0, 75.0),
        dt.OutdoorCondition("06:00", 20.0, 80.0),
        dt.OutdoorCondition("12:00", 33.0, 45.0),
        dt.OutdoorCondition("18:00", 35.0, 40.0),
    ]


# ---------------------------------------------------------------------------
# simulate_schedule -- "a day in the life"
# ---------------------------------------------------------------------------


def test_simulate_schedule_returns_one_step_per_condition():
    conditions = _day_profile()
    result = dt.simulate_schedule(conditions=conditions, age_days=35, **COMMON)

    assert len(result.steps) == len(conditions)
    assert [s.label for s in result.steps] == ["00:00", "06:00", "12:00", "18:00"]


def test_simulate_schedule_uses_real_growth_curve_weight():
    result = dt.simulate_schedule(conditions=_day_profile(), age_days=21, **COMMON)

    expected = gc.ross_308_body_weight_kg(21)
    assert all(s.body_weight_kg == pytest.approx(expected) for s in result.steps)


def test_simulate_schedule_target_temp_is_constant_within_one_day():
    # Bird age is fixed for a single-day run, so the target setpoint
    # should not wander step to step.
    result = dt.simulate_schedule(conditions=_day_profile(), age_days=35, **COMMON)
    targets = {round(s.target_indoor_t_c, 6) for s in result.steps}
    assert len(targets) == 1


def test_hotter_step_needs_at_least_as_many_fans_as_cooler_step():
    result = dt.simulate_schedule(conditions=_day_profile(), age_days=35, **COMMON)
    by_label = {s.label: s for s in result.steps}
    # 18:00 (35C) is the hottest step; 06:00 (20C) the coolest.
    assert by_label["18:00"].fans_on >= by_label["06:00"].fans_on


def test_steps_carry_the_recommendation_they_were_built_from():
    result = dt.simulate_schedule(conditions=_day_profile(), age_days=35, **COMMON)
    for s in result.steps:
        assert s.fans_on == s.recommendation.fans_on
        assert s.pads_on == s.recommendation.pads_on


def test_simulate_schedule_rejects_empty_conditions():
    with pytest.raises(ValueError, match="at least one"):
        dt.simulate_schedule(conditions=[], age_days=35, **COMMON)


def test_simulate_schedule_refuses_age_outside_published_table():
    # growth_curve refuses to extrapolate; the twin must not paper over that.
    with pytest.raises(ValueError):
        dt.simulate_schedule(
            conditions=_day_profile(),
            age_days=gc.ROSS_308_MAX_AGE_DAYS + 5,
            **COMMON,
        )


def test_notes_record_the_data_provenance():
    result = dt.simulate_schedule(conditions=_day_profile(), age_days=35, **COMMON)
    joined = " ".join(result.notes)
    assert "Aviagen" in joined
    assert "caller-supplied" in joined  # the no-synthesized-weather promise


# ---------------------------------------------------------------------------
# Pads
# ---------------------------------------------------------------------------


def test_pads_come_on_during_hot_steps_when_a_pad_is_installed():
    result = dt.simulate_schedule(
        conditions=_day_profile(), age_days=35, cooling_pad=CELDEK_7090_15_150MM, **COMMON
    )
    by_label = {s.label: s for s in result.steps}
    assert by_label["18:00"].pads_on is True
    assert result.pad_steps >= 1


def test_pads_never_come_on_when_no_pad_is_installed():
    result = dt.simulate_schedule(conditions=_day_profile(), age_days=35, cooling_pad=None, **COMMON)
    assert all(s.pads_on is False for s in result.steps)
    assert result.pad_steps == 0


# ---------------------------------------------------------------------------
# Schedule blocks -- the "for how long" half of the question
# ---------------------------------------------------------------------------


def test_consecutive_identical_staging_collapses_into_one_block():
    # Four identical conditions -> one block spanning all four steps.
    conditions = [dt.OutdoorCondition(f"h{i}", 25.0, 60.0) for i in range(4)]
    result = dt.simulate_schedule(conditions=conditions, age_days=35, **COMMON)

    assert len(result.blocks) == 1
    block = result.blocks[0]
    assert block.n_steps == 4
    assert block.start_label == "h0"
    assert block.end_label == "h3"


def test_changing_staging_starts_a_new_block():
    conditions = [
        dt.OutdoorCondition("cool", 15.0, 60.0),
        dt.OutdoorCondition("hot", 38.0, 40.0),
    ]
    result = dt.simulate_schedule(conditions=conditions, age_days=42, **COMMON)
    # These two conditions should not produce identical staging.
    if result.steps[0].fans_on != result.steps[1].fans_on:
        assert len(result.blocks) == 2


def test_blocks_cover_every_step_exactly_once():
    result = dt.simulate_schedule(conditions=_day_profile(), age_days=35, **COMMON)
    assert sum(b.n_steps for b in result.blocks) == len(result.steps)


# ---------------------------------------------------------------------------
# Installed-capacity shortfall
# ---------------------------------------------------------------------------


def test_shortfall_flagged_when_requirement_exceeds_installed_fans():
    result = dt.simulate_schedule(
        conditions=_day_profile(), age_days=42, installed_fan_count=1, **COMMON
    )
    assert result.shortfall_steps > 0
    assert any(s.capacity_shortfall for s in result.steps)
    assert any("WARNING" in n for n in result.notes)


def test_shortfall_does_not_cap_the_reported_requirement():
    # fans_on must keep reporting what's NEEDED -- capping it would
    # hide the shortfall, which is the opposite of useful.
    capped = dt.simulate_schedule(
        conditions=_day_profile(), age_days=42, installed_fan_count=1, **COMMON
    )
    uncapped = dt.simulate_schedule(conditions=_day_profile(), age_days=42, **COMMON)
    assert [s.fans_on for s in capped.steps] == [s.fans_on for s in uncapped.steps]


def test_no_shortfall_flagged_when_capacity_is_ample():
    result = dt.simulate_schedule(
        conditions=_day_profile(), age_days=35, installed_fan_count=999, **COMMON
    )
    assert result.shortfall_steps == 0
    assert not any(s.capacity_shortfall for s in result.steps)


def test_installed_fan_count_none_never_flags_shortfall():
    result = dt.simulate_schedule(conditions=_day_profile(), age_days=42, **COMMON)
    assert result.shortfall_steps == 0


# ---------------------------------------------------------------------------
# simulate_grow_out -- "how does the requirement grow with the flock"
# ---------------------------------------------------------------------------


def test_grow_out_returns_one_step_per_age():
    ages = [7.0, 14.0, 21.0, 28.0, 35.0, 42.0]
    result = dt.simulate_grow_out(
        age_days_sequence=ages, outdoor_t_c=30.0, outdoor_rh_pct=50.0, **COMMON
    )
    assert len(result.steps) == len(ages)
    assert [s.age_days for s in result.steps] == ages


def test_grow_out_fan_requirement_rises_once_sensible_heat_governs():
    # NOTE: the naive expectation "more fans every week" is WRONG, and
    # this test documents why rather than asserting it. At day 7 the
    # governing constraint is moisture removal; from day 14 on it is
    # sensible heat. Those are different physics and don't hand over
    # smoothly, so the total requirement actually DIPS at the crossover
    # (3 fans at day 7, 2 at day 14 for this house). Within the
    # sensible-heat-governed stretch it is properly monotonic.
    # See the digital_twin.py module docstring, point 1.
    ages = [float(d) for d in range(7, 43, 7)]
    result = dt.simulate_grow_out(
        age_days_sequence=ages, outdoor_t_c=30.0, outdoor_rh_pct=50.0, **COMMON
    )

    sensible = [
        s for s in result.steps
        if s.recommendation.governing_constraint == "sensible_heat"
    ]
    assert len(sensible) >= 2, "expected the mature-flock steps to be sensible-heat governed"
    fans = [s.fans_on for s in sensible]
    assert fans == sorted(fans)


def test_grow_out_governing_constraint_can_change_with_age():
    # The mechanism behind the dip above -- worth asserting explicitly
    # so that if the constraint handover ever silently disappears, a
    # test says so.
    ages = [float(d) for d in range(7, 43, 7)]
    result = dt.simulate_grow_out(
        age_days_sequence=ages, outdoor_t_c=30.0, outdoor_rh_pct=50.0, **COMMON
    )
    constraints = {s.recommendation.governing_constraint for s in result.steps}
    assert len(constraints) > 1


def test_grow_out_target_temperature_falls_as_birds_grow():
    # Younger/lighter birds want a warmer house -- this is what makes
    # the schedule age-dependent at all.
    result = dt.simulate_grow_out(
        age_days_sequence=[7.0, 42.0], outdoor_t_c=30.0, outdoor_rh_pct=50.0, **COMMON
    )
    young, old = result.steps
    assert young.target_indoor_t_c > old.target_indoor_t_c


def test_grow_out_weight_matches_published_table_at_each_age():
    ages = [dt.MIN_SIMULATABLE_AGE_DAYS, 21.0, 42.0]
    result = dt.simulate_grow_out(
        age_days_sequence=ages, outdoor_t_c=25.0, outdoor_rh_pct=60.0, **COMMON
    )
    for step in result.steps:
        assert step.body_weight_kg == pytest.approx(gc.ross_308_body_weight_kg(step.age_days))


# ---------------------------------------------------------------------------
# The two-Aviagen-tables gap at very young ages (module docstring, point 2)
# ---------------------------------------------------------------------------


def test_day_zero_is_rejected_with_a_self_explaining_message():
    # Day 0 birds (0.044 kg) fall below the minimum-ventilation table's
    # 0.05 kg floor. The error must name the real cause, not surface a
    # confusing one from deep inside the ventilation solver.
    with pytest.raises(ValueError) as exc:
        dt.simulate_schedule(conditions=_day_profile(), age_days=0.0, **COMMON)

    message = str(exc.value)
    assert "minimum-ventilation table" in message
    assert f"day {dt.MIN_SIMULATABLE_AGE_DAYS:g}" in message


def test_min_simulatable_age_is_derived_from_the_two_published_tables():
    from pcis.core import ventilation_solver as vs

    # At the boundary the weight must clear the min-vent floor...
    assert (
        gc.ross_308_body_weight_kg(dt.MIN_SIMULATABLE_AGE_DAYS)
        >= vs.AVIAGEN_MIN_VENT_MIN_WEIGHT_KG
    )
    # ...and the day before it must not (i.e. it really is the earliest).
    if dt.MIN_SIMULATABLE_AGE_DAYS > gc.ROSS_308_MIN_AGE_DAYS:
        assert (
            gc.ross_308_body_weight_kg(dt.MIN_SIMULATABLE_AGE_DAYS - 1)
            < vs.AVIAGEN_MIN_VENT_MIN_WEIGHT_KG
        )


def test_earliest_simulatable_age_actually_simulates():
    result = dt.simulate_schedule(
        conditions=_day_profile(), age_days=dt.MIN_SIMULATABLE_AGE_DAYS, **COMMON
    )
    assert len(result.steps) == len(_day_profile())


def test_grow_out_rejects_empty_sequence():
    with pytest.raises(ValueError, match="at least one"):
        dt.simulate_grow_out(
            age_days_sequence=[], outdoor_t_c=30.0, outdoor_rh_pct=50.0, **COMMON
        )


def test_grow_out_refuses_age_outside_published_table():
    with pytest.raises(ValueError):
        dt.simulate_grow_out(
            age_days_sequence=[35.0, gc.ROSS_308_MAX_AGE_DAYS + 1],
            outdoor_t_c=30.0,
            outdoor_rh_pct=50.0,
            **COMMON,
        )


# ---------------------------------------------------------------------------
# Summary statistics
# ---------------------------------------------------------------------------


def test_peak_fans_on_matches_the_max_step():
    result = dt.simulate_schedule(conditions=_day_profile(), age_days=35, **COMMON)
    assert result.peak_fans_on == max(s.fans_on for s in result.steps)


def test_fan_hours_scales_with_step_duration():
    result = dt.simulate_schedule(conditions=_day_profile(), age_days=35, **COMMON)
    total_fans = sum(s.fans_on for s in result.steps)
    assert result.fan_hours(1.0) == pytest.approx(total_fans)
    assert result.fan_hours(6.0) == pytest.approx(total_fans * 6.0)


def test_pad_hours_scales_with_step_duration():
    result = dt.simulate_schedule(
        conditions=_day_profile(), age_days=35, cooling_pad=CELDEK_7090_15_150MM, **COMMON
    )
    assert result.pad_hours(6.0) == pytest.approx(result.pad_steps * 6.0)


def test_fan_hours_rejects_nonpositive_duration():
    result = dt.simulate_schedule(conditions=_day_profile(), age_days=35, **COMMON)
    with pytest.raises(ValueError):
        result.fan_hours(0.0)
    with pytest.raises(ValueError):
        result.pad_hours(-1.0)


# ---------------------------------------------------------------------------
# format_schedule_table -- presentation only
# ---------------------------------------------------------------------------


def test_format_schedule_table_contains_every_step_and_the_summary():
    result = dt.simulate_schedule(conditions=_day_profile(), age_days=35, **COMMON)
    text = dt.format_schedule_table(result)

    for step in result.steps:
        assert step.label in text
    assert "Consolidated schedule:" in text
    assert "Peak fans required:" in text
    assert "Notes:" in text


def test_format_schedule_table_marks_shortfall_steps():
    result = dt.simulate_schedule(
        conditions=_day_profile(), age_days=42, installed_fan_count=1, **COMMON
    )
    text = dt.format_schedule_table(result)
    assert "(!capacity)" in text
    assert "WARNING" in text


# ---------------------------------------------------------------------------
# Physically-unreachable target detection
#
# This is the most safety-relevant thing the twin does. Ventilation can
# only move the house toward the supply-air state -- it can never cool
# below it. When outdoor (or post-pad) air is hotter than the target,
# the sensible-heat equation still returns a finite fan count, which
# reads as "run this many fans and you'll hit target". You won't.
# ---------------------------------------------------------------------------


def test_unreachable_target_flagged_when_supply_air_exceeds_target():
    # Day 35 birds want ~20.7C; a 37C afternoon is ~28C even after pads.
    result = dt.simulate_schedule(
        conditions=[dt.OutdoorCondition("15:00", 37.0, 38.0)],
        age_days=35,
        cooling_pad=CELDEK_7090_15_150MM,
        **COMMON,
    )
    step = result.steps[0]
    assert step.target_unreachable is True
    assert step.recommendation.supply_air_t_c >= step.target_indoor_t_c
    assert result.unreachable_steps == 1


def test_unreachable_target_not_flagged_on_a_cool_day():
    # Cold outdoor air is well below the target, so ventilation can
    # genuinely reach it.
    result = dt.simulate_schedule(
        conditions=[dt.OutdoorCondition("06:00", 8.0, 70.0)],
        age_days=35,
        **COMMON,
    )
    assert result.steps[0].target_unreachable is False
    assert result.unreachable_steps == 0


def test_unreachable_warning_names_the_worst_step_and_the_gap():
    result = dt.simulate_schedule(
        conditions=[
            dt.OutdoorCondition("06:00", 8.0, 70.0),
            dt.OutdoorCondition("15:00", 40.0, 35.0),
        ],
        age_days=35,
        **COMMON,
    )
    warning = next(n for n in result.notes if "unreachable" in n)
    assert "15:00" in warning  # the hot step, not the cool one
    assert "More fans will not do it." in warning  # what won't help


def test_unreachable_steps_marked_in_the_rendered_table():
    result = dt.simulate_schedule(
        conditions=[dt.OutdoorCondition("15:00", 40.0, 35.0)],
        age_days=35,
        **COMMON,
    )
    text = dt.format_schedule_table(result)
    assert "(!unreachable)" in text


def test_twin_reports_the_engines_flag_rather_than_re_deriving_it():
    # The detection must live in one place. If the twin ever starts
    # computing this itself again, the two can drift apart.
    result = dt.simulate_schedule(
        conditions=[dt.OutdoorCondition("15:00", 40.0, 35.0)],
        age_days=35,
        **COMMON,
    )
    step = result.steps[0]
    assert step.target_unreachable is step.recommendation.target_unreachable


def test_capacity_shortfall_and_unreachable_are_independent_flags():
    # A house with plenty of fans on a brutally hot day: no capacity
    # shortfall, but the target is still physically unreachable. These
    # are different failures and must not be conflated.
    result = dt.simulate_schedule(
        conditions=[dt.OutdoorCondition("15:00", 40.0, 35.0)],
        age_days=35,
        installed_fan_count=999,
        **COMMON,
    )
    step = result.steps[0]
    assert step.capacity_shortfall is False
    assert step.target_unreachable is True


# ---------------------------------------------------------------------------
# Heaters in the schedule (cold-weather / brooding)
# ---------------------------------------------------------------------------


def _cold_day():
    return [dt.OutdoorCondition(l, t, 80.0) for l, t in
            [("00:00", 2.0), ("06:00", 0.0), ("12:00", 9.0), ("18:00", 4.0)]]


def test_cold_brooding_schedule_calls_for_heat():
    r = dt.simulate_schedule(
        conditions=_cold_day(), age_days=5, bird_count=20000,
        envelope_surfaces=SURFACES, fan=FAN_CATALOG[1],
        design_static_pressure_pa=30.0, delta_t_c=3.0, indoor_rh_pct=60.0,
        heater_capacity_w=120_000.0,
    )
    assert r.heating_steps == len(r.steps)          # every step needs heat
    assert all(s.heating_needed for s in r.steps)
    assert all(s.heater_duty_fraction is not None for s in r.steps)
    assert any("HEATING" in n for n in r.notes)


def test_minimum_ventilation_fans_still_run_while_heating():
    # A real winter house heats AND runs minimum-ventilation fans for air
    # quality -- heating must not zero the fans.
    r = dt.simulate_schedule(
        conditions=_cold_day(), age_days=5, bird_count=20000,
        envelope_surfaces=SURFACES, fan=FAN_CATALOG[1],
        design_static_pressure_pa=30.0, delta_t_c=3.0, indoor_rh_pct=60.0,
    )
    assert all(s.fans_on >= 1 for s in r.steps)
    assert all(s.heating_needed for s in r.steps)


def test_hot_day_schedule_needs_no_heat():
    hot = [dt.OutdoorCondition(l, t, 45.0) for l, t in
           [("12:00", 34.0), ("15:00", 37.0)]]
    r = dt.simulate_schedule(
        conditions=hot, age_days=35, bird_count=20000,
        envelope_surfaces=SURFACES, fan=FAN_CATALOG[1],
        design_static_pressure_pa=30.0, delta_t_c=3.0, indoor_rh_pct=60.0,
    )
    assert r.heating_steps == 0
    assert not any(s.heating_needed for s in r.steps)


def test_schedule_blocks_split_on_heating_state():
    # A day that starts cold (heat) and warms enough to stop heating must
    # break into separate blocks at the transition.
    mixed = [dt.OutdoorCondition("cold", -2.0, 80.0),
             dt.OutdoorCondition("warm", 33.0, 45.0)]
    r = dt.simulate_schedule(
        conditions=mixed, age_days=14, bird_count=20000,
        envelope_surfaces=SURFACES, fan=FAN_CATALOG[1],
        design_static_pressure_pa=30.0, delta_t_c=3.0, indoor_rh_pct=60.0,
    )
    heating_flags = {b.heating_needed for b in r.blocks}
    assert len(r.blocks) >= 2
    assert heating_flags == {True, False}


def test_format_table_shows_a_heat_column():
    r = dt.simulate_schedule(
        conditions=_cold_day(), age_days=5, bird_count=20000,
        envelope_surfaces=SURFACES, fan=FAN_CATALOG[1],
        design_static_pressure_pa=30.0, delta_t_c=3.0, indoor_rh_pct=60.0,
        heater_capacity_w=120_000.0,
    )
    text = dt.format_schedule_table(r)
    assert "Heat" in text
    assert "heat ON" in text
