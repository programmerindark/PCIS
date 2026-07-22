"""Unit tests for pcis.db (models + session helpers).

Uses an in-memory SQLite database for isolation and speed.
"""

import csv
import os
import tempfile

import pytest
from sqlalchemy.orm import Session

from pcis.core import heat_moisture_balance as hmb
from pcis.core import recommendation_engine as re
from pcis.db.session import (
    RECOMMENDATION_LOG_CSV_COLUMNS,
    compute_error_metrics,
    export_recommendation_logs_csv,
    fit_and_save_calibration,
    get_calibration,
    get_house_by_name,
    get_measurements,
    get_or_create_house_config,
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


# ---------------------------------------------------------------------------
# ML data-logging: age_days + comfort-assessment fields, CSV export
# ---------------------------------------------------------------------------


def test_save_recommendation_persists_age_and_comfort_fields(session):
    house = save_house_config(session, "House 14", length_m=150.0, width_m=15.0, height_m=3.0, surfaces=SURFACES)
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
        age_days=28,
    )
    session.commit()

    log = recommendation_history(session, house)[0]
    assert log.age_days == 28
    assert log.supply_air_t_c == pytest.approx(result.supply_air_t_c)
    assert log.supply_air_rh_pct == pytest.approx(result.supply_air_rh_pct)
    assert log.target_unreachable == result.target_unreachable
    assert log.target_temp_c == pytest.approx(result.comfort.target_temp_c)
    assert log.deviation_c == pytest.approx(result.comfort.deviation_c)
    assert log.thi == pytest.approx(result.comfort.thi)
    assert log.thi_class == result.comfort.thi_class
    assert log.comfort_index == pytest.approx(result.comfort.comfort_index)
    assert log.target_temp_rh_clamped == result.comfort.target_temp_rh_clamped


def test_save_recommendation_age_days_defaults_to_none(session):
    house = save_house_config(session, "House 15", length_m=100.0, width_m=12.0, height_m=2.5, surfaces=SURFACES)
    session.commit()

    result = re.recommend(
        bird_count=20000, body_weight_kg=2.5,
        indoor_t_c=24.0, indoor_rh_pct=60.0,
        outdoor_t_c=20.0, outdoor_rh_pct=55.0,
        envelope_surfaces=SURFACES,
        fan=FAN_CATALOG[1], design_static_pressure_pa=30.0, delta_t_c=3.0,
        cooling_pad=CELDEK_7090_15_150MM,
    )
    save_recommendation(
        session, house,
        bird_count=20000, body_weight_kg=2.5,
        indoor_t_c=24.0, indoor_rh_pct=60.0,
        outdoor_t_c=20.0, outdoor_rh_pct=55.0,
        recommendation=result,
    )
    session.commit()

    log = recommendation_history(session, house)[0]
    assert log.age_days is None


def test_export_recommendation_logs_csv_writes_correct_header_and_rows(session):
    house = save_house_config(session, "House 16", length_m=150.0, width_m=15.0, height_m=3.0, surfaces=SURFACES)
    session.commit()

    scenarios = [
        dict(age_days=7, body_weight_kg=0.18, indoor_t_c=33.0, indoor_rh_pct=60.0,
             outdoor_t_c=30.0, outdoor_rh_pct=50.0),
        dict(age_days=35, body_weight_kg=2.5, indoor_t_c=24.0, indoor_rh_pct=65.0,
             outdoor_t_c=20.0, outdoor_rh_pct=55.0),
    ]
    for sc in scenarios:
        result = re.recommend(
            bird_count=20000,
            body_weight_kg=sc["body_weight_kg"],
            indoor_t_c=sc["indoor_t_c"],
            indoor_rh_pct=sc["indoor_rh_pct"],
            outdoor_t_c=sc["outdoor_t_c"],
            outdoor_rh_pct=sc["outdoor_rh_pct"],
            envelope_surfaces=SURFACES,
            fan=FAN_CATALOG[1], design_static_pressure_pa=30.0, delta_t_c=3.0,
            cooling_pad=CELDEK_7090_15_150MM,
        )
        save_recommendation(
            session, house,
            bird_count=20000, body_weight_kg=sc["body_weight_kg"],
            indoor_t_c=sc["indoor_t_c"], indoor_rh_pct=sc["indoor_rh_pct"],
            outdoor_t_c=sc["outdoor_t_c"], outdoor_rh_pct=sc["outdoor_rh_pct"],
            recommendation=result,
            age_days=sc["age_days"],
        )
    session.commit()

    with tempfile.TemporaryDirectory() as tmp:
        out_path = os.path.join(tmp, "training_data.csv")
        returned_path = export_recommendation_logs_csv(session, output_path=out_path)
        assert returned_path == out_path
        assert os.path.exists(out_path)

        with open(out_path, newline="", encoding="utf-8") as f:
            reader = csv.reader(f)
            rows = list(reader)

    assert rows[0] == RECOMMENDATION_LOG_CSV_COLUMNS
    assert len(rows) == 3  # header + 2 data rows

    age_idx = RECOMMENDATION_LOG_CSV_COLUMNS.index("age_days")
    house_idx = RECOMMENDATION_LOG_CSV_COLUMNS.index("house_name")
    bw_idx = RECOMMENDATION_LOG_CSV_COLUMNS.index("body_weight_kg")
    ages = {row[age_idx] for row in rows[1:]}
    assert ages == {"7", "35"}
    assert all(row[house_idx] == "House 16" for row in rows[1:])
    body_weights = {row[bw_idx] for row in rows[1:]}
    assert body_weights == {"0.18", "2.5"}


