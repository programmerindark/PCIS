"""Unit tests for pcis.equipment.cooling_pad."""

import pytest

from pcis.equipment.cooling_pad import (
    CELDEK_7090_15_100MM,
    CELDEK_7090_15_150MM,
    COOLING_PAD_CATALOG,
    CoolingPad,
    leaving_air_state,
)


def test_catalog_has_two_records():
    assert len(COOLING_PAD_CATALOG) == 2


def test_every_record_has_source_and_valid_efficiency():
    for pad in COOLING_PAD_CATALOG:
        assert pad.source.strip()
        assert 0.0 < pad.assumed_saturation_efficiency <= 1.0


def test_150mm_pad_design_point_matches_msu_extension():
    # 350 fpm = 1.7780 m/s
    assert CELDEK_7090_15_150MM.design_velocity_mps == pytest.approx(1.78, abs=0.01)
    assert CELDEK_7090_15_150MM.assumed_saturation_efficiency == pytest.approx(0.75)


def test_150mm_pad_pressure_drop_matches_uga_extension():
    # 0.05 in. W.C. = 12.4544 Pa
    assert CELDEK_7090_15_150MM.design_pad_pressure_drop_pa == pytest.approx(12.45, abs=0.1)


def test_100mm_pad_design_point_matches_uga_extension():
    # 225 fpm = 1.143 m/s
    assert CELDEK_7090_15_100MM.design_velocity_mps == pytest.approx(1.14, abs=0.01)
    # Cited 70-75% band, midpoint used -- no longer the old unverified
    # 0.65 placeholder.
    assert 0.70 <= CELDEK_7090_15_100MM.assumed_saturation_efficiency <= 0.75
    assert CELDEK_7090_15_100MM.design_pad_pressure_drop_pa == pytest.approx(12.45, abs=0.1)


def test_cooling_pad_rejects_non_positive_pressure_drop():
    with pytest.raises(ValueError):
        CoolingPad(
            manufacturer="Test", model="X", depth_mm=150.0, material="cellulose",
            design_velocity_mps=1.5, design_velocity_range_mps=(0.5, 3.0),
            assumed_saturation_efficiency=0.7, source="test",
            design_pad_pressure_drop_pa=0.0,
        )


def test_cooling_pad_requires_source():
    with pytest.raises(ValueError):
        CoolingPad(
            manufacturer="Test",
            model="X",
            depth_mm=150.0,
            material="cellulose",
            design_velocity_mps=1.5,
            design_velocity_range_mps=(0.5, 3.0),
            assumed_saturation_efficiency=0.7,
            source="",
        )


def test_cooling_pad_rejects_invalid_efficiency():
    with pytest.raises(ValueError):
        CoolingPad(
            manufacturer="Test", model="X", depth_mm=150.0, material="cellulose",
            design_velocity_mps=1.5, design_velocity_range_mps=(0.5, 3.0),
            assumed_saturation_efficiency=1.5, source="test",
        )
    with pytest.raises(ValueError):
        CoolingPad(
            manufacturer="Test", model="X", depth_mm=150.0, material="cellulose",
            design_velocity_mps=1.5, design_velocity_range_mps=(0.5, 3.0),
            assumed_saturation_efficiency=0.0, source="test",
        )


# ---------------------------------------------------------------------------
# leaving_air_state
# ---------------------------------------------------------------------------

def test_leaving_air_state_cools_the_air():
    result = leaving_air_state(inlet_t_c=35.0, inlet_rh_pct=40.0, efficiency=0.75)
    assert result.t_c < 35.0
    assert result.rh_pct > 40.0  # humidified


def test_leaving_air_state_at_zero_efficiency_is_identity():
    result = leaving_air_state(inlet_t_c=35.0, inlet_rh_pct=40.0, efficiency=1e-9)
    assert result.t_c == pytest.approx(35.0, abs=1e-3)
    assert result.rh_pct == pytest.approx(40.0, abs=1e-2)


def test_leaving_air_state_at_full_efficiency_reaches_saturation():
    result = leaving_air_state(inlet_t_c=35.0, inlet_rh_pct=40.0, efficiency=1.0)
    assert result.t_c == pytest.approx(result.wet_bulb_c, abs=1e-6)
    assert result.rh_pct == pytest.approx(100.0, abs=0.5)


def test_leaving_air_state_more_efficiency_means_more_cooling():
    low = leaving_air_state(inlet_t_c=35.0, inlet_rh_pct=40.0, efficiency=0.5)
    high = leaving_air_state(inlet_t_c=35.0, inlet_rh_pct=40.0, efficiency=0.9)
    assert high.t_c < low.t_c


def test_leaving_air_state_rejects_invalid_efficiency():
    with pytest.raises(ValueError):
        leaving_air_state(30.0, 50.0, efficiency=0.0)
    with pytest.raises(ValueError):
        leaving_air_state(30.0, 50.0, efficiency=1.1)


def test_leaving_air_state_using_catalog_design_efficiency():
    pad = CELDEK_7090_15_150MM
    result = leaving_air_state(
        inlet_t_c=38.0, inlet_rh_pct=35.0, efficiency=pad.assumed_saturation_efficiency
    )
    assert result.t_c < 38.0
    assert result.efficiency == pytest.approx(0.75)
