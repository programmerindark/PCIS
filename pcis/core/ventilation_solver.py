"""Ventilation rate solver: required airflow, air changes/hour, tunnel
airspeed, and fan-count sizing.

Two ventilation regimes are modeled, matching standard broiler-house
design practice:

1. Minimum (cold/mild-weather) ventilation -- a per-bird rate, looked
   up directly from Aviagen's published table (see
   `minimum_ventilation_rate_aviagen`), used for timer-cycled minimum
   ventilation in cold weather / brooding.
2. Heat-stress / tunnel (warm-weather) ventilation -- computed from a
   sensible-heat energy balance (see
   `required_airflow_for_sensible_heat`), used when the house needs
   active cooling and minimum-ventilation rates are far too low.

A moisture-balance and a CO2-dilution check (see
`required_airflow_for_moisture`, `co2_ventilation_requirement`) are
also provided as independent constraints -- the governing (design)
airflow is the largest of whichever constraints apply to the season
in question; see `governing_airflow`.

References
----------
[Aviagen2018]  Aviagen, "AviagenBrief: Minimum Ventilation Rates for
    Today's Broiler", February 2018. Table 1 (live weight vs. minimum
    ventilation rate, m3/hr per bird), valid for ambient temperatures
    between -1 and 16 C. Also source of the air-quality thresholds
    used as defaults below (CO2 < 3000 ppm, CO < 10 ppm, NH3 < 10 ppm,
    RH 60-70% days 1-3 / 50-60% thereafter).
    https://aviagen.com/assets/Tech_Center/Broiler_Breeder_Tech_Articles/English/AviagenBrief-VentilationRates-2018-EN.pdf
    Retrieved 2026-07-20.

[ASHRAE17]  ASHRAE Handbook -- Fundamentals, 2017, Chapter 1. The
    sensible-heat-removal ventilation equation
    (Q = m_dot * cp * dT) is standard HVAC engineering, not
    poultry-specific; cp of moist air (1.006 + 1.86*W kJ/(kg da*K))
    uses the same coefficients already cited in
    `psychrometrics.enthalpy`.

The CO2-dilution ventilation formula itself (steady-state contaminant
mass balance, V = production / (C_target - C_outdoor)) is standard
indoor-air-quality engineering (the same logic underlies ASHRAE
Standard 62.1 ventilation-for-acceptable-IAQ calculations); it is
implemented generically here and takes target/outdoor concentrations
as parameters rather than hardcoding them, except where an
[Aviagen2018] default is explicitly noted.

Units: SI. Airflow in m^3/h unless noted; temperatures in Celsius.
"""

from __future__ import annotations

import math

from pcis.core import psychrometrics as psy


# ---------------------------------------------------------------------------
# Aviagen minimum ventilation table [Aviagen2018, Table 1]
# ---------------------------------------------------------------------------

#: (live_weight_kg, min_ventilation_m3_per_h_per_bird), exactly as
#: published. Valid only for ambient temperatures -1 to 16 C.
_AVIAGEN_MIN_VENT_TABLE = [
    (0.05, 0.080), (0.10, 0.141), (0.15, 0.208), (0.20, 0.258),
    (0.25, 0.305), (0.30, 0.350), (0.35, 0.393), (0.40, 0.435),
    (0.45, 0.475), (0.50, 0.514), (0.55, 0.552), (0.60, 0.589),
    (0.65, 0.625), (0.70, 0.661), (0.75, 0.696), (0.80, 0.731),
    (0.85, 0.765), (0.90, 0.798), (0.95, 0.831), (1.00, 0.864),
    (1.10, 0.928), (1.20, 0.991), (1.30, 1.052), (1.40, 1.112),
    (1.50, 1.171), (1.60, 1.229), (1.70, 1.286), (1.80, 1.343),
    (1.90, 1.398), (2.00, 1.453), (2.20, 1.561), (2.40, 1.666),
    (2.60, 1.769), (2.80, 1.870), (3.00, 1.969), (3.20, 2.067),
    (3.40, 2.163), (3.60, 2.258), (3.80, 2.352), (4.00, 2.444),
    (4.20, 2.535), (4.40, 2.625),
]

#: Ambient temperature validity range for the table above, degrees C.
AVIAGEN_MIN_VENT_VALID_TEMP_RANGE_C = (-1.0, 16.0)

