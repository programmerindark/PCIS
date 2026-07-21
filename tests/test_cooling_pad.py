"""Unit tests for pcis.equipment.cooling_pad."""

import pytest

from pcis.equipment.cooling_pad import (
    CELDEK_7090_15_100MM,
    CELDEK_7090_15_150MM,
    COOLING_PAD_CATALOG,
    MUNTERS_CELDEK_7090_SATURATION_EFFICIENCY_PCT,
    MUNTERS_CURVE_READING_TOLERANCE_PCT,
    CoolingPad,
    exceeds_droplet_risk_velocity,
    leaving_air_state,
    saturation_efficiency_at_velocity,
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


# ---------------------------------------------------------------------------
# Munters chart-digitized saturation-efficiency curve
# ---------------------------------------------------------------------------


def test_curve_covers_the_four_depths_munters_plots():
    assert set(MUNTERS_CELDEK_7090_SATURATION_EFFICIENCY_PCT) == {100.0, 150.0, 200.0, 300.0}


def test_efficiency_decreases_with_velocity_for_every_depth():
    # The physical law the chart shows: less contact time at higher
    # face velocity means less saturation.
    for depth, points in MUNTERS_CELDEK_7090_SATURATION_EFFICIENCY_PCT.items():
        effs = [e for _, e in points]
        assert effs == sorted(effs, reverse=True), f"depth {depth} not monotonic"


def test_efficiency_increases_with_pad_depth_at_every_velocity():
    depths = sorted(MUNTERS_CELDEK_7090_SATURATION_EFFICIENCY_PCT)
    velocities = [v for v, _ in MUNTERS_CELDEK_7090_SATURATION_EFFICIENCY_PCT[depths[0]]]
    for v in velocities:
        effs = [saturation_efficiency_at_velocity(d, v) for d in depths]
        assert effs == sorted(effs), f"depth ordering wrong at {v} m/s"


def test_exact_gridline_lookup_returns_the_digitized_value():
    assert saturation_efficiency_at_velocity(150.0, 2.0) == pytest.approx(0.89)
    assert saturation_efficiency_at_velocity(100.0, 5.0) == pytest.approx(0.68)


def test_interpolates_between_gridlines():
    # Midway between the 2 m/s (89%) and 3 m/s (85%) points for 150mm.
    assert saturation_efficiency_at_velocity(150.0, 2.5) == pytest.approx(0.87)


def test_refuses_unplotted_depth():
    with pytest.raises(ValueError, match="not a depth Munters plots"):
        saturation_efficiency_at_velocity(125.0, 2.0)


def test_refuses_to_extrapolate_beyond_chart_range():
    with pytest.raises(ValueError, match="refusing to extrapolate"):
        saturation_efficiency_at_velocity(150.0, 6.0)
    with pytest.raises(ValueError, match="refusing to extrapolate"):
        saturation_efficiency_at_velocity(150.0, 0.1)


def test_droplet_risk_flag_matches_the_shaded_chart_region():
    assert exceeds_droplet_risk_velocity(4.0) is True
    assert exceeds_droplet_risk_velocity(2.0) is False


def test_reading_tolerance_is_stated_and_nonzero():
    # A chart-digitized value that claimed zero reading error would be
    # misrepresenting its own provenance.
    assert MUNTERS_CURVE_READING_TOLERANCE_PCT > 0


# ---------------------------------------------------------------------------
# The manufacturer-vs-extension disagreement
#
# This is the finding that came out of digitizing the curve, and these
# tests exist to stop anyone (including a future me) from quietly
# "fixing" the default to the more flattering number.
# ---------------------------------------------------------------------------


def test_manufacturer_curve_is_substantially_more_optimistic_than_the_default():
    pad = CELDEK_7090_15_150MM
    manufacturer = saturation_efficiency_at_velocity(pad.depth_mm, pad.design_velocity_mps)
    gap_pct = (manufacturer - pad.assumed_saturation_efficiency) * 100.0
    # The gap is real and large -- far outside the chart reading tolerance.
    assert gap_pct > 3 * MUNTERS_CURVE_READING_TOLERANCE_PCT


def test_defaults_still_use_the_conservative_extension_figure():
    # Being optimistic about cooling capacity under-ventilates birds in
    # a heat wave. The catalog defaults must stay conservative.
    for pad in COOLING_PAD_CATALOG:
        manufacturer = saturation_efficiency_at_velocity(pad.depth_mm, pad.design_velocity_mps)
        assert pad.assumed_saturation_efficiency < manufacturer


def test_using_the_manufacturer_curve_predicts_colder_supply_air():
    # Demonstrates the practical consequence of the gap: the optimistic
    # figure produces colder supply air, which would flow through to
    # lower airflow requirements and fewer fans.
    pad = CELDEK_7090_15_150MM
    outdoor_t, outdoor_rh = 38.0, 30.0
    conservative = leaving_air_state(outdoor_t, outdoor_rh, pad.assumed_saturation_efficiency)
    optimistic = leaving_air_state(
        outdoor_t, outdoor_rh,
        saturation_efficiency_at_velocity(pad.depth_mm, pad.design_velocity_mps),
    )
    assert optimistic.t_c < conservative.t_c
