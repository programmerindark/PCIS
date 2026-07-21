"""Unit tests for pcis.db (models + session helpers).

Uses an in-memory SQLite database for isolation and speed.
"""

import pytest
from sqlalchemy.orm import Session

from pcis.core import heat_moisture_balance as hmb
from pcis.core import recommendation_engine as re
from pcis.db.session import (
    compute_error_metrics,
    fit_and_save_calibration,
    get_calibration,
    get_house_by_name,
    get_measurements,
    house_surfaces_as_domain_objects,
    init_db,
    latest_flock_record,
    recommendation_history,
    save_flock_record,
    save_house_config,
    save_measurement,
    save_recommendation,
)
from pcis.equipment.cooling_pad import CELDEK_7090_15_150MM
from pcis.equipment.fan_curve import FAN_CATALOG


@pytest.fixture()
def engine():
    return init_db(":memory:")


@pytest.fixture()
def session(engine):
    with Session(engine) as s:
        yield s


SURFACES = [
    hmb.Surface("sidewalls", u_value=0.6, area_m2=350.0),
    hmb.Surface("ceiling", u_value=0.4, area_m2=1500.0),
]


def test_save_and_fetch_house_config(session):
    house = save_house_config(session, "House 1", length_m=150.0, width_m=15.0, height_m=3.0, surfaces=SURFACES)
    session.commit()

    fetched = get_house_by_name(session, "House 1")
    assert fetched is not None
    assert fetched.id == house.id
    assert fetched.floor_area_m2 == pytest.approx(150.0 * 15.0)
    assert fetched.volume_m3 == pytest.approx(150.0 * 15.0 * 3.0)
    assert len(fetched.surfaces) == 2


def test_get_house_by_name_returns_none_when_missing(session):
    assert get_house_by_name(session, "Nonexistent") is None


def test_house_surfaces_round_trip_to_domain_objects(session):
    house = save_house_config(session, "House 2", length_m=100.0, width_m=12.0, height_m=2.5, surfaces=SURFACES)
    session.commit()

    domain_surfaces = house_surfaces_as_domain_objects(house)
    assert len(domain_surfaces) == 2
    names = {s.name for s in domain_surfaces}
    assert names == {"sidewalls", "ceiling"}


def test_save_flock_record_and_get_latest(session):
    house = save_house_config(session, "House 3", length_m=120.0, width_m=15.0, height_m=3.0, surfaces=SURFACES)
    session.commit()

    save_flock_record(session, house, breed="Ross 308", bird_count=20000, body_weight_kg=0.5)
    save_flock_record(session, house, breed="Ross 308", bird_count=19800, body_weight_kg=2.5)
    session.commit()

    latest = latest_flock_record(session, house)
    assert latest is not None
    assert latest.body_weight_kg == pytest.approx(2.5)
    assert latest.bird_count == 19800


def test_latest_flock_record_none_when_no_records(session):
    house = save_house_config(session, "House 4", length_m=100.0, width_m=12.0, height_m=2.5, surfaces=SURFACES)
    session.commit()
    assert latest_flock_record(session, house) is None


def test_save_and_fetch_recommendation_history(session):
    house = save_house_config(session, "House 5", length_m=150.0, width_m=15.0, height_m=3.0, surfaces=SURFACES)
    session.commit()

    result = re.recommend(
        bird_count=20000,
        body_weight_kg=2.5,
        indoor_t_c=29.0,
        indoor_rh_pct=60.0,
        outdoor_t_c=38.0,
        outdoor_rh_pct=30.0,
        envelope_surfaces=SURFACES,
        fan=FAN_CATALOG[1],
        design_static_pressure_pa=30.0,
        delta_t_c=3.0,
        cooling_pad=CELDEK_7090_15_150MM,
    )
    save_recommendation(
        session, house,
        bird_count=20000, body_weight_kg=2.5,
        indoor_t_c=29.0, indoor_rh_pct=60.0,
        outdoor_t_c=38.0, outdoor_rh_pct=30.0,
        recommendation=result,
    )
    session.commit()

    history = recommendation_history(session, house)
    assert len(history) == 1
    log = history[0]
    assert log.fans_on == result.fans_on
    assert log.pads_on == result.pads_on
    assert log.confidence_score == pytest.approx(result.confidence_score)
    assert "\n".join(result.explanation) == log.explanation


def test_recommendation_history_orders_newest_first(session):
    house = save_house_config(session, "House 6", length_m=100.0, width_m=12.0, height_m=2.5, surfaces=SURFACES)
    session.commit()

    for bw in (0.5, 1.5, 2.5):
        result = re.recommend(
            bird_count=20000, body_weight_kg=bw,
            indoor_t_c=24.0, indoor_rh_pct=60.0,
            outdoor_t_c=20.0, outdoor_rh_pct=55.0,
            envelope_surfaces=SURFACES,
            fan=FAN_CATALOG[1], design_static_pressure_pa=30.0, delta_t_c=3.0,
            cooling_pad=CELDEK_7090_15_150MM,
        )
        save_recommendation(
            session, house,
            bird_count=20000, body_weight_kg=bw,
            indoor_t_c=24.0, indoor_rh_pct=60.0,
            outdoor_t_c=20.0, outdoor_rh_pct=55.0,
            recommendation=result,
        )
    session.commit()

    history = recommendation_history(session, house)
    assert len(history) == 3
    assert history[0].body_weight_kg == pytest.approx(2.5)  # most recently inserted


