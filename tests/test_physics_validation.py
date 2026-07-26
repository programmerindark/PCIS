"""End-to-end physics validation: are the engine's OUTPUTS plausible?

The other test files check each formula in isolation. This one sweeps
realistic operating conditions and asserts that the numbers a farmer
actually sees behave sensibly and consistently with each other -- the
class of bug that unit tests miss (e.g. a felt temperature that never
changes, or a THI frozen at one value).

Every assertion here is a physical/operational invariant, not a
regression snapshot.
"""

import pytest

from pcis.core import bird_status as bs
from pcis.core import comfort_engine as ce
from pcis.core import growth_curve as gc
from pcis.core import heat_moisture_balance as hmb
from pcis.core import house_metrics as hmet
from pcis.core import psychrometrics as psy
from pcis.core import recommendation_engine as re
from pcis.equipment.cooling_pad import COOLING_PAD_CATALOG
from pcis.equipment.fan_curve import FAN_CATALOG

L, W, H = 120.0, 15.0, 3.0
SURF = [hmb.Surface("walls", 0.41, 2 * (L + W) * H), hmb.Surface("ceiling", 0.26, L * W)]


def rec(age=37, out_t=27.0, rh=60.0, xs=23.23, birds=21940, pads=None, heater=None, fans=0):
    wt = gc.ross_308_body_weight_kg(age)
    tgt = ce.target_temperature(wt, rh)
    return re.recommend(
        bird_count=birds, body_weight_kg=wt, indoor_t_c=tgt, indoor_rh_pct=rh,
        outdoor_t_c=out_t, outdoor_rh_pct=rh, envelope_surfaces=SURF,
        fan=FAN_CATALOG[0], design_static_pressure_pa=30.0, delta_t_c=3.0,
        cooling_pad=pads, house_cross_section_m2=xs, heater_capacity_w=heater,
    )


# ----------------------------------------------------------------------
# Achievable temperature — the bug class that shipped
# ----------------------------------------------------------------------

def test_achievable_temp_never_below_supply_air():
    """Ventilation cannot cool below the air it is fed."""
    for t in [5, 15, 22, 27, 33, 40]:
        r = rec(out_t=t)
        assert r.achievable_indoor_t_c >= r.supply_air_t_c - 1e-6
        assert r.achievable_indoor_t_c >= r.comfort.target_temp_c - 1e-6


def test_felt_temperature_tracks_outdoor_conditions():
    """REGRESSION: felt temp was frozen at the target and never moved."""
    feels = [rec(out_t=t).effective_temp_c for t in [15, 22, 27, 32, 38]]
    assert all(f is not None for f in feels)
    assert len(set(round(f, 1) for f in feels)) > 3, "felt temp barely varies"
    assert feels == sorted(feels), "felt temp must rise with outdoor temp"


def test_thi_rises_with_temperature():
    """REGRESSION: THI was pinned to the target temperature."""
    this = [rec(out_t=t).comfort.thi for t in [15, 22, 27, 32, 38]]
    assert this == sorted(this)
    assert this[-1] - this[0] > 8, "THI should span a wide range"


def test_felt_temperature_never_above_dry_bulb():
    for t in [18, 25, 30, 36]:
        r = rec(out_t=t)
        assert r.effective_temp_c <= r.achievable_indoor_t_c + 1e-6


def test_windchill_fades_in_extreme_heat():
    """Aviagen: the effect disappears above ~38 C."""
    warm = rec(out_t=30)
    extreme = rec(out_t=39)
    drop_warm = warm.achievable_indoor_t_c - warm.effective_temp_c
    drop_extreme = extreme.achievable_indoor_t_c - extreme.effective_temp_c
    assert drop_warm > drop_extreme
    assert drop_extreme < 1.0


# ----------------------------------------------------------------------
# Fan sizing / airflow physics
# ----------------------------------------------------------------------

def test_more_birds_need_more_airflow():
    small = rec(birds=5000)
    large = rec(birds=25000)
    assert large.required_airflow_m3_per_h > small.required_airflow_m3_per_h
    assert large.fans_on >= small.fans_on


def test_hotter_weather_needs_at_least_as_many_fans():
    counts = [rec(out_t=t).fans_on for t in [12, 20, 26, 32]]
    assert counts == sorted(counts)


def test_delivered_airflow_covers_requirement():
    for t in [18, 27, 35]:
        r = rec(out_t=t)
        assert r.delivered_airflow_m3_per_h >= r.required_airflow_m3_per_h


def test_airspeed_matches_continuity_equation():
    """V = Q / A, with Q in m3/h -> m3/s."""
    xs = 23.23
    r = rec(xs=xs)
    expected = (r.delivered_airflow_m3_per_h / 3600.0) / xs
    assert r.air_speed_mps == pytest.approx(expected, rel=1e-6)


def test_narrower_cross_section_gives_faster_air():
    wide = rec(xs=45.0, out_t=20)
    narrow = rec(xs=23.0, out_t=20)
    assert narrow.air_speed_mps > wide.air_speed_mps


def test_fan_count_is_a_positive_integer():
    for t in [5, 20, 40]:
        r = rec(out_t=t)
        assert isinstance(r.fans_on, int) and r.fans_on >= 1


# ----------------------------------------------------------------------
# Heating / cooling regimes
# ----------------------------------------------------------------------

