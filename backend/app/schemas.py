"""Request/response models for the PCIS API (Pydantic v2)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Insulation = Literal["uninsulated", "insulated", "well_insulated"]


class HouseFlockInputs(BaseModel):
    """The shared inputs describing one house + flock + operating point."""

    length_m: float = Field(gt=0, le=500)
    width_m: float = Field(gt=0, le=100)
    height_m: float = Field(gt=0, le=20)
    insulation: Insulation = "insulated"
    fan_index: int = Field(ge=0)
    installed_fans: int = Field(ge=0, le=200)
    static_pressure_pa: float = Field(ge=0, le=200)
    cooling_pads: bool = False
    heater_kw: float = Field(ge=0, le=2000)
    bird_age_days: int = Field(ge=0, le=56)
    bird_count: int = Field(ge=1, le=500_000)
    indoor_rh_pct: float = Field(ge=0, le=100)
    outdoor_t_c: float = Field(ge=-40, le=60)
    outdoor_rh_pct: float = Field(ge=0, le=100)


class RecommendRequest(HouseFlockInputs):
    pass


class WeatherPoint(BaseModel):
    label: str
    t_c: float = Field(ge=-40, le=60)
    rh_pct: float = Field(ge=0, le=100)


class ScheduleRequest(HouseFlockInputs):
    profile: list[WeatherPoint] = Field(min_length=1)
    step_hours: float = Field(gt=0, le=24, default=3.0)