def test_export_recommendation_logs_csv_empty_when_no_logs(session):
    house = save_house_config(session, "House 17", length_m=100.0, width_m=12.0, height_m=2.5, surfaces=SURFACES)
    session.commit()

    with tempfile.TemporaryDirectory() as tmp:
        out_path = os.path.join(tmp, "empty.csv")
        export_recommendation_logs_csv(session, output_path=out_path, house=house)
        with open(out_path, newline="", encoding="utf-8") as f:
            rows = list(csv.reader(f))
    assert rows == [RECOMMENDATION_LOG_CSV_COLUMNS]


# ---------------------------------------------------------------------------
# get_or_create_house_config -- backs the GUI's automatic per-run logging
# ---------------------------------------------------------------------------


def test_get_or_create_house_config_creates_when_missing(session):
    house = get_or_create_house_config(
        session, "House 18", length_m=150.0, width_m=15.0, height_m=3.0, surfaces=SURFACES
    )
    session.commit()

    fetched = get_house_by_name(session, "House 18")
    assert fetched is not None
    assert fetched.id == house.id
    assert len(fetched.surfaces) == 2


def test_get_or_create_house_config_reuses_existing_house_without_raising(session):
    first = get_or_create_house_config(
        session, "House 19", length_m=150.0, width_m=15.0, height_m=3.0, surfaces=SURFACES
    )
    session.commit()

    # Calling again with the same name must NOT raise a uniqueness error --
    # this is exactly the scenario a plain save_house_config would fail on
    # (see test_house_config_name_must_be_unique above).
    second = get_or_create_house_config(
        session, "House 19", length_m=150.0, width_m=15.0, height_m=3.0, surfaces=SURFACES
    )
    session.commit()

    assert second.id == first.id
    assert get_house_by_name(session, "House 19") is not None


def test_get_or_create_house_config_updates_dimensions_and_surfaces_on_reuse(session):
    get_or_create_house_config(
        session, "House 20", length_m=100.0, width_m=10.0, height_m=2.5, surfaces=SURFACES
    )
    session.commit()

    new_surfaces = [hmb.Surface("sidewalls", u_value=0.5, area_m2=400.0)]
    updated = get_or_create_house_config(
        session, "House 20", length_m=200.0, width_m=20.0, height_m=4.0, surfaces=new_surfaces
    )
    session.commit()

    assert updated.length_m == pytest.approx(200.0)
    assert updated.width_m == pytest.approx(20.0)
    assert updated.height_m == pytest.approx(4.0)
    assert len(updated.surfaces) == 1
    assert updated.surfaces[0].area_m2 == pytest.approx(400.0)


# ---------------------------------------------------------------------------
# Data curation: view, tag, delete (History tab back-end)
# ---------------------------------------------------------------------------


def _one_recommendation(session, house, **kw):
    result = re.recommend(
        bird_count=20000, body_weight_kg=2.3,
        indoor_t_c=29.0, indoor_rh_pct=60.0,
        outdoor_t_c=35.0, outdoor_rh_pct=40.0,
        envelope_surfaces=SURFACES, fan=FAN_CATALOG[1],
        design_static_pressure_pa=30.0, delta_t_c=3.0,
    )
    return save_recommendation(
        session, house, bird_count=20000, body_weight_kg=2.3,
        indoor_t_c=29.0, indoor_rh_pct=60.0, outdoor_t_c=35.0, outdoor_rh_pct=40.0,
        recommendation=result, age_days=35, **kw,
    )


def test_all_recommendation_logs_can_exclude_tests(session):
    from pcis.db.session import all_recommendation_logs
    house = save_house_config(session, "Cur1", length_m=100, width_m=12, height_m=2.5, surfaces=SURFACES)
    session.commit()
    _one_recommendation(session, house)
    _one_recommendation(session, house, is_test=True)
    session.commit()
    assert len(all_recommendation_logs(session)) == 2
    assert len(all_recommendation_logs(session, include_test=False)) == 1


def test_count_recommendation_logs_splits_real_and_test(session):
    from pcis.db.session import count_recommendation_logs
    house = save_house_config(session, "Cur2", length_m=100, width_m=12, height_m=2.5, surfaces=SURFACES)
    session.commit()
    _one_recommendation(session, house)
    _one_recommendation(session, house)
    _one_recommendation(session, house, is_test=True)
    session.commit()
    assert count_recommendation_logs(session) == (2, 1)


