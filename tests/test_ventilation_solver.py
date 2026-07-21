"""Unit tests for pcis.core.ventilation_solver."""

import pytest

from pcis.core import psychrometrics as psy
from pcis.core import ventilation_solver as vs


# ---------------------------------------------------------------------------
# Aviagen minimum ventilation table
# ---------------------------------------------------------------------------

def test_minimum_ventilation_exact_table_points():
    assert vs.minimum_ventilation_rate_aviagen(1.00) == pytest.approx(0.864)
    assert vs.minimum_ventilation_rate_aviagen(0.05) == pytest.approx(0.080)
    assert vs.minimum_ventilation_rate_aviagen(4.40) == pytest.approx(2.625)


def test_minimum_ventilation_interpolates_between_points():
    # Between 2.40 kg (1.666) and 2.60 kg (1.769); midpoint -> 1.7175
    result = vs.minimum_ventilation_rate_aviagen(2.5)
    assert result == pytest.approx(1.7175)


def test_minimum_ventilation_increases_with_weight():
    weights = [0.1, 0.5, 1.0, 2.0, 3.0, 4.0]
    values = [vs.minimum_ventilation_rate_aviagen(w) for w in weights]
    assert all(b > a for a, b in zip(values, values[1:]))


def test_minimum_ventilation_rejects_out_of_table_range():
    with pytest.raises(ValueError):
        vs.minimum_ventilation_rate_aviagen(0.01)
    with pytest.raises(ValueError):
        vs.minimum_ventilation_rate_aviagen(5.0)


# ---------------------------------------------------------------------------
# Sensible-heat-driven airflow (round-trip / self-consistency checks)
# ---------------------------------------------------------------------------

def test_sensible_heat_airflow_round_trip_recovers_load():
    net_sensible_w = 100_000.0
    delta_t_c = 5.0
    inlet_t_c, inlet_rh = 25.0, 60.0

    airflow_m3_per_h = vs.required_airflow_for_sensible_heat(
        net_sensible_w, delta_t_c, inlet_t_c, inlet_rh
    )

    w_inlet = psy.humidity_ratio_from_relative_humidity(inlet_t_c, inlet_rh)
    v_specific = psy.specific_volume(inlet_t_c, w_inlet)
    cp_moist_j = (1.006 + 1.86 * w_inlet) * 1000.0

    m_dot_da_kg_per_s = (airflow_m3_per_h / 3600.0) / v_specific
    recovered_q = m_dot_da_kg_per_s * cp_moist_j * delta_t_c
    assert recovered_q == pytest.approx(net_sensible_w, rel=1e-9)


def test_sensible_heat_airflow_rejects_nonpositive_load_or_deltaT():
    with pytest.raises(ValueError):
        vs.required_airflow_for_sensible_heat(-100.0, 5.0, 25.0, 60.0)
    with pytest.raises(ValueError):
        vs.required_airflow_for_sensible_heat(100.0, 0.0, 25.0, 60.0)


def test_sensible_heat_airflow_increases_as_deltaT_shrinks():
    # Tighter allowed temperature rise -> more air needed to carry the
    # same heat load.
    airflow_wide = vs.required_airflow_for_sensible_heat(50_000.0, 8.0, 25.0, 60.0)
    airflow_tight = vs.required_airflow_for_sensible_heat(50_000.0, 2.0, 25.0, 60.0)
    assert airflow_tight > airflow_wide


# ---------------------------------------------------------------------------
# Moisture-driven airflow
# ---------------------------------------------------------------------------

def test_moisture_airflow_round_trip_recovers_load():
    moisture_load = 20.0  # kg/h
    indoor_t, indoor_rh = 24.0, 65.0
    inlet_t, inlet_rh = 5.0, 80.0

    airflow_m3_per_h = vs.required_airflow_for_moisture(
        moisture_load, indoor_t, indoor_rh, inlet_t, inlet_rh
    )

    w_indoor = psy.humidity_ratio_from_relative_humidity(indoor_t, indoor_rh)
    w_inlet = psy.humidity_ratio_from_relative_humidity(inlet_t, inlet_rh)
    v_specific = psy.specific_volume(inlet_t, w_inlet)

    m_dot_da_kg_per_h = airflow_m3_per_h / v_specific
    recovered_moisture = m_dot_da_kg_per_h * (w_indoor - w_inlet)
    assert recovered_moisture == pytest.approx(moisture_load, rel=1e-9)


def test_moisture_airflow_rejects_when_indoor_not_more_humid():
    # inlet more humid than indoor target -> ventilation can't remove
    # moisture this way; should raise rather than return nonsense.
    with pytest.raises(ValueError):
        vs.required_airflow_for_moisture(10.0, 20.0, 40.0, 20.0, 90.0)


# ---------------------------------------------------------------------------
# CO2-driven airflow
# ---------------------------------------------------------------------------

def test_co2_ventilation_requirement_exact_arithmetic():
    # V = 1.0 / ((3000-420)*1e-6) = 387.597... m3/h
    result = vs.co2_ventilation_requirement(1.0, target_indoor_ppm=3000.0, outdoor_ppm=420.0)
    assert result == pytest.approx(1.0 / (2580e-6))


def test_co2_ventilation_requirement_default_uses_aviagen_threshold():
    result_default = vs.co2_ventilation_requirement(1.0, outdoor_ppm=420.0)
    result_explicit = vs.co2_ventilation_requirement(1.0, target_indoor_ppm=vs.AVIAGEN_MAX_CO2_PPM, outdoor_ppm=420.0)
    assert result_default == pytest.approx(result_explicit)


def test_co2_ventilation_requirement_rejects_target_below_outdoor():
    with pytest.raises(ValueError):
        vs.co2_ventilation_requirement(1.0, target_indoor_ppm=300.0, outdoor_ppm=420.0)


# ---------------------------------------------------------------------------
# Air changes / hour, tunnel airspeed
# ---------------------------------------------------------------------------

def test_air_changes_per_hour():
    assert vs.air_changes_per_hour(airflow_m3_per_h=10000.0, house_volume_m3=2000.0) == pytest.approx(5.0)


def test_air_changes_per_hour_rejects_nonpositive_volume():
    with pytest.raises(ValueError):
        vs.air_changes_per_hour(1000.0, 0.0)


def test_tunnel_airspeed():
    # 36000 m3/h = 10 m3/s; over 5 m2 cross-section -> 2 m/s
    assert vs.tunnel_airspeed(airflow_m3_per_h=36000.0, cross_section_area_m2=5.0) == pytest.approx(2.0)


# ---------------------------------------------------------------------------
# Governing airflow / fan count
# ---------------------------------------------------------------------------

def test_governing_airflow_takes_the_max():
    assert vs.governing_airflow(100.0, 500.0, 300.0) == pytest.approx(500.0)


def test_governing_airflow_requires_at_least_one_value():
    with pytest.raises(ValueError):
        vs.governing_airflow()


def test_required_fan_count_rounds_up():
    assert vs.required_fan_count(required_airflow_m3_per_h=100_000.0, fan_airflow_m3_per_h=40_000.0) == 3
    assert vs.required_fan_count(required_airflow_m3_per_h=80_000.0, fan_airflow_m3_per_h=40_000.0) == 2


def test_required_fan_count_zero_requirement_needs_zero_fans():
    assert vs.required_fan_count(0.0, 40_000.0) == 0


def test_required_fan_count_rejects_invalid_fan_airflow():
    with pytest.raises(ValueError):
        vs.required_fan_count(1000.0, 0.0)
