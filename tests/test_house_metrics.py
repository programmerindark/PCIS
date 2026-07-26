"""Tests for the derived house metrics (density, CO2, ACH)."""

import pytest

from pcis.core import house_metrics as hm


def _m(**kw):
    d = dict(
        bird_count=20000, body_weight_kg=2.0, floor_area_m2=1800.0,
        house_volume_m3=5400.0, delivered_airflow_m3_per_h=400_000.0,
        co2_production_m3_per_h=60.0, outdoor_co2_ppm=420.0,
    )
    d.update(kw)
    return hm.assess(**d)


def test_stocking_density_is_kg_per_m2():
    # 20000 birds x 2 kg / 1800 m2 = 22.2 kg/m2
    a = _m()
    assert a.stocking_density_kg_m2 == pytest.approx(22.2, abs=0.1)
    assert a.density_within_limit is True


def test_density_flags_over_limit():
    # heavier birds push past the 39 kg/m2 derogation limit
    a = _m(body_weight_kg=4.0)
    assert a.stocking_density_kg_m2 == pytest.approx(44.4, abs=0.1)
    assert a.density_within_limit is False
    assert "exceeds" in a.note


def test_eu_limits_are_the_cited_values():
    assert hm.DENSITY_LIMIT_DEFAULT == 33.0
    assert hm.DENSITY_LIMIT_DEROGATION == 39.0
    assert hm.DENSITY_LIMIT_MAX == 42.0


def test_co2_mass_balance():
    # outdoor + production/airflow * 1e6 = 420 + 60/400000*1e6 = 570 ppm
    a = _m()
    assert a.estimated_co2_ppm == pytest.approx(570, abs=1)
    assert a.co2_within_guideline is True


def test_co2_rises_when_ventilation_drops():
    low = _m(delivered_airflow_m3_per_h=20_000.0)
    assert low.estimated_co2_ppm > 3000
    assert low.co2_within_guideline is False


def test_air_changes_and_per_bird():
    a = _m()
    assert a.air_changes_per_hour == pytest.approx(400_000 / 5400, abs=0.2)
    assert a.airflow_per_bird_m3_h == pytest.approx(20.0, abs=0.1)


def test_missing_airflow_is_handled():
    a = _m(delivered_airflow_m3_per_h=None)
    assert a.estimated_co2_ppm is None
    assert a.air_changes_per_hour is None
    assert a.stocking_density_kg_m2 > 0