#: Body-weight bounds of the table above, kg. Exported (rather than
#: left implicit inside the private table) so callers can check whether
#: a weight is simulatable BEFORE calling and surface a meaningful
#: message, instead of discovering it as a ValueError from deep inside
#: `minimum_ventilation_rate_aviagen`. `pcis.core.digital_twin` uses
#: these to derive its earliest simulatable bird age.
AVIAGEN_MIN_VENT_MIN_WEIGHT_KG = _AVIAGEN_MIN_VENT_TABLE[0][0]
AVIAGEN_MIN_VENT_MAX_WEIGHT_KG = _AVIAGEN_MIN_VENT_TABLE[-1][0]

#: Air-quality thresholds that should never be exceeded [Aviagen2018].
AVIAGEN_MAX_CO2_PPM = 3000.0
AVIAGEN_MAX_CO_PPM = 10.0
AVIAGEN_MAX_NH3_PPM = 10.0


def minimum_ventilation_rate_aviagen(body_weight_kg: float) -> float:
    """Minimum (timer-cycled) ventilation rate per bird, m^3/h.

    Linear interpolation on the published Aviagen table
    [Aviagen2018, Table 1]. This table is explicitly stated to apply
    only for ambient temperatures between -1 and 16 C -- it is a
    cold/mild-weather minimum, not a cooling/heat-stress rate. For
    warm weather, use `required_airflow_for_sensible_heat` instead.

    Parameters
    ----------
    body_weight_kg : float
        Live body weight per bird, kg. Must be within the table's
        range [0.05, 4.40] kg -- this function refuses to extrapolate.

    Returns
    -------
    float
        Minimum ventilation rate, m^3/h per bird.
    """
    xs = [p[0] for p in _AVIAGEN_MIN_VENT_TABLE]
    ys = [p[1] for p in _AVIAGEN_MIN_VENT_TABLE]
    if body_weight_kg < xs[0] or body_weight_kg > xs[-1]:
        raise ValueError(
            f"body_weight_kg={body_weight_kg} is outside the Aviagen "
            f"(2018) table range [{xs[0]}, {xs[-1]}] kg; refusing to "
            "extrapolate beyond published data"
        )
    for (x0, y0), (x1, y1) in zip(_AVIAGEN_MIN_VENT_TABLE, _AVIAGEN_MIN_VENT_TABLE[1:]):
        if x0 <= body_weight_kg <= x1:
            if x1 == x0:
                return y0
            frac = (body_weight_kg - x0) / (x1 - x0)
            return y0 + frac * (y1 - y0)
    return ys[-1]


# ---------------------------------------------------------------------------
# Sensible-heat-driven (warm-weather / tunnel) ventilation requirement
# ---------------------------------------------------------------------------

def required_airflow_for_sensible_heat(
    net_sensible_w: float,
    delta_t_c: float,
    inlet_t_c: float,
    inlet_rh_pct: float,
    p_pa: float = psy.STANDARD_ATM_PRESSURE_PA,
) -> float:
    """Airflow required to remove a sensible heat load, m^3/h.

    From the sensible-heat energy balance on ventilation air
    [ASHRAE17]: Q = m_dot_da * cp_moist * dT, solved for volumetric
    flow using the inlet air's specific volume.

    Parameters
    ----------
    net_sensible_w : float
        Net sensible heat load to be removed, W (e.g. from
        `heat_moisture_balance.net_house_load().net_sensible_w`).
        Must be positive (a cooling/removal problem); if the house
        has a net sensible deficit, ventilation cannot fix that --
        supplemental heat is needed instead.
    delta_t_c : float
        Design temperature rise allowed across the house (indoor
        target minus inlet/outdoor temperature), degrees C. Must be
        positive.
    inlet_t_c : float
        Inlet (outdoor) air dry-bulb temperature, degrees C.
    inlet_rh_pct : float
        Inlet (outdoor) air relative humidity, percent.
    p_pa : float, optional
        Atmospheric pressure, Pa.

    Returns
    -------
    float
        Required airflow, m^3/h.
    """
    if net_sensible_w <= 0:
        raise ValueError(
            "net_sensible_w must be positive (a cooling problem); a "
            "non-positive value means there is no excess sensible "
            "heat for ventilation to remove"
        )
    if delta_t_c <= 0:
        raise ValueError("delta_t_c must be positive")

    w_inlet = psy.humidity_ratio_from_relative_humidity(inlet_t_c, inlet_rh_pct, p_pa)
    cp_moist_kj_per_kgk = 1.006 + 1.86 * w_inlet  # [ASHRAE17], same coefficients as enthalpy()
    cp_moist_j_per_kgk = cp_moist_kj_per_kgk * 1000.0

    m_dot_da_kg_per_s = net_sensible_w / (cp_moist_j_per_kgk * delta_t_c)
    v_specific = psy.specific_volume(inlet_t_c, w_inlet, p_pa)
    volumetric_m3_per_s = m_dot_da_kg_per_s * v_specific
    return volumetric_m3_per_s * 3600.0


