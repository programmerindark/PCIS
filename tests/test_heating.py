"""Tests for pcis.core.heating.

Checks the energy balance behaves the way real brooding does -- chicks
need heat, grown birds do not, and the crossover happens as the flock's
own heat output overtakes the losses -- and that every piece composes
from already-cited modules (no new constants).
"""

from __future__ import annotations

import pytest

from pcis.core import growth_curve as gc
from pcis.core import heat_moisture_balance as hmb
from pcis.core import heating
from pcis.core import ventilation_solver as vs

SURFACES = [
    hmb.Surface("sidewalls", u_value=0.6, area_m2=350.0),
    hmb.Surface("ceiling", u_value=0.4, area_m2=1500.0),
]


def _requirement(age_days, indoor_t, outdoor_t, n=20000, outdoor_rh=40.0, heater_w=None):
    weight = gc.ross_308_body_weight_kg(age_days)
    flock = hmb.flock_load(n, weight, indoor_t)
    envelope = hmb.total_envelope_conduction_loss(SURFACES, indoor_t, outdoor_t)
    min_vent = vs.minimum_ventilation_rate_aviagen(weight) * n
    return heating.heating_requirement(
        flock, envelope, min_vent, indoor_t, outdoor_t, outdoor_rh,
        heater_capacity_w=heater_w,
    )


def test_day_old_chicks_in_the_cold_need_heat():
    r = _requirement(age_days=1, indoor_t=33.0, outdoor_t=10.0)
    assert r.heating_needed is True
    assert r.heat_deficit_w > 0.0
    # Loss must exceed the tiny heat a day-old chick produces.
    assert r.bird_sensible_heat_w < r.envelope_loss_w + r.ventilation_loss_w


def test_grown_birds_in_mild_weather_need_no_heat():
    r = _requirement(age_days=35, indoor_t=21.0, outdoor_t=15.0)
    assert r.heating_needed is False
    assert r.heat_deficit_w == 0.0


def test_grown_birds_on_a_hot_day_need_no_heat():
    r = _requirement(age_days=35, indoor_t=21.0, outdoor_t=34.0)
    assert r.heating_needed is False


def test_colder_outside_needs_more_heat():
    mild = _requirement(age_days=1, indoor_t=33.0, outdoor_t=15.0)
    cold = _requirement(age_days=1, indoor_t=33.0, outdoor_t=0.0)
    assert cold.heat_deficit_w > mild.heat_deficit_w


def test_bird_heat_output_rises_with_age():
    # Heavier birds contribute more sensible heat -- the mechanism that
    # eventually removes the need for heaters.
    young = _requirement(age_days=3, indoor_t=32.0, outdoor_t=12.0)
    older = _requirement(age_days=12, indoor_t=32.0, outdoor_t=12.0)
    assert older.bird_sensible_heat_w > young.bird_sensible_heat_w


def test_brooding_needs_heat_and_grown_birds_do_not():
    # The endpoints of a cold grow-out: chicks need heat, four-week birds
    # heat themselves.
    day2 = _requirement(age_days=2, indoor_t=33.0, outdoor_t=10.0)
    day28 = _requirement(age_days=28, indoor_t=23.0, outdoor_t=10.0)
    assert day2.heating_needed is True
    assert day28.heating_needed is False


def test_peak_heating_demand_is_not_day_one():
    # A real, non-obvious result of the energy balance: in early brooding
    # the minimum-ventilation requirement grows FASTER than the birds'
    # heat output, so the heating deficit RISES for the first week or so
    # before the birds finally overtake it. Peak heat demand is around
    # week 1-2, not day 1 -- which is exactly the "week 2 transition"
    # operators find tricky. Encoded here so the behaviour is deliberate,
    # not an accident nobody noticed.
    day2 = _requirement(age_days=2, indoor_t=33.0, outdoor_t=10.0)
    day10 = _requirement(age_days=10, indoor_t=29.0, outdoor_t=10.0)
    assert day10.heat_deficit_w > day2.heat_deficit_w


def test_heating_need_falls_from_its_peak_to_zero():
    # From the mid-brood peak onward the requirement falls monotonically
    # to zero as the birds' heat output takes over.
    day18 = _requirement(age_days=18, indoor_t=26.0, outdoor_t=10.0)
    day21 = _requirement(age_days=21, indoor_t=25.0, outdoor_t=10.0)
    day28 = _requirement(age_days=28, indoor_t=23.0, outdoor_t=10.0)
    assert day18.heat_deficit_w > day21.heat_deficit_w >= day28.heat_deficit_w
    assert day28.heat_deficit_w == 0.0


def test_ventilation_air_is_part_of_the_heat_load():
    # Warming incoming cold air is a real, often dominant, winter load.
    # It must be counted, not ignored.
    r = _requirement(age_days=7, indoor_t=31.0, outdoor_t=5.0)
    assert r.ventilation_loss_w > 0.0


def test_no_ventilation_loss_when_outside_is_warmer_than_target():
    loss = heating.ventilation_heat_loss_w(
        airflow_m3_per_h=5000.0, indoor_t_c=25.0, outdoor_t_c=30.0, outdoor_rh_pct=50.0
    )
    assert loss == 0.0


def test_heater_duty_fraction_from_capacity():
    r = _requirement(age_days=1, indoor_t=33.0, outdoor_t=10.0, heater_w=100_000.0)
    assert r.heater_duty_fraction == pytest.approx(r.heat_deficit_w / 100_000.0)
    assert 0.0 < r.heater_duty_fraction < 1.0
    assert r.heater_undersized is False


def test_undersized_heater_is_flagged():
    # A tiny heater against a big deficit: duty > 1 means even running
    # flat out it cannot hold target.
    r = _requirement(age_days=1, indoor_t=33.0, outdoor_t=-5.0, heater_w=5_000.0)
    assert r.heating_needed is True
    assert r.heater_duty_fraction > 1.0
    assert r.heater_undersized is True


def test_duty_is_none_without_a_capacity():
    r = _requirement(age_days=1, indoor_t=33.0, outdoor_t=10.0, heater_w=None)
    assert r.heater_duty_fraction is None
    assert r.heater_undersized is False


def test_heat_deficit_never_negative():
    # Even deep in the "no heating" regime the deficit is clamped at 0,
    # never a negative "surplus".
    r = _requirement(age_days=42, indoor_t=20.0, outdoor_t=30.0)
    assert r.heat_deficit_w == 0.0
