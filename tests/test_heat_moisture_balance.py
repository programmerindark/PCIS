"""Unit tests for pcis.core.heat_moisture_balance."""

import pytest

from pcis.core import bird_metabolism as bm
from pcis.core import heat_moisture_balance as hmb


# ---------------------------------------------------------------------------
# Envelope conduction
# ---------------------------------------------------------------------------

def test_r_value_to_u_value():
    assert hmb.r_value_to_u_value(2.0) == pytest.approx(0.5)


def test_r_value_to_u_value_rejects_nonpositive():
    with pytest.raises(ValueError):
        hmb.r_value_to_u_value(0.0)


def test_envelope_conduction_loss_basic():
    # Q = U*A*dT = 0.5 * 100 * (24-5) = 950 W
    q = hmb.envelope_conduction_loss(u_value=0.5, area_m2=100.0, t_in_c=24.0, t_out_c=5.0)
    assert q == pytest.approx(950.0)


def test_envelope_conduction_loss_reverses_sign_when_outside_hotter():
    q = hmb.envelope_conduction_loss(u_value=0.5, area_m2=100.0, t_in_c=24.0, t_out_c=40.0)
    assert q < 0  # heat gain from outside


def test_total_envelope_conduction_loss_sums_surfaces():
    surfaces = [
        hmb.Surface("wall_a", u_value=0.4, area_m2=50.0),
        hmb.Surface("wall_b", u_value=0.4, area_m2=50.0),
        hmb.Surface("ceiling", u_value=0.3, area_m2=200.0),
    ]
    total = hmb.total_envelope_conduction_loss(surfaces, t_in_c=24.0, t_out_c=4.0)
    expected = (0.4 * 50.0 + 0.4 * 50.0 + 0.3 * 200.0) * (24.0 - 4.0)
    assert total == pytest.approx(expected)


# ---------------------------------------------------------------------------
# Flock load aggregation
# ---------------------------------------------------------------------------

def test_flock_load_scales_linearly_with_bird_count():
    bw, t_c = 2.5, 24.0
    flock = hmb.flock_load(bird_count=20000, body_weight_kg=bw, t_c=t_c)

    assert flock.total_heat_w == pytest.approx(20000 * bm.total_heat_production(bw))
    assert flock.sensible_heat_w == pytest.approx(20000 * bm.sensible_heat_production(bw, t_c))
    assert flock.latent_heat_w == pytest.approx(20000 * bm.latent_heat_production(bw, t_c))
    assert flock.moisture_kg_per_h == pytest.approx(20000 * bm.moisture_production(bw, t_c))
    assert flock.co2_m3_per_h == pytest.approx(20000 * bm.co2_production(bw))


def test_flock_load_rejects_nonpositive_bird_count():
    with pytest.raises(ValueError):
        hmb.flock_load(bird_count=0, body_weight_kg=1.0, t_c=24.0)


def test_flock_load_sensible_plus_latent_equals_total():
    flock = hmb.flock_load(bird_count=1000, body_weight_kg=1.5, t_c=28.0)
    assert flock.sensible_heat_w + flock.latent_heat_w == pytest.approx(flock.total_heat_w, rel=1e-6)


# ---------------------------------------------------------------------------
# Net house load
# ---------------------------------------------------------------------------

def test_net_house_load_basic_arithmetic():
    flock = hmb.FlockLoad(
        bird_count=1000,
        body_weight_kg=2.0,
        t_c=24.0,
        total_heat_w=20000.0,
        sensible_heat_w=10000.0,
        latent_heat_w=10000.0,
        moisture_kg_per_h=15.0,
        co2_m3_per_h=3.0,
    )
    net = hmb.net_house_load(flock, envelope_loss_w=3000.0, supplemental_heat_w=500.0)
    # net_sensible = 10000 - 3000 + 500 = 7500
    assert net.net_sensible_w == pytest.approx(7500.0)
    assert net.latent_w == pytest.approx(10000.0)
    assert net.moisture_kg_per_h == pytest.approx(15.0)


def test_net_house_load_defaults_to_no_supplemental_heat():
    flock = hmb.FlockLoad(
        bird_count=1, body_weight_kg=1.0, t_c=20.0,
        total_heat_w=10.0, sensible_heat_w=6.0, latent_heat_w=4.0,
        moisture_kg_per_h=0.005, co2_m3_per_h=0.001,
    )
    net = hmb.net_house_load(flock, envelope_loss_w=2.0)
    assert net.net_sensible_w == pytest.approx(4.0)