# ---------------------------------------------------------------------------
# Moisture-driven ventilation requirement
# ---------------------------------------------------------------------------

def required_airflow_for_moisture(
    moisture_load_kg_per_h: float,
    indoor_t_c: float,
    indoor_rh_pct: float,
    inlet_t_c: float,
    inlet_rh_pct: float,
    p_pa: float = psy.STANDARD_ATM_PRESSURE_PA,
) -> float:
    """Airflow required to hold a target indoor humidity, m^3/h.

    Steady-state moisture mass balance: the ventilation air must carry
    away moisture at the same rate the flock produces it, without
    letting the indoor humidity ratio exceed the target
    (indoor_t_c, indoor_rh_pct) state.

        m_dot_da = moisture_load / (W_indoor - W_inlet)

    Parameters
    ----------
    moisture_load_kg_per_h : float
        House moisture production, kg/h (e.g. from
        `heat_moisture_balance.FlockLoad.moisture_kg_per_h`).
    indoor_t_c, indoor_rh_pct : float
        Target indoor (exhaust) dry-bulb temperature (C) and relative
        humidity (%) -- the maximum humidity condition to be held.
    inlet_t_c, inlet_rh_pct : float
        Inlet (outdoor) dry-bulb temperature (C) and relative
        humidity (%).
    p_pa : float, optional
        Atmospheric pressure, Pa.

    Returns
    -------
    float
        Required airflow, m^3/h.
    """
    w_indoor = psy.humidity_ratio_from_relative_humidity(indoor_t_c, indoor_rh_pct, p_pa)
    w_inlet = psy.humidity_ratio_from_relative_humidity(inlet_t_c, inlet_rh_pct, p_pa)
    if w_indoor <= w_inlet:
        raise ValueError(
            "indoor humidity ratio must exceed inlet humidity ratio "
            "for ventilation to be able to remove moisture; check "
            "indoor/inlet temperature and RH inputs"
        )
    m_dot_da_kg_per_h = moisture_load_kg_per_h / (w_indoor - w_inlet)
    v_specific = psy.specific_volume(inlet_t_c, w_inlet, p_pa)
    return m_dot_da_kg_per_h * v_specific


# ---------------------------------------------------------------------------
# CO2-driven ventilation requirement
# ---------------------------------------------------------------------------

def co2_ventilation_requirement(
    co2_production_m3_per_h: float,
    target_indoor_ppm: float = AVIAGEN_MAX_CO2_PPM,
    outdoor_ppm: float = 420.0,
) -> float:
    """Airflow required to hold indoor CO2 at or below a target, m^3/h.

    Steady-state contaminant mass balance (standard indoor-air-quality
    dilution ventilation, e.g. the logic underlying ASHRAE 62.1):

        V_dot = production / ((C_target - C_outdoor) * 1e-6)

    Parameters
    ----------
    co2_production_m3_per_h : float
        House CO2 production, m^3/h (e.g. from
        `heat_moisture_balance.FlockLoad.co2_m3_per_h`).
    target_indoor_ppm : float, optional
        Maximum acceptable indoor CO2 concentration, ppm. Defaults to
        3000 ppm [Aviagen2018] -- confirm this against your own
        breed/region guidance if it differs.
    outdoor_ppm : float, optional
        Ambient outdoor CO2 concentration, ppm. Defaults to 420 ppm,
        an approximate global-average atmospheric background as of
        the mid-2020s -- this drifts over time and by location; pass
        a locally measured value if precision matters.

    Returns
    -------
    float
        Required airflow, m^3/h.
    """
    if target_indoor_ppm <= outdoor_ppm:
        raise ValueError("target_indoor_ppm must exceed outdoor_ppm")
    return co2_production_m3_per_h / ((target_indoor_ppm - outdoor_ppm) * 1e-6)


# ---------------------------------------------------------------------------
# Air changes / hour, tunnel airspeed, governing airflow, fan count
# ---------------------------------------------------------------------------

