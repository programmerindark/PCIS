"""Sensor block names must never be confused with physical placement.

Ecowitt labels blocks by sensor TYPE: the WS90 array is always "outdoor"
and the gateway console probe is always "indoor", regardless of where the
hardware actually hangs. On this farm the install is reversed -- the array
is inside the house and the console is outside.

Reversing these silently inverts the moisture balance: PCIS would compare
house air against house air, conclude ventilation removes water, and
recommend fans that in reality pump WETTER air in. These tests pin the
mapping so the failure cannot recur unnoticed.
"""
from __future__ import annotations

from backend.app import ecowitt

# The farm's actual first live reading.
BLOCKS = {
    "outdoor": {"temperature_c": 24.9, "humidity_pct": 96.0},   # WS90  -> INSIDE
    "indoor": {"temperature_c": 24.7, "humidity_pct": 99.0},    # console -> OUTSIDE
}


def test_default_maps_the_ws90_block_to_inside_the_house():
    got = ecowitt.select_house_conditions(BLOCKS)
    assert got["indoor_t_c"] == 24.9
    assert got["indoor_rh_pct"] == 96.0
    assert got["source_block"] == "outdoor"


def test_the_other_block_is_reported_as_measured_outdoor():
    """Two modules means ambient is measured, not forecast."""
    got = ecowitt.select_house_conditions(BLOCKS)
    assert got["outdoor_measured"] is True
    assert got["outdoor_t_c"] == 24.7
    assert got["outdoor_rh_pct"] == 99.0
    assert got["outdoor_source_block"] == "indoor"


def test_placement_can_be_stated_explicitly_for_a_normal_install():
    """A farm that mounted it the conventional way must also work."""
    got = ecowitt.select_house_conditions(
        BLOCKS, indoor_block="indoor", outdoor_block="outdoor"
    )
    assert got["indoor_t_c"] == 24.7
    assert got["outdoor_t_c"] == 24.9


def test_single_module_reports_no_measured_outdoor():
    """One sensor cannot measure both sides; say so rather than guess."""
    got = ecowitt.select_house_conditions({"outdoor": BLOCKS["outdoor"]})
    assert got["indoor_t_c"] == 24.9
    assert got["outdoor_measured"] is False
    assert got["outdoor_t_c"] is None


def test_three_blocks_do_not_get_an_inferred_outdoor():
    """With extra channels present, inference is ambiguous -- refuse it."""
    blocks = {**BLOCKS, "temp_and_humidity_ch1": {"temperature_c": 26.0}}
    got = ecowitt.select_house_conditions(blocks)
    assert got["outdoor_measured"] is False


def test_wind_is_exposed_as_a_measured_in_house_air_speed():
    """The WS90 anemometer indoors reads fan-driven tunnel velocity."""
    payload = {"data": {"wind": {"wind_speed": {"value": "7.2"}}}}
    checks = ecowitt.parse_cross_checks(payload)
    assert checks["measured_air_speed_mps"] == 3.22


def test_pressure_is_read_from_the_absolute_reading():
    """Sea-level-corrected 'relative' would defeat the whole point."""
    payload = {"data": {"pressure": {"absolute": {"value": "946.2"},
                                     "relative": {"value": "1013.0"}}}}
    assert ecowitt.parse_pressure_hpa(payload) == 946.2
