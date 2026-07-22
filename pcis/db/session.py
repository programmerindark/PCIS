"""Engine/session setup and save/query helpers for PCIS persistence.

Uses SQLite by default (per the project's stated tech stack: "SQLite
(later PostgreSQL)"). Because this is plain SQLAlchemy 2.0 with
standard column types (no SQLite-specific types used in models.py),
switching `init_db` to a PostgreSQL URL later should not require
schema changes.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import Engine, create_engine, select
from sqlalchemy.orm import Session

from pcis.core import heat_moisture_balance as hmb
from pcis.core import validation as val
from pcis.core.recommendation_engine import Recommendation
from pcis.db.models import (
    Base,
    CalibrationFactorRecord,
    EnvelopeSurface,
    FlockRecord,
    HouseConfig,
    MeasurementRecord,
    RecommendationLog,
)


def init_db(db_path: str = "pcis.db", echo: bool = False) -> Engine:
    """Create (if needed) and return a SQLite-backed engine with all
    tables present.

    Parameters
    ----------
    db_path : str, optional
        Filesystem path for the SQLite database, or ":memory:" for an
        in-memory database (useful for tests). Defaults to "pcis.db"
        in the current working directory.
    echo : bool, optional
        Passed through to SQLAlchemy's `create_engine(echo=...)` for
        SQL statement logging during debugging.

    Returns
    -------
    Engine
        A SQLAlchemy engine with `Base.metadata` already created.
    """
    url = f"sqlite:///{db_path}" if db_path != ":memory:" else "sqlite:///:memory:"
    engine = create_engine(url, echo=echo)
    Base.metadata.create_all(engine)
    return engine


def save_house_config(
    session: Session,
    name: str,
    length_m: float,
    width_m: float,
    height_m: float,
    surfaces: list[hmb.Surface],
) -> HouseConfig:
    """Persist a house configuration and its envelope surfaces.

    Parameters
    ----------
    session : Session
    name : str
        Unique house name/identifier.
    length_m, width_m, height_m : float
        Floor dimensions.
    surfaces : list[heat_moisture_balance.Surface]
        Envelope surfaces (see `pcis.core.heat_moisture_balance.Surface`).

    Returns
    -------
    HouseConfig
        The persisted ORM object (already added/flushed to the
        session; caller is responsible for `session.commit()`).
    """
    house = HouseConfig(name=name, length_m=length_m, width_m=width_m, height_m=height_m)
    for s in surfaces:
        house.surfaces.append(EnvelopeSurface(name=s.name, u_value=s.u_value, area_m2=s.area_m2))
    session.add(house)
    session.flush()
    return house


def get_house_by_name(session: Session, name: str) -> HouseConfig | None:
    """Fetch a house configuration by its unique name, or None."""
    return session.execute(select(HouseConfig).where(HouseConfig.name == name)).scalar_one_or_none()


def get_or_create_house_config(
    session: Session,
    name: str,
    length_m: float,
    width_m: float,
    height_m: float,
    surfaces: list[hmb.Surface],
) -> HouseConfig:
    """Fetch a house by name if it already exists, refreshing its
    dimensions/envelope surfaces to the given values; otherwise create
    it via `save_house_config`.

    `HouseConfig.name` is unique, so a plain `save_house_config` call
    raises on a second call with the same name. This helper exists for
    call sites that record automatically on every action (e.g. the
    GUI logging one row per recommendation run under the same house
    name) and must not fail just because the house was already seen.
    """
    house = get_house_by_name(session, name)
    if house is None:
        return save_house_config(session, name, length_m, width_m, height_m, surfaces)
    house.length_m = length_m
    house.width_m = width_m
    house.height_m = height_m
    house.surfaces.clear()
    for s in surfaces:
        house.surfaces.append(EnvelopeSurface(name=s.name, u_value=s.u_value, area_m2=s.area_m2))
    session.flush()
    return house


def house_surfaces_as_domain_objects(house: HouseConfig) -> list[hmb.Surface]:
    """Convert a persisted HouseConfig's surfaces back into the plain
    `heat_moisture_balance.Surface` objects the engineering core uses.
    """
    return [hmb.Surface(name=s.name, u_value=s.u_value, area_m2=s.area_m2) for s in house.surfaces]


def save_flock_record(
    session: Session,
    house: HouseConfig,
    breed: str,
    bird_count: int,
    body_weight_kg: float,
    recorded_at: dt.datetime | None = None,
) -> FlockRecord:
    """Persist a flock bird-count/weight reading for a house.

    See `models.FlockRecord` docstring re: `breed` being informational
    only -- the engineering core is not currently breed-specific.
    """
    record = FlockRecord(
        house_id=house.id,
        breed=breed,
        bird_count=bird_count,
        body_weight_kg=body_weight_kg,
        recorded_at=recorded_at or dt.datetime.utcnow(),
    )
    session.add(record)
    session.flush()
    return record


def latest_flock_record(session: Session, house: HouseConfig) -> FlockRecord | None:
    """Most recently recorded flock reading for a house, or None."""
    stmt = (
        select(FlockRecord)
        .where(FlockRecord.house_id == house.id)
        .order_by(FlockRecord.recorded_at.desc())
        .limit(1)
    )
    return session.execute(stmt).scalar_one_or_none()


def save_recommendation(
    session: Session,
    house: HouseConfig,
    bird_count: int,
    body_weight_kg: float,
    indoor_t_c: float,
    indoor_rh_pct: float,
    outdoor_t_c: float,
    outdoor_rh_pct: float,
    recommendation: Recommendation,
    age_days: int | None = None,
    is_test: bool = False,
    note: str | None = None,
) -> RecommendationLog:
    """Persist a full snapshot of a `recommendation_engine.recommend()`
    call -- inputs, outputs, and the comfort-assessment breakdown --
    for later review, Stage 3 validation (comparing recommended
    settings to what was actually run and observed), or export as a
    training dataset (`export_recommendation_logs_csv`).

    Parameters
    ----------
    age_days : int, optional
        Bird age at this snapshot, if known (e.g. from the GUI's
        growth-curve-linked age field). Stored so a growing history of
        these rows carries the one input (age/day) that the
        `Recommendation` object itself doesn't retain, alongside the
        timestamp SQLAlchemy already sets automatically.
    """
    log = RecommendationLog(
        house_id=house.id,
        age_days=age_days,
        bird_count=bird_count,
        body_weight_kg=body_weight_kg,
        indoor_t_c=indoor_t_c,
        indoor_rh_pct=indoor_rh_pct,
        outdoor_t_c=outdoor_t_c,
        outdoor_rh_pct=outdoor_rh_pct,
        fans_on=recommendation.fans_on,
        pads_on=recommendation.pads_on,
        required_airflow_m3_per_h=recommendation.required_airflow_m3_per_h,
        governing_constraint=recommendation.governing_constraint,
        confidence_score=recommendation.confidence_score,
        explanation="\n".join(recommendation.explanation),
        target_temp_c=recommendation.comfort.target_temp_c,
        deviation_c=recommendation.comfort.deviation_c,
        thi=recommendation.comfort.thi,
        thi_class=recommendation.comfort.thi_class,
        comfort_index=recommendation.comfort.comfort_index,
        target_temp_rh_clamped=recommendation.comfort.target_temp_rh_clamped,
        supply_air_t_c=recommendation.supply_air_t_c,
        supply_air_rh_pct=recommendation.supply_air_rh_pct,
        target_unreachable=recommendation.target_unreachable,
        is_test=is_test,
        note=note,
    )
    session.add(log)
    session.flush()
    return log


def recommendation_history(session: Session, house: HouseConfig, limit: int = 50) -> list[RecommendationLog]:
    """Most recent recommendation logs for a house, newest first."""
    stmt = (
        select(RecommendationLog)
        .where(RecommendationLog.house_id == house.id)
        .order_by(RecommendationLog.timestamp.desc())
        .limit(limit)
    )
    return list(session.execute(stmt).scalars().all())


# ---------------------------------------------------------------------------
# Data curation: view, tag and delete logged runs
#
# Every "Run Recommendation" click logs a row, exploratory ones included.
# Without a way to review and prune, the exported dataset fills with test
# clicks and mistyped inputs -- noise that a model would train on as if it
# were real. These helpers back the History tab.
# ---------------------------------------------------------------------------


def all_recommendation_logs(
    session: Session,
    include_test: bool = True,
    limit: int | None = None,
) -> list[RecommendationLog]:
    """Every logged run across all houses, newest first.

    `include_test=False` returns only rows NOT marked as tests -- i.e.
    the data actually fit for training.
    """
    stmt = select(RecommendationLog).order_by(RecommendationLog.timestamp.desc())
    if not include_test:
        stmt = stmt.where(RecommendationLog.is_test.is_(False))
    if limit is not None:
        stmt = stmt.limit(limit)
    return list(session.execute(stmt).scalars().all())


def count_recommendation_logs(session: Session) -> tuple[int, int]:
    """(real_count, test_count) across all houses."""
    from sqlalchemy import func

    total = session.execute(
        select(func.count()).select_from(RecommendationLog)
    ).scalar_one()
    tests = session.execute(
        select(func.count()).select_from(RecommendationLog)
        .where(RecommendationLog.is_test.is_(True))
    ).scalar_one()
    return total - tests, tests


def delete_recommendation_logs(session: Session, ids: list[int]) -> int:
    """Permanently delete the given rows. Returns how many were removed.

    Deletion is real and irreversible -- this is the point of the
    feature (removing garbage), so there is no soft-delete. The GUI
    confirms before calling this.
    """
    if not ids:
        return 0
    rows = list(session.execute(
        select(RecommendationLog).where(RecommendationLog.id.in_(ids))
    ).scalars().all())
    for row in rows:
        session.delete(row)
    session.flush()
    return len(rows)


def set_recommendation_test_flag(session: Session, ids: list[int], is_test: bool) -> int:
    """Mark rows as test (excluded from the real dataset) or real.

    Reversible on purpose: a row wrongly marked as a test can be
    restored, unlike a deletion. Returns how many rows were updated.
    """
    if not ids:
        return 0
    rows = list(session.execute(
        select(RecommendationLog).where(RecommendationLog.id.in_(ids))
    ).scalars().all())
    for row in rows:
        row.is_test = is_test
    session.flush()
    return len(rows)


def set_recommendation_note(session: Session, log_id: int, note: str | None) -> bool:
    """Attach or clear a free-text note on one row. Returns True if found."""
    row = session.get(RecommendationLog, log_id)
    if row is None:
        return False
    row.note = (note or "").strip() or None
    session.flush()
    return True


#: Column order for `export_recommendation_logs_csv` -- one row per
#: saved `RecommendationLog`, oldest first. Kept as an explicit list
#: (rather than introspecting the ORM model) so the CSV schema is
#: stable and documented in one place, independent of column-ordering
#: changes to the model.
RECOMMENDATION_LOG_CSV_COLUMNS = [
    "id", "house_name", "timestamp", "age_days",
    "bird_count", "body_weight_kg",
    "indoor_t_c", "indoor_rh_pct", "outdoor_t_c", "outdoor_rh_pct",
    "fans_on", "pads_on", "required_airflow_m3_per_h", "governing_constraint",
    "confidence_score",
    "target_temp_c", "deviation_c", "thi", "thi_class", "comfort_index",
    "target_temp_rh_clamped",
    "supply_air_t_c", "supply_air_rh_pct", "target_unreachable",
    "is_test", "note",
]


def export_recommendation_logs_csv(
    session: Session,
    output_path: str,
    house: HouseConfig | None = None,
    exclude_test: bool = False,
) -> str:
    """Export saved `RecommendationLog` rows to a CSV file, one row per
    saved recommendation, oldest first -- a growing dataset intended
    for future calibration/ML work (e.g. comparing predicted fan/pad
    decisions and comfort scores against real outcomes once historical
    data exists), not just a one-off report.

    Every column is something PCIS already computed and cited
    (`recommendation_engine.py`/`comfort_engine.py`) at the moment the
    row was saved -- this function only serializes it, it does not
    compute anything new.

    Parameters
    ----------
    output_path : str
        Destination CSV file path.
    house : HouseConfig, optional
        If given, export only that house's logs. If None, export every
        saved recommendation across all houses (a `house_name` column
        is included either way so the source house is always
        identifiable).
    exclude_test : bool, optional
        If True, rows marked as tests (`is_test`) are omitted -- i.e.
        export only the data fit for training. Defaults to False so the
        raw dump still includes everything with the flag visible.

    Returns
    -------
    str
        `output_path`, for chaining/confirmation.
    """
    import csv

    stmt = select(RecommendationLog).order_by(RecommendationLog.timestamp.asc())
    if house is not None:
        stmt = stmt.where(RecommendationLog.house_id == house.id)
    if exclude_test:
        stmt = stmt.where(RecommendationLog.is_test.is_(False))
    logs = list(session.execute(stmt).scalars().all())

    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(RECOMMENDATION_LOG_CSV_COLUMNS)
        for log in logs:
            writer.writerow([
                log.id,
                log.house.name,
                log.timestamp.isoformat(),
                log.age_days,
                log.bird_count,
                log.body_weight_kg,
                log.indoor_t_c,
                log.indoor_rh_pct,
                log.outdoor_t_c,
                log.outdoor_rh_pct,
                log.fans_on,
                log.pads_on,
                log.required_airflow_m3_per_h,
                log.governing_constraint,
                log.confidence_score,
                log.target_temp_c,
                log.deviation_c,
                log.thi,
                log.thi_class,
                log.comfort_index,
                log.target_temp_rh_clamped,
                log.supply_air_t_c,
                log.supply_air_rh_pct,
                log.target_unreachable,
                log.is_test,
                log.note,
            ])
    return output_path


# ---------------------------------------------------------------------------
# Validation / calibration persistence
# ---------------------------------------------------------------------------

def save_measurement(
    session: Session,
    house: HouseConfig,
    variable: str,
    predicted_value: float,
    measured_value: float,
    recorded_at: dt.datetime | None = None,
) -> MeasurementRecord:
    """Persist one predicted-vs-measured observation for a house.

    `variable` is a free-text label (e.g. "indoor_t_c",
    "static_pressure_pa", "airflow_m3_per_h", "body_weight_kg") --
    kept consistent by convention, not enforced by an enum, so new
    measured quantities can be added without a schema migration.
    """
    record = MeasurementRecord(
        house_id=house.id,
        variable=variable,
        predicted_value=predicted_value,
        measured_value=measured_value,
        recorded_at=recorded_at or dt.datetime.utcnow(),
    )
    session.add(record)
    session.flush()
    return record


def get_measurements(session: Session, house: HouseConfig, variable: str) -> list[MeasurementRecord]:
    """All measurement records for a house and variable, oldest first."""
    stmt = (
        select(MeasurementRecord)
        .where(MeasurementRecord.house_id == house.id, MeasurementRecord.variable == variable)
        .order_by(MeasurementRecord.recorded_at.asc())
    )
    return list(session.execute(stmt).scalars().all())


def compute_error_metrics(session: Session, house: HouseConfig, variable: str) -> val.ErrorMetrics:
    """Compute `pcis.core.validation.ErrorMetrics` from all stored
    measurement records for a house/variable.
    """
    records = get_measurements(session, house, variable)
    if not records:
        raise ValueError(f"no measurement records for house={house.name!r}, variable={variable!r}")
    predicted = [r.predicted_value for r in records]
    measured = [r.measured_value for r in records]
    return val.error_metrics(predicted, measured)


def fit_and_save_calibration(session: Session, house: HouseConfig, variable: str) -> CalibrationFactorRecord:
    """Fit a linear calibration from stored measurement records for a
    house/variable (see `pcis.core.validation.fit_calibration`) and
    persist it, replacing any previous calibration for the same
    house/variable.
    """
    records = get_measurements(session, house, variable)
    if not records:
        raise ValueError(f"no measurement records for house={house.name!r}, variable={variable!r}")
    predicted = [r.predicted_value for r in records]
    measured = [r.measured_value for r in records]
    fit = val.fit_calibration(predicted, measured)

    existing = session.execute(
        select(CalibrationFactorRecord).where(
            CalibrationFactorRecord.house_id == house.id,
            CalibrationFactorRecord.variable == variable,
        )
    ).scalar_one_or_none()
    if existing is not None:
        session.delete(existing)
        session.flush()

    record = CalibrationFactorRecord(
        house_id=house.id,
        variable=variable,
        slope=fit.slope,
        intercept=fit.intercept,
        r_squared=fit.r_squared,
        n=fit.n,
    )
    session.add(record)
    session.flush()
    return record


def get_calibration(session: Session, house: HouseConfig, variable: str) -> CalibrationFactorRecord | None:
    """The current persisted calibration for a house/variable, or None
    if none has been fit yet.
    """
    stmt = select(CalibrationFactorRecord).where(
        CalibrationFactorRecord.house_id == house.id,
        CalibrationFactorRecord.variable == variable,
    )
    return session.execute(stmt).scalar_one_or_none()