def air_changes_per_hour(airflow_m3_per_h: float, house_volume_m3: float) -> float:
    """Air changes per hour = airflow / house volume."""
    if house_volume_m3 <= 0:
        raise ValueError("house_volume_m3 must be positive")
    return airflow_m3_per_h / house_volume_m3


def tunnel_airspeed(airflow_m3_per_h: float, cross_section_area_m2: float) -> float:
    """Tunnel (bulk) air velocity, m/s, given airflow and the house's
    cross-sectional area (width x eave/ceiling height, typically).
    """
    if cross_section_area_m2 <= 0:
        raise ValueError("cross_section_area_m2 must be positive")
    return (airflow_m3_per_h / 3600.0) / cross_section_area_m2


def governing_airflow(*requirements_m3_per_h: float) -> float:
    """The design (governing) airflow is the largest of the applicable
    constraint requirements (heat, moisture, CO2, minimum-ventilation
    per bird x bird count, etc.) -- standard ventilation design
    practice: satisfy the most restrictive constraint, not the
    average.
    """
    if not requirements_m3_per_h:
        raise ValueError("at least one requirement must be provided")
    return max(requirements_m3_per_h)


def required_fan_count(required_airflow_m3_per_h: float, fan_airflow_m3_per_h: float) -> int:
    """Number of identical fans needed to meet a required airflow.

    Simple ceiling division -- assumes fans operate in parallel at
    the same static pressure point (fan_airflow_m3_per_h should
    already be each fan's delivered airflow at the design static
    pressure, e.g. from
    `pcis.equipment.fan_curve.FanCurve.airflow_at_static_pressure`).

    Parameters
    ----------
    required_airflow_m3_per_h : float
        Total airflow the house needs, m^3/h.
    fan_airflow_m3_per_h : float
        Airflow delivered by one fan at the design static pressure,
        m^3/h.

    Returns
    -------
    int
        Number of fans required (rounded up).
    """
    if required_airflow_m3_per_h < 0:
        raise ValueError("required_airflow_m3_per_h must be non-negative")
    if fan_airflow_m3_per_h <= 0:
        raise ValueError("fan_airflow_m3_per_h must be positive")
    return math.ceil(required_airflow_m3_per_h / fan_airflow_m3_per_h)


#: Minimum humidity-ratio gradient (kg water / kg dry air) for ventilation
#: to be a practical moisture-removal mechanism. Mirrors
#: `recommendation_engine.MOISTURE_MIN_HUMIDITY_RATIO_DIFF`; defined here
#: too so this module stays importable on its own. PCIS engineering
#: judgment, not a literature value.
DRYING_MIN_HUMIDITY_RATIO_DIFF = 0.0005


def outdoor_rh_threshold_for_drying(
    indoor_t_c: float,
    indoor_rh_pct: float,
    outdoor_t_c: float,
    p_pa: float = psy.STANDARD_ATM_PRESSURE_PA,
    min_diff: float = DRYING_MIN_HUMIDITY_RATIO_DIFF,
) -> float | None:
    """Outdoor RH below which ventilation starts removing moisture again.

    Ventilation dries a house only when the incoming air holds less water
    per kg of dry air than the house air does. In humid weather that
    gradient can vanish or reverse, at which point running more fans adds
    water instead of removing it.

    Rather than leaving the operator with "ventilation cannot dehumidify"
    and no idea how long that will last, this returns the outdoor relative
    humidity at which drying resumes -- a single number they can watch on
    a forecast or a sensor.

    Returns None when the outdoor air is so much colder than the house
    that it can never carry enough moisture to matter, or when drying
    already works at any humidity (threshold >= 100%).
    """
    w_indoor = psy.humidity_ratio_from_relative_humidity(
        indoor_t_c, indoor_rh_pct, p_pa
    )
    target_w = w_indoor - min_diff
    if target_w <= 0:
        return None

    # Already drying at saturated outdoor air: no threshold to report.
    w_at_saturation = psy.humidity_ratio_from_relative_humidity(
        outdoor_t_c, 100.0, p_pa
    )
    if w_at_saturation <= target_w:
        return None

    # Humidity ratio rises monotonically with RH at fixed temperature and
    # pressure, so a bisection is exact to within the tolerance below.
    lo, hi = 0.0, 100.0
    for _ in range(60):
        mid = (lo + hi) / 2.0
        w_mid = psy.humidity_ratio_from_relative_humidity(outdoor_t_c, mid, p_pa)
        if w_mid > target_w:
            hi = mid
        else:
            lo = mid
    return round(lo, 1)
