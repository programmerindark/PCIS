"""SQLAlchemy 2.0 declarative models for PCIS persistence.

Schema overview
----------------
HouseConfig
    A physical house: floor dimensions plus a set of EnvelopeSurface
    rows (walls, ceiling -- see `pcis.core.heat_moisture_balance.Surface`
    for the engineering meaning of U-value/area).
EnvelopeSurface
    One conduction-loss surface belonging to a HouseConfig.
FlockRecord
    A bird-count/weight reading for a house at a point in time. The
    `breed` field is informational only right now -- see note below.
RecommendationLog
    A saved snapshot of one `recommendation_engine.recommend()` call:
    the inputs, the outputs, and the full explanation text, so past
    recommendations can be reviewed or used for Stage 3 validation
    (comparing recommended vs. actually-observed conditions).
MeasurementRecord
    One predicted-vs-measured pair for a named variable (e.g.
    "indoor_t_c", "static_pressure_pa", "airflow_m3_per_h",
    "body_weight_kg") at a house, for validation/calibration -- see
    `pcis.core.validation`.
CalibrationFactorRecord
    A fitted linear calibration (see `pcis.core.validation.
    fit_calibration`, whose return type is the plain dataclass
    `CalibrationFactor` -- this ORM class is its persisted form, named
    distinctly to avoid confusion) for one variable at one house,
    persisted so it can be reapplied to future predictions without
    refitting every time.

Note on breed
-------------
`FlockRecord.breed` is stored as free text (e.g. "Ross 308", "Cobb
500") for record-keeping, but the engineering core does not currently
branch on breed: `bird_metabolism.py` uses the generic CIGR (2002)
broiler formula (not breed-specific), and `comfort_engine.py`'s
target-temperature table and `ventilation_solver.py`'s minimum-
ventilation table are both sourced from Aviagen (Ross-lineage)
publications. If Cobb-specific figures differ and you have a source
for them, that would be a legitimate future refinement -- flagging
this now rather than implying breed-specific accuracy that doesn't
exist yet.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class HouseConfig(Base):
    __tablename__ = "house_configs"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), unique=True)
    length_m: Mapped[float]
    width_m: Mapped[float]
    height_m: Mapped[float]
    created_at: Mapped[dt.datetime] = mapped_column(default=dt.datetime.utcnow)

    surfaces: Mapped[list["EnvelopeSurface"]] = relationship(
        back_populates="house", cascade="all, delete-orphan"
    )
    flock_records: Mapped[list["FlockRecord"]] = relationship(
        back_populates="house", cascade="all, delete-orphan"
    )
    recommendations: Mapped[list["RecommendationLog"]] = relationship(
        back_populates="house", cascade="all, delete-orphan"
    )
    measurements: Mapped[list["MeasurementRecord"]] = relationship(
        back_populates="house", cascade="all, delete-orphan"
    )
    calibration_factors: Mapped[list["CalibrationFactorRecord"]] = relationship(
        back_populates="house", cascade="all, delete-orphan"
    )

    @property
    def floor_area_m2(self) -> float:
        return self.length_m * self.width_m

    @property
    def volume_m3(self) -> float:
        return self.length_m * self.width_m * self.height_m


class EnvelopeSurface(Base):
    __tablename__ = "envelope_surfaces"

    id: Mapped[int] = mapped_column(primary_key=True)
    house_id: Mapped[int] = mapped_column(ForeignKey("house_configs.id"))
    name: Mapped[str] = mapped_column(String(100))
    u_value: Mapped[float]  # W/(m^2*K)
    area_m2: Mapped[float]

    house: Mapped["HouseConfig"] = relationship(back_populates="surfaces")


class FlockRecord(Base):
    __tablename__ = "flock_records"

    id: Mapped[int] = mapped_column(primary_key=True)
    house_id: Mapped[int] = mapped_column(ForeignKey("house_configs.id"))
    breed: Mapped[str] = mapped_column(String(100))  # informational only -- see module docstring
    bird_count: Mapped[int]
    body_weight_kg: Mapped[float]
    recorded_at: Mapped[dt.datetime] = mapped_column(default=dt.datetime.utcnow)

    house: Mapped["HouseConfig"] = relationship(back_populates="flock_records")


class RecommendationLog(Base):
    __tablename__ = "recommendation_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    house_id: Mapped[int] = mapped_column(ForeignKey("house_configs.id"))
    timestamp: Mapped[dt.datetime] = mapped_column(default=dt.datetime.utcnow)

    # Inputs snapshot
    bird_count: Mapped[int]
    body_weight_kg: Mapped[float]
    indoor_t_c: Mapped[float]
    indoor_rh_pct: Mapped[float]
    outdoor_t_c: Mapped[float]
    outdoor_rh_pct: Mapped[float]

    # Outputs snapshot
    fans_on: Mapped[int]
    pads_on: Mapped[bool]
    required_airflow_m3_per_h: Mapped[float]
    governing_constraint: Mapped[str] = mapped_column(String(50))
    confidence_score: Mapped[float]
    explanation: Mapped[str] = mapped_column(Text)  # newline-joined explanation lines

    house: Mapped["HouseConfig"] = relationship(back_populates="recommendations")


class MeasurementRecord(Base):
    """One predicted-vs-measured pair for a named variable, for
    validation/calibration. See `pcis.core.validation`.
    """

    __tablename__ = "measurement_records"

    id: Mapped[int] = mapped_column(primary_key=True)
    house_id: Mapped[int] = mapped_column(ForeignKey("house_configs.id"))
    variable: Mapped[str] = mapped_column(String(50))  # e.g. "indoor_t_c", "airflow_m3_per_h"
    predicted_value: Mapped[float]
    measured_value: Mapped[float]
    recorded_at: Mapped[dt.datetime] = mapped_column(default=dt.datetime.utcnow)

    house: Mapped["HouseConfig"] = relationship(back_populates="measurements")


class CalibrationFactorRecord(Base):
    """A fitted linear calibration (see `pcis.core.validation.
    fit_calibration`) for one variable at one house.
    """

    __tablename__ = "calibration_factors"

    id: Mapped[int] = mapped_column(primary_key=True)
    house_id: Mapped[int] = mapped_column(ForeignKey("house_configs.id"))
    variable: Mapped[str] = mapped_column(String(50))
    slope: Mapped[float]
    intercept: Mapped[float]
    r_squared: Mapped[float]
    n: Mapped[int]
    fitted_at: Mapped[dt.datetime] = mapped_column(default=dt.datetime.utcnow)

    house: Mapped["HouseConfig"] = relationship(back_populates="calibration_factors")