def test_cold_weather_triggers_heating_not_pads():
    r = rec(age=7, out_t=-2.0, rh=60.0, heater=80_000)
    assert r.heating_needed is True
    assert r.pads_on is False


def test_hot_weather_never_calls_for_heating():
    r = rec(out_t=36.0, heater=80_000)
    assert r.heating_needed is False


def test_pads_only_engage_when_hot_and_installed():
    hot_with = rec(out_t=36.0, rh=40.0, pads=COOLING_PAD_CATALOG[0])
    hot_without = rec(out_t=36.0, rh=40.0, pads=None)
    cool_with = rec(out_t=15.0, rh=40.0, pads=COOLING_PAD_CATALOG[0])
    assert hot_with.pads_on is True
    assert hot_without.pads_on is False
    assert cool_with.pads_on is False


def test_pads_lower_supply_air_temperature():
    with_pads = rec(out_t=36.0, rh=40.0, pads=COOLING_PAD_CATALOG[0])
    without = rec(out_t=36.0, rh=40.0, pads=None)
    assert with_pads.supply_air_t_c < without.supply_air_t_c


# ----------------------------------------------------------------------
# Humidity / VPD
# ----------------------------------------------------------------------

def test_vpd_falls_as_humidity_rises():
    vpds = [rec(out_t=27, rh=r).vpd_kpa for r in [30, 50, 70, 90]]
    assert vpds == sorted(vpds, reverse=True)
    assert vpds[-1] < 0.5, "near-saturated air should have very low VPD"


def test_vpd_matches_definition():
    r = rec(out_t=27, rh=60)
    expected = psy.saturation_vapor_pressure(r.achievable_indoor_t_c) * 0.4 / 1000.0
    assert r.vpd_kpa == pytest.approx(expected, rel=1e-6)


# ----------------------------------------------------------------------
# Bird status consistency
# ----------------------------------------------------------------------

def test_heat_stress_risk_escalates_with_heat():
    risks = [bs.from_recommendation(rec(out_t=t)).heat_stress_risk for t in [16, 27, 36]]
    order = {"Low": 0, "Moderate": 1, "High": 2}
    assert [order[r] for r in risks] == sorted(order[r] for r in risks)


def test_water_intake_rises_with_temperature():
    w = [bs.from_recommendation(rec(out_t=t)).water_intake_multiplier for t in [18, 27, 36]]
    assert w == sorted(w)
    assert w[0] == pytest.approx(1.0, abs=0.35)


def test_bird_status_uses_engine_values_directly():
    r = rec(out_t=30)
    st = bs.from_recommendation(r)
    assert st.effective_bird_temp_c == pytest.approx(r.effective_temp_c)
    assert st.comfort_score == pytest.approx(r.comfort.comfort_index)


def test_felt_comfort_beats_dry_bulb_when_air_is_moving():
    """With strong airflow in moderate heat the birds are better off than
    the dry-bulb deviation alone suggests."""
    r = rec(out_t=27, rh=60, xs=23.23)
    assert r.felt_comfort_index is not None
    assert r.felt_comfort_index >= r.comfort.comfort_index


# ----------------------------------------------------------------------
# House metrics
# ----------------------------------------------------------------------

def test_density_grows_with_bird_age():
    def dens(age):
        wt = gc.ross_308_body_weight_kg(age)
        return hmet.assess(bird_count=20000, body_weight_kg=wt, floor_area_m2=L * W,
                           house_volume_m3=L * W * H, delivered_airflow_m3_per_h=3e5,
                           co2_production_m3_per_h=50.0).stocking_density_kg_m2
    d = [dens(a) for a in [7, 21, 35, 49]]
    assert d == sorted(d)


def test_co2_falls_as_ventilation_rises():
    def co2(airflow):
        return hmet.assess(bird_count=20000, body_weight_kg=2.5, floor_area_m2=L * W,
                           house_volume_m3=L * W * H, delivered_airflow_m3_per_h=airflow,
                           co2_production_m3_per_h=60.0).estimated_co2_ppm
    assert co2(50_000) > co2(200_000) > co2(500_000)


def test_co2_never_below_outdoor_background():
    m = hmet.assess(bird_count=20000, body_weight_kg=2.5, floor_area_m2=L * W,
                    house_volume_m3=L * W * H, delivered_airflow_m3_per_h=1e7,
                    co2_production_m3_per_h=60.0, outdoor_co2_ppm=420.0)
    assert m.estimated_co2_ppm >= 420.0


# ----------------------------------------------------------------------
# Global sanity sweep — nothing absurd anywhere
# ----------------------------------------------------------------------

@pytest.mark.parametrize("age", [1, 14, 28, 42, 56])
@pytest.mark.parametrize("out_t", [0, 12, 24, 36])
def test_outputs_stay_physically_plausible(age, out_t):
    r = rec(age=age, out_t=out_t, rh=60.0, heater=100_000)
    assert 1 <= r.fans_on <= 200
    assert r.required_airflow_m3_per_h > 0
    assert -30 <= r.achievable_indoor_t_c <= 60
    assert -30 <= r.effective_temp_c <= 60
    assert 0 <= r.comfort.comfort_index <= 100
    assert 0 <= r.confidence_score <= 100
    assert 0 <= r.vpd_kpa <= 12
    assert r.air_speed_mps is not None and 0 <= r.air_speed_mps <= 20
    assert r.heat_deficit_w >= 0