def test_delete_recommendation_logs_is_permanent(session):
    from pcis.db.session import all_recommendation_logs, delete_recommendation_logs
    house = save_house_config(session, "Cur3", length_m=100, width_m=12, height_m=2.5, surfaces=SURFACES)
    session.commit()
    a = _one_recommendation(session, house)
    _one_recommendation(session, house)
    session.commit()
    removed = delete_recommendation_logs(session, [a.id])
    session.commit()
    assert removed == 1
    remaining = all_recommendation_logs(session)
    assert len(remaining) == 1 and remaining[0].id != a.id


def test_set_test_flag_is_reversible(session):
    from pcis.db.session import count_recommendation_logs, set_recommendation_test_flag
    house = save_house_config(session, "Cur4", length_m=100, width_m=12, height_m=2.5, surfaces=SURFACES)
    session.commit()
    a = _one_recommendation(session, house)
    session.commit()
    set_recommendation_test_flag(session, [a.id], True); session.commit()
    assert count_recommendation_logs(session) == (0, 1)
    set_recommendation_test_flag(session, [a.id], False); session.commit()
    assert count_recommendation_logs(session) == (1, 0)


def test_export_can_exclude_test_rows(session, tmp_path):
    import csv as _csv
    from pcis.db.session import export_recommendation_logs_csv
    house = save_house_config(session, "Cur5", length_m=100, width_m=12, height_m=2.5, surfaces=SURFACES)
    session.commit()
    _one_recommendation(session, house)
    _one_recommendation(session, house, is_test=True)
    session.commit()
    out = tmp_path / "real.csv"
    export_recommendation_logs_csv(session, str(out), exclude_test=True)
    rows = list(_csv.reader(open(out, newline="", encoding="utf-8")))
    assert len(rows) == 2  # header + 1 real row
    assert "is_test" in rows[0] and "note" in rows[0]


# ---------------------------------------------------------------------------
# Schema migration: opening a database written by an older version
#
# create_all() makes missing tables but never alters an existing one, so a
# db from before a column was added crashes the first query that references
# it ("no such column: recommendation_logs.age_days"). init_db must top up
# missing columns in place.
# ---------------------------------------------------------------------------


def test_old_schema_database_is_migrated_in_place(tmp_path):
    import sqlite3

    from pcis.db.session import all_recommendation_logs, count_recommendation_logs, init_db

    db = tmp_path / "old.db"
    con = sqlite3.connect(db)
    con.executescript(
        """
        CREATE TABLE house_configs (id INTEGER PRIMARY KEY, name TEXT UNIQUE,
            length_m REAL, width_m REAL, height_m REAL, created_at TEXT);
        CREATE TABLE recommendation_logs (
            id INTEGER PRIMARY KEY, house_id INTEGER, timestamp TEXT,
            bird_count INTEGER, body_weight_kg REAL, indoor_t_c REAL, indoor_rh_pct REAL,
            outdoor_t_c REAL, outdoor_rh_pct REAL, fans_on INTEGER, pads_on INTEGER,
            required_airflow_m3_per_h REAL, governing_constraint TEXT,
            confidence_score REAL, explanation TEXT);
        INSERT INTO house_configs VALUES (1,'Legacy',150,15,3,'2026-01-01');
        INSERT INTO recommendation_logs
            (id,house_id,timestamp,bird_count,body_weight_kg,indoor_t_c,indoor_rh_pct,
             outdoor_t_c,outdoor_rh_pct,fans_on,pads_on,required_airflow_m3_per_h,
             governing_constraint,confidence_score,explanation)
            VALUES (1,1,'2026-01-01 08:00',20000,2.3,29,60,35,40,10,0,317000,
                    'moisture',85,'legacy row');
        """
    )
    con.commit()
    con.close()

    engine = init_db(str(db))  # must not raise; must add the missing columns

    with Session(engine) as s:
        logs = all_recommendation_logs(s)           # the query that crashed
        assert len(logs) == 1
        assert logs[0].governing_constraint == "moisture"   # legacy data intact
        assert logs[0].age_days is None                     # new column, default
        assert logs[0].is_test is False
        assert count_recommendation_logs(s) == (1, 0)

    con = sqlite3.connect(db)
    cols = {r[1] for r in con.execute("PRAGMA table_info(recommendation_logs)")}
    con.close()
    assert {"age_days", "is_test", "note", "supply_air_t_c", "target_unreachable"} <= cols


def test_migration_is_a_noop_on_a_current_database(tmp_path):
    from pcis.db.session import _migrate_add_missing_columns, init_db

    engine = init_db(str(tmp_path / "fresh.db"))
    # A freshly created db already has every column, so a second migration
    # pass must add nothing.
    assert _migrate_add_missing_columns(engine) == []