def test_house_config_name_must_be_unique(session):
    save_house_config(session, "Unique House", length_m=100.0, width_m=12.0, height_m=2.5, surfaces=SURFACES)
    session.commit()

    with pytest.raises(Exception):
        save_house_config(session, "Unique House", length_m=100.0, width_m=12.0, height_m=2.5, surfaces=SURFACES)


# ---------------------------------------------------------------------------
# Validation / calibration persistence
# ---------------------------------------------------------------------------

def test_save_and_get_measurements(session):
    house = save_house_config(session, "House 7", length_m=100.0, width_m=12.0, height_m=2.5, surfaces=SURFACES)
    session.commit()

    save_measurement(session, house, "indoor_t_c", predicted_value=29.0, measured_value=28.2)
    save_measurement(session, house, "indoor_t_c", predicted_value=30.0, measured_value=29.5)
    session.commit()

    records = get_measurements(session, house, "indoor_t_c")
    assert len(records) == 2
    assert records[0].predicted_value == pytest.approx(29.0)
    assert records[1].measured_value == pytest.approx(29.5)


def test_get_measurements_empty_for_unrecorded_variable(session):
    house = save_house_config(session, "House 8", length_m=100.0, width_m=12.0, height_m=2.5, surfaces=SURFACES)
    session.commit()
    assert get_measurements(session, house, "static_pressure_pa") == []


def test_compute_error_metrics_from_stored_measurements(session):
    house = save_house_config(session, "House 9", length_m=100.0, width_m=12.0, height_m=2.5, surfaces=SURFACES)
    session.commit()

    pairs = [(10.0, 9.0), (20.0, 22.0), (30.0, 31.0)]
    for predicted, measured in pairs:
        save_measurement(session, house, "airflow_check", predicted_value=predicted, measured_value=measured)
    session.commit()

    metrics = compute_error_metrics(session, house, "airflow_check")
    assert metrics.n == 3
    assert metrics.bias == pytest.approx(-2.0 / 3.0)


def test_compute_error_metrics_raises_when_no_data(session):
    house = save_house_config(session, "House 10", length_m=100.0, width_m=12.0, height_m=2.5, surfaces=SURFACES)
    session.commit()
    with pytest.raises(ValueError):
        compute_error_metrics(session, house, "nonexistent_variable")


def test_fit_and_save_calibration_persists_and_is_retrievable(session):
    house = save_house_config(session, "House 11", length_m=100.0, width_m=12.0, height_m=2.5, surfaces=SURFACES)
    session.commit()

    predicted_values = [1.0, 2.0, 3.0, 4.0]
    for p in predicted_values:
        save_measurement(session, house, "body_weight_kg", predicted_value=p, measured_value=2.0 * p + 1.0)
    session.commit()

    fitted = fit_and_save_calibration(session, house, "body_weight_kg")
    session.commit()

    assert fitted.slope == pytest.approx(2.0)
    assert fitted.intercept == pytest.approx(1.0)
    assert fitted.r_squared == pytest.approx(1.0)

    fetched = get_calibration(session, house, "body_weight_kg")
    assert fetched is not None
    assert fetched.slope == pytest.approx(2.0)


def test_fit_and_save_calibration_replaces_previous_fit(session):
    house = save_house_config(session, "House 12", length_m=100.0, width_m=12.0, height_m=2.5, surfaces=SURFACES)
    session.commit()

    for p in [1.0, 2.0, 3.0]:
        save_measurement(session, house, "static_pressure_pa", predicted_value=p, measured_value=p)
    session.commit()
    fit_and_save_calibration(session, house, "static_pressure_pa")
    session.commit()

    # New, different measurements -> refit should replace, not duplicate
    for p in [10.0, 20.0, 30.0]:
        save_measurement(session, house, "static_pressure_pa", predicted_value=p, measured_value=2 * p)
    session.commit()
    fit_and_save_calibration(session, house, "static_pressure_pa")
    session.commit()

    fetched = get_calibration(session, house, "static_pressure_pa")
    assert fetched is not None
    assert fetched.n == 6  # all 6 measurements used in the second fit (cumulative)


def test_get_calibration_none_when_not_fitted(session):
    house = save_house_config(session, "House 13", length_m=100.0, width_m=12.0, height_m=2.5, surfaces=SURFACES)
    session.commit()
    assert get_calibration(session, house, "indoor_t_c") is None
