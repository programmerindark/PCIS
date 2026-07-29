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
    #: Measured barometric pressure (hPa). Optional: when omitted PCIS
    #: assumes sea level, which overstates air density at altitude and so
    #: overstates how much heat each cubic metre of fan air can carry.
    pressure_hpa: float | None = Field(default=None, ge=500, le=1100)
    #: Anemometer reading from inside the house (m/s), when available.
    #: Used only as a cross-check on the computed air speed -- never as a
    #: substitute for it.
    measured_air_speed_mps: float | None = Field(default=None, ge=0, le=15)


class RecommendRequest(HouseFlockInputs):
    pass


class WeatherPoint(BaseModel):
    label: str
    t_c: float = Field(ge=-40, le=60)
    rh_pct: float = Field(ge=0, le=100)


class ScheduleRequest(HouseFlockInputs):
    profile: list[WeatherPoint] = Field(min_length=1)
    step_hours: float = Field(gt=0, le=24, default=3.0)


class MortalityRequest(BaseModel):
    placed: int = Field(gt=0)
    cumulative_dead: int = Field(ge=0)
    age_days: float = Field(ge=0, le=56)
    dead_today: int = Field(ge=0, default=0)
    #: Birds removed ALIVE (thinning / lifting / partial depletion).
    #: Never mortality -- see pcis/core/mortality.py for why conflating
    #: the two produces a false welfare alarm.
    depleted: int = Field(ge=0, default=0)


class EcowittCloudRequest(BaseModel):
    """Credentials from the user's ecowitt.net account."""
    application_key: str = Field(min_length=8)
    api_key: str = Field(min_length=8)
    mac: str = Field(min_length=6)
    #: Which Ecowitt block is PHYSICALLY inside the house. On this farm
    #: the WS90 array (Ecowitt's "outdoor" block) hangs inside, so that is
    #: the default -- see backend/app/ecowitt.py module docstring.
    indoor_block: str = "outdoor"
    #: Which block is physically outside. None = infer as "the other one".
    outdoor_block: str | None = None
    include_raw: bool = False       # debug: return the payload shape (keys stripped)


class EcowittLocalRequest(BaseModel):
    """Gateway IP on the farm LAN (no keys needed)."""
    gateway_ip: str = Field(min_length=7)
    indoor_block: str = "indoor"
    outdoor_block: str | None = None


class EcowittKeysRequest(BaseModel):
    application_key: str = Field(min_length=8)
    api_key: str = Field(min_length=8)
