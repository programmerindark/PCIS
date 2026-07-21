"""Unit tests for pcis.gui.units.

Unit conversion is the kind of code that looks too simple to test and
then silently corrupts every number downstream. These tests check the
definitional factors against independently known reference points
(freezing/boiling water, a known CFM figure, etc.) rather than just
asserting the code agrees with itself, and specifically guard the
absolute-vs-difference temperature distinction, which is the classic
bug in this domain.
"""

from __future__ import annotations

import pytest

from pcis.gui import units as u


# ---------------------------------------------------------------------------
# Temperature: absolute
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "celsius, fahrenheit",
    [
        (0.0, 32.0),        # water freezes
        (100.0, 212.0),     # water boils
        (-40.0, -40.0),     # the crossover point
        (37.0, 98.6),       # body temperature
    ],
)
def test_celsius_fahrenheit_reference_points(celsius, fahrenheit):
    assert u.c_to_f(celsius) == pytest.approx(fahrenheit)
    assert u.f_to_c(fahrenheit) == pytest.approx(celsius)


def test_temperature_round_trips():
    for c in [-20.0, 0.0, 21.5, 35.0, 45.0]:
        assert u.f_to_c(u.c_to_f(c)) == pytest.approx(c)


# ---------------------------------------------------------------------------
# Temperature: DIFFERENCES
#
# The bug this guards: a 3 degC allowed temperature rise is 5.4 degF,
# not 37.4 degF. Applying the 32-degree offset to a difference would
# roughly double the sensible-heat airflow requirement.
# ---------------------------------------------------------------------------


def test_temperature_difference_has_no_offset():
    assert u.delta_c_to_delta_f(3.0) == pytest.approx(5.4)
    assert u.delta_c_to_delta_f(0.0) == pytest.approx(0.0)
    assert u.delta_f_to_delta_c(5.4) == pytest.approx(3.0)


def test_delta_conversion_differs_from_absolute_conversion():
    # If these ever coincide, someone has wired the wrong function in.
    assert u.delta_c_to_delta_f(3.0) != pytest.approx(u.c_to_f(3.0))


def test_delta_temperature_round_trips():
    for d in [0.5, 3.0, 11.0]:
        assert u.delta_f_to_delta_c(u.delta_c_to_delta_f(d)) == pytest.approx(d)


# ---------------------------------------------------------------------------
# Length / area / mass
# ---------------------------------------------------------------------------


def test_foot_is_exactly_0_3048_metres():
    assert u.ft_to_m(1.0) == pytest.approx(0.3048, abs=1e-12)
    assert u.m_to_ft(0.3048) == pytest.approx(1.0)


def test_typical_house_length_converts_sensibly():
    # A 150 m house is a bit under 500 ft.
    assert u.m_to_ft(150.0) == pytest.approx(492.126, abs=0.01)


def test_area_conversion_is_the_square_of_length():
    assert u.sqft_to_m2(1.0) == pytest.approx(0.3048**2, abs=1e-12)
    assert u.m2_to_sqft(1.0) == pytest.approx(10.7639, abs=1e-3)


def test_pound_is_exactly_0_45359237_kg():
    assert u.lb_to_kg(1.0) == pytest.approx(0.45359237, abs=1e-12)


def test_broiler_weight_converts_sensibly():
    # A 2.5 kg bird is about 5.5 lb.
    assert u.kg_to_lb(2.5) == pytest.approx(5.5116, abs=1e-3)


# ---------------------------------------------------------------------------
# Airflow
# ---------------------------------------------------------------------------


def test_one_cfm_in_m3_per_hour():
    # 1 ft^3/min = 0.3048^3 m^3 * 60 min/h = 1.699 m^3/h
    assert u.cfm_to_m3ph(1.0) == pytest.approx(1.69901, abs=1e-5)


def test_typical_tunnel_fan_airflow_converts_sensibly():
    # ~40,000 m^3/h is a bit under 24,000 CFM -- the range a real
    # 130cm tunnel fan lives in.
    assert u.m3ph_to_cfm(40000.0) == pytest.approx(23542.6, abs=1.0)


def test_airflow_round_trips():
    for q in [1000.0, 45000.0, 250000.0]:
        assert u.cfm_to_m3ph(u.m3ph_to_cfm(q)) == pytest.approx(q)


# ---------------------------------------------------------------------------
# Pressure
# ---------------------------------------------------------------------------


def test_inch_water_column_matches_the_cooling_pad_citation():
    # cooling_pad.py cites 0.05 in. W.C. = 12.45 Pa; this must agree,
    # or the two modules are using different water-density conventions.
    assert u.inwc_to_pa(0.05) == pytest.approx(12.45, abs=0.01)


def test_typical_house_static_pressure_converts_sensibly():
    # 30 Pa is about 0.12 in. W.C. -- a normal tunnel design point.
    assert u.pa_to_inwc(30.0) == pytest.approx(0.1204, abs=1e-4)


# ---------------------------------------------------------------------------
# U-value
# ---------------------------------------------------------------------------


def test_u_value_round_trips():
    for u_si in [0.3, 0.6, 1.2]:
        assert u.u_imperial_to_si(u.u_si_to_imperial(u_si)) == pytest.approx(u_si)


def test_u_value_converts_to_the_expected_magnitude():
    # 1 W/(m^2*K) ~= 0.176 BTU/(h*ft^2*degF) -- a standard textbook
    # conversion, checked here against an independently known figure
    # rather than against this module's own arithmetic.
    assert u.u_si_to_imperial(1.0) == pytest.approx(0.1761, abs=1e-3)


# ---------------------------------------------------------------------------
# UnitSystem records
# ---------------------------------------------------------------------------


def test_metric_system_is_the_identity_everywhere():
    m = u.METRIC
    for from_si, to_si in [
        (m.length_from_si, m.length_to_si),
        (m.area_from_si, m.area_to_si),
        (m.temp_from_si, m.temp_to_si),
        (m.delta_temp_from_si, m.delta_temp_to_si),
        (m.mass_from_si, m.mass_to_si),
        (m.airflow_from_si, m.airflow_to_si),
        (m.pressure_from_si, m.pressure_to_si),
        (m.u_value_from_si, m.u_value_to_si),
    ]:
        assert from_si(42.0) == 42.0
        assert to_si(42.0) == 42.0


def test_every_unit_system_round_trips_every_quantity():
    for system in u.UNIT_SYSTEMS:
        pairs = [
            (system.length_from_si, system.length_to_si, 150.0),
            (system.area_from_si, system.area_to_si, 350.0),
            (system.temp_from_si, system.temp_to_si, 29.0),
            (system.delta_temp_from_si, system.delta_temp_to_si, 3.0),
            (system.mass_from_si, system.mass_to_si, 2.5),
            (system.airflow_from_si, system.airflow_to_si, 45000.0),
            (system.pressure_from_si, system.pressure_to_si, 30.0),
            (system.u_value_from_si, system.u_value_to_si, 0.6),
        ]
        for from_si, to_si, value in pairs:
            assert to_si(from_si(value)) == pytest.approx(value), system.name


def test_every_unit_system_has_a_suffix_for_every_quantity():
    for system in u.UNIT_SYSTEMS:
        suffixes = [
            system.length_suffix, system.area_suffix, system.temp_suffix,
            system.delta_temp_suffix, system.mass_suffix, system.airflow_suffix,
            system.pressure_suffix, system.u_value_suffix,
        ]
        for s in suffixes:
            assert s.strip(), f"{system.name} has an empty suffix"
