"""SKOV's humidity curve as a benchmark, not a calculation input.

Aviagen's target-temperature table stops at 70% RH, so above that PCIS
clamps and warns. That warning is honest but abstract: "outside the tested
range" does not tell an operator whether 96% is slightly unusual or wildly
wrong.

SKOV's curve answers a DIFFERENT question -- what humidity is acceptable at
a given age, not what temperature to hold -- so it cannot extend Aviagen's
table. But it is a working commercial controller's own limit, which makes
it a legitimate yardstick: it turns "no data up here" into "17 points past
what a real controller would accept".

These tests pin two things: that the benchmark is reported, and that it
stays strictly informational.
"""
from __future__ import annotations

import pytest

from backend.app.engine_api import _surfaces
from pcis.core import recommendation_engine as re
from pcis.core import skov_reference as skov
from pcis.equipment.fan_curve import FAN_CATALOG


def _rec(indoor_rh, age=37):
    return re.recommend(
        bird_count=15760, body_weight_kg=2.496, indoor_t_c=21.0,
        indoor_rh_pct=indoor_rh, outdoor_t_c=24.7, outdoor_rh_pct=99.0,
        envelope_surfaces=_surfaces(120.0, 15.0, 3.0, "insulated"),
        fan=FAN_CATALOG[0], design_static_pressure_pa=30.0, delta_t_c=3.0,
        cooling_pad=None, house_cross_section_m2=45.0,
        heater_capacity_w=None, bird_age_days=age,
    )


# --- the curve itself -----------------------------------------------------

def test_curve_matches_the_transcribed_screenshots():
    assert skov.expected_humidity_pct(28) == pytest.approx(70.0)
    assert skov.expected_humidity_pct(35) == pytest.approx(77.0)
    assert skov.expected_humidity_pct(42) == pytest.approx(85.0)


def test_curve_interpolates_between_tabulated_days():
    assert 77.0 < skov.expected_humidity_pct(37) < 85.0


def test_comparison_reports_the_excess():
    got = skov.compare_humidity(42, 96.0)
    assert got["expected_pct"] == 85
    assert got["excess_pct"] == 11
    assert got["above_controller_limit"] is True


def test_normal_humidity_is_not_flagged():
    assert skov.compare_humidity(42, 70.0)["above_controller_limit"] is False


# --- how the engine uses it ----------------------------------------------

def test_benchmark_is_attached_to_the_recommendation():
    b = _rec(96.0).skov_humidity_benchmark
    assert b is not None and b["excess_pct"] > 0


def test_the_clamp_warning_now_carries_a_concrete_number():
    """The whole point: abstract caveat becomes a measurable statement."""
    rec = _rec(96.0)
    txt = " ".join(rec.explanation)
    assert "SKOV Viper Touch controller expects about" in txt
    assert "points above what a commercial controller would accept" in txt


def test_benchmark_changes_no_fan_count():
    """It is context. If it moved a decision it would be an override."""
    assert _rec(96.0).fans_on == _rec(96.0).fans_on
    # Same conditions, benchmark present vs absent (no age -> no benchmark).
    with_age = _rec(96.0)
    without = re.recommend(
        bird_count=15760, body_weight_kg=2.496, indoor_t_c=21.0,
        indoor_rh_pct=96.0, outdoor_t_c=24.7, outdoor_rh_pct=99.0,
        envelope_surfaces=_surfaces(120.0, 15.0, 3.0, "insulated"),
        fan=FAN_CATALOG[0], design_static_pressure_pa=30.0, delta_t_c=3.0,
        cooling_pad=None, house_cross_section_m2=45.0,
        heater_capacity_w=None,
    )
    assert with_age.fans_on == without.fans_on
    assert without.skov_humidity_benchmark is None


def test_benchmark_does_not_alter_the_target_temperature():
    """Aviagen still wins on target temp -- SKOV fills gaps, not overrides."""
    rec = _rec(96.0)
    assert rec.comfort.target_temp_c == pytest.approx(19.3, abs=0.1)


def test_no_benchmark_text_when_humidity_is_normal():
    txt = " ".join(_rec(60.0).explanation)
    assert "commercial controller would accept" not in txt
