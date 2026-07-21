"""Unit tests for pcis.core.bird_metabolism.

Reference cross-checks:
  - total_heat_production is checked against the order of magnitude
    shown in Aarnink (2018) Figure 4, which compares CIGR-calculated
    and measured broiler heat production over 0-3.5 kg live weight
    (measured tops out around 20-25 W near market weight; the paper
    reports the CIGR formula runs ~11.3% higher than measured on
    average across that range).
  - CO2 production is checked against the order of magnitude in
    Pedersen et al. (2008), which reports typical broiler CO2
    production factors of 0.165-0.180 m3/h per heat-production-unit.
"""

import pytest

from pcis.core import bird_metabolism as bm


# ---------------------------------------------------------------------------
# Total heat production
# ---------------------------------------------------------------------------

def test_total_heat_production_day_old_chick():
    # ~44 g day-old chick should produce a little over 1 W.
    q = bm.total_heat_production(0.044)
    assert 0.5 < q < 2.0


def test_total_heat_production_market_weight():
    # ~2.5 kg broiler: CIGR eq gives ~21 W, consistent with Aarnink
    # (2018) Figure 4 (measured ~19 W, CIGR ~11.3% higher on average).
    q = bm.total_heat_production(2.5)
    assert q == pytest.approx(21.1, rel=0.02)


def test_total_heat_production_increases_with_weight():
    weights = [0.1, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0]
    values = [bm.total_heat_production(w) for w in weights]
    assert all(b > a for a, b in zip(values, values[1:]))


def test_total_heat_production_rejects_nonpositive_weight():
    with pytest.raises(ValueError):
        bm.total_heat_production(0.0)
    with pytest.raises(ValueError):
        bm.total_heat_production(-1.0)


# ---------------------------------------------------------------------------
# Sensible / latent split
# ---------------------------------------------------------------------------

def test_sensible_plus_latent_equals_total():
    for bw in (0.5, 1.5, 2.5):
        for t in (10.0, 20.0, 30.0, 35.0):
            q_total = bm.total_heat_production(bw)
            q_sens = bm.sensible_heat_production(bw, t)
            q_lat = bm.latent_heat_production(bw, t)
            assert q_sens + q_lat == pytest.approx(q_total, rel=1e-9)


def test_sensible_fraction_at_20c_matches_cigr_equation13():
    # At Ti = 20 C the middle term 20*(20-Ti) vanishes, but the
    # -0.228*Ti^2 term does not: bracket = 0.61*(1000 - 0.228*400)
    # = 0.61*908.8 -> fraction = 0.554368. This is a direct,
    # hand-computed check of the Eq. 13 constants (0.61, 20, 0.228).
    bw = 2.0
    q_total = bm.total_heat_production(bw)
    q_sens = bm.sensible_heat_production(bw, 20.0)
    assert q_sens / q_total == pytest.approx(0.554368, rel=1e-9)


def test_sensible_fraction_decreases_as_temperature_rises():
    # Heat-stressed birds shift from sensible to evaporative
    # (latent) heat loss -- a basic physiological/engineering check.
    bw = 2.0
    q_total = bm.total_heat_production(bw)
    frac_cool = bm.sensible_heat_production(bw, 15.0) / q_total
    frac_hot = bm.sensible_heat_production(bw, 32.0) / q_total
    assert frac_hot < frac_cool


# ---------------------------------------------------------------------------
# Moisture production
# ---------------------------------------------------------------------------

def test_moisture_production_positive_and_reasonable():
    # A near-market-weight bird at a typical grow-out temperature
    # should produce on the order of single-digit to low-teens g/h,
    # not zero and not kilograms.
    m_kg_per_h = bm.moisture_production(2.5, 24.0)
    assert 0.005 < m_kg_per_h < 0.030


def test_moisture_production_increases_with_temperature():
    # More latent heat loss at higher temperature -> more moisture.
    bw = 2.0
    m_cool = bm.moisture_production(bw, 18.0)
    m_hot = bm.moisture_production(bw, 32.0)
    assert m_hot > m_cool


# ---------------------------------------------------------------------------
# CO2 production
# ---------------------------------------------------------------------------

def test_co2_production_market_weight_order_of_magnitude():
    # ~2.5 kg bird: Qtotal ~21 W -> ~0.0211 hpu -> ~0.0035 m3/h
    # (~3.5 L/h), consistent with Pedersen et al. (2008) factors.
    co2 = bm.co2_production(2.5)
    assert co2 == pytest.approx(0.00348, rel=0.05)


def test_co2_production_house_level_exceeds_animal_level():
    # House-level factors include manure/litter contribution and
    # should be >= animal-level factors per Pedersen et al. (2008)
    # Table 6.
    co2_animal = bm.co2_production(2.5, level="animal")
    co2_house = bm.co2_production(2.5, level="house")
    assert co2_house >= co2_animal


def test_co2_production_rejects_invalid_level():
    with pytest.raises(ValueError):
        bm.co2_production(2.0, level="bogus")


def test_co2_production_increases_with_weight():
    co2_small = bm.co2_production(0.3)
    co2_large = bm.co2_production(2.5)
    assert co2_large > co2_small
