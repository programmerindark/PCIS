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
) -> RecommendationLog:
    """Persist a full snapshot of a `recommendation_engine.recommend()`
    call -- inputs and outputs both -- for later review or Stage 3
    validation (comparing recommended settings to what was actually
    run and observed).
    """
    log = RecommendationLog(
        house_id=house.id,
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
