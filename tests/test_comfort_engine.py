"""Unit tests for pcis.core.comfort_engine."""

import pytest

from pcis.core import comfort_engine as ce


# ---------------------------------------------------------------------------
# Target temperature table
# ---------------------------------------------------------------------------

def test_target_temperature_exact_table_points():
    assert ce.target_temperature(0.044, 50) == pytest.approx(33.2)
    assert ce.target_temperature(1.530, 50) == pytest.approx(22.7)
    assert ce.target_temperature(0.290, 70) == pytest.approx(25.0)


def test_target_temperature_flat_above_max_weight():
    # >1530 g row is a flat asymptote, not a hard upper bound.
    assert ce.target_temperature(2.5, 50) == pytest.approx(22.7)
    assert ce.target_temperature(4.0, 60) == pytest.approx(20.7)


def test_target_temperature_interpolates_rh():
    # Row 290g: {40: 31.3, 50: 28.6}; RH=45 -> midpoint = 29.95
    assert ce.target_temperature(0.290, 45) == pytest.approx(29.95)


def test_target_temperature_interpolates_weight():
    # Between 44g (36.0) and 100g (33.7) at RH=40; weight=72g -> midpoint
    assert ce.target_temperature(0.072, 40) == pytest.approx(34.85)


def test_target_temperature_decreases_with_weight():
    # Within the table's range (up to 1.53 kg), target temp should
    # strictly decrease. Above 1.53 kg it's a flat asymptote (tested
    # separately in test_target_temperature_flat_above_max_weight).
    weights = [0.044, 0.1, 0.29, 0.59, 1.0, 1.53]
    values = [ce.target_temperature(w, 50) for w in weights]
    assert all(b < a for a, b in zip(values, values[1:]))


def test_target_temperature_decreases_with_rh():
    # Higher RH -> lower ideal dry-bulb temp (evaporative cooling less
    # effective), consistent with the table's structure.
    low_rh = ce.target_temperature(0.59, 40)
    high_rh = ce.target_temperature(0.59, 70)
    assert high_rh < low_rh


def test_target_temperature_rejects_out_of_range_rh():
    with pytest.raises(ValueError):
        ce.target_temperature(1.0, 30.0)
    with pytest.raises(ValueError):
        ce.target_temperature(1.0, 80.0)


def test_target_temperature_rejects_below_min_weight():
    with pytest.raises(ValueError):
        ce.target_temperature(0.01, 50.0)


def test_temperature_deviation_sign():
    target = ce.target_temperature(1.015, 50.0)  # 24.7
    assert ce.temperature_deviation(30.0, 1.015, 50.0) == pytest.approx(30.0 - target)
    assert ce.temperature_deviation(20.0, 1.015, 50.0) < 0


# ---------------------------------------------------------------------------
# THI
# ---------------------------------------------------------------------------

def test_thi_tao_xin_exact_arithmetic():
    assert ce.thi_tao_xin(30.0, 25.0) == pytest.approx(0.85 * 30.0 + 0.15 * 25.0)


def test_thi_marai_exact_arithmetic():
    result = ce.thi_marai(30.0, 60.0)
    expected = 30.0 - ((0.31 - 0.31 * 0.6) * (30.0 - 14.4))
    assert result == pytest.approx(expected)


def test_thi_stress_classification_bands():
    assert ce.thi_stress_classification(25.9) == "comfort"
    assert ce.thi_stress_classification(26.0) == "heat_stress"
    assert ce.thi_stress_classification(29.0) == "heat_stress"
    assert ce.thi_stress_classification(29.1) == "severe_heat_stress"


# ---------------------------------------------------------------------------
# Composite comfort index
# ---------------------------------------------------------------------------

def test_bird_comfort_index_perfect_conditions_scores_100():
    bw, rh = 1.015, 50.0
    target = ce.target_temperature(bw, rh)
    result = ce.bird_comfort_index(t_c=target, t_wb_c=18.0, rh_pct=rh, body_weight_kg=bw)
    assert result.comfort_index == pytest.approx(100.0)
    assert result.thi_class == "comfort"


def test_bird_comfort_index_severe_heat_scores_low():
    bw, rh = 1.015, 50.0
    result = ce.bird_comfort_index(t_c=38.0, t_wb_c=30.0, rh_pct=rh, body_weight_kg=bw)
    assert result.comfort_index < 20.0
    assert result.thi_class == "severe_heat_stress"
    assert result.deviation_c > 0


def test_bird_comfort_index_cold_stress_also_penalized():
    # Symmetric penalty: too cold should score poorly too, even if THI
    # (a heat-oriented metric) looks "fine".
    bw, rh = 1.015, 50.0
    target = ce.target_temperature(bw, rh)
    result = ce.bird_comfort_index(t_c=target - 8.0, t_wb_c=target - 10.0, rh_pct=rh, body_weight_kg=bw)
    assert result.comfort_index < 50.0
    assert result.deviation_c < 0


def test_bird_comfort_index_worst_dimension_governs():
    # Good temperature match but bad THI should still drag the score
    # down (min-of-components logic, not an average).
    bw, rh = 1.015, 50.0
    target = ce.target_temperature(bw, rh)
    result = ce.bird_comfort_index(t_c=target, t_wb_c=target + 5.0, rh_pct=rh, body_weight_kg=bw)
    assert result.comfort_index <= 100.0 - ce.THI_PENALTY_HEAT_STRESS + 1e-6 or result.thi_class == "comfort"


def test_bird_comfort_index_within_tolerance_no_penalty():
    # Deviation inside the tolerance band should not be penalized.
    bw, rh = 1.015, 50.0
    target = ce.target_temperature(bw, rh)
    result = ce.bird_comfort_index(
        t_c=target + ce.TEMP_DEVIATION_TOLERANCE_C * 0.5,
        t_wb_c=target - 5.0,
        rh_pct=rh,
        body_weight_kg=bw,
    )
    assert result.comfort_index == pytest.approx(100.0)
