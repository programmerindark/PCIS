"""Unit tests for pcis.equipment.fan_curve.

Reference values are the exact points published in Big Dutchman's
"Wall Fans" catalog (en 9/2019) for the AirMaster V130/VC130 family --
see fan_curve.py module docstring for the full citation and the
"Multifan 130" naming note.
"""

import pytest

from pcis.equipment.fan_curve import FAN_CATALOG, FanCurve


def _find(model_substring: str) -> FanCurve:
    for fc in FAN_CATALOG:
        if model_substring in fc.model:
            return fc
    raise AssertionError(f"no fan found matching {model_substring!r}")


def test_catalog_has_four_130cm_records():
    assert len(FAN_CATALOG) == 4
    assert all(fc.diameter_m == pytest.approx(1.30) for fc in FAN_CATALOG)


def test_every_record_has_source_and_manufacturer():
    for fc in FAN_CATALOG:
        assert fc.manufacturer == "Big Dutchman"
        assert "bigdutchmanusa.com" in fc.source
        assert len(fc.power_w) == len(fc.airflow_m3_per_h)


def test_v130_1hp_exact_published_points():
    fc = _find("V130-3-1.0 PS")
    assert fc.airflow_at_static_pressure(0) == pytest.approx(40400)
    assert fc.airflow_at_static_pressure(20) == pytest.approx(36100)
    assert fc.airflow_at_static_pressure(30) == pytest.approx(33100)
    assert fc.airflow_at_static_pressure(40) == pytest.approx(29900)


def test_v130_1_5hp_exact_published_points():
    fc = _find("V130-3-1.5 PS")
    assert fc.airflow_at_static_pressure(0) == pytest.approx(46700)
    assert fc.airflow_at_static_pressure(60) == pytest.approx(31900)


def test_vc130_cone_variant_outperforms_no_cone_at_same_power_class():
    # The catalog markets cone fans as offering "higher air
    # performance" at the same pressure -- verify VC130-1.0PS beats
    # V130-1.0PS at every shared pressure point.
    no_cone = _find("V130-3-1.0 PS")
    cone = _find("VC130-3-1.0 PS")
    for sp in (0, 20, 30, 40):
        assert cone.airflow_at_static_pressure(sp) > no_cone.airflow_at_static_pressure(sp)


def test_interpolation_between_published_points():
    fc = _find("V130-3-1.0 PS")
    # Midpoint between 20 Pa (36100) and 30 Pa (33100) should linearly
    # interpolate to 34600.
    assert fc.airflow_at_static_pressure(25) == pytest.approx(34600)


def test_airflow_decreases_as_pressure_increases():
    for fc in FAN_CATALOG:
        pairs = sorted(zip(fc.static_pressure_pa, fc.airflow_m3_per_h))
        flows = [p[1] for p in pairs]
        assert all(a > b for a, b in zip(flows, flows[1:]))


def test_extrapolation_beyond_tested_range_raises():
    fc = _find("V130-3-1.0 PS")  # tested only up to 40 Pa
    with pytest.raises(ValueError):
        fc.airflow_at_static_pressure(100)
    with pytest.raises(ValueError):
        fc.airflow_at_static_pressure(-5)


def test_power_w_computed_consistently_with_spec_power():
    # power_w = spec_power_w_per_1000m3h * (airflow/1000); check the
    # 0 Pa point for V130-3-1.0 PS: 27.5 * 40400/1000 = 1111.0 W.
    fc = _find("V130-3-1.0 PS")
    assert fc.power_w[0] == pytest.approx(27.5 * 40400 / 1000.0)


def test_fan_curve_requires_source():
    with pytest.raises(ValueError):
        FanCurve(
            manufacturer="Test",
            model="X",
            diameter_m=1.0,
            static_pressure_pa=[0, 10],
            airflow_m3_per_h=[100, 90],
            source="",
        )


def test_fan_curve_rejects_mismatched_lengths():
    with pytest.raises(ValueError):
        FanCurve(
            manufacturer="Test",
            model="X",
            diameter_m=1.0,
            static_pressure_pa=[0, 10, 20],
            airflow_m3_per_h=[100, 90],
            source="test source",
        )
