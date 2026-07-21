"""House-level sensible/latent heat and moisture balance.

Combines per-bird loads (from `pcis.core.bird_metabolism`) with flock
size to get whole-house loads, and provides building-envelope
conduction loss so a net heat/moisture load (the amount the
ventilation system must remove or add) can be computed.

References
----------
[ASHRAE17]  ASHRAE Handbook -- Fundamentals, 2017. Steady-state
            conduction through a building envelope, Q = U*A*dT, is
            the standard form of Fourier's law of conduction applied
            to a building assembly (Ch. 25/26); U = 1/R for a single
            layer, and R-values of series layers add (Ch. 26,
            Eq. 1-4). This is basic heat-transfer engineering, not a
            poultry-specific formula, and is implemented generically
            here -- the module does NOT hardcode R-values for named
            insulation materials ("fiberglass batt", "polyurethane
            foam", etc.), because I do not have a verified, sourced
            table of those values in this session. Callers must
            supply U-value or R-value directly (e.g. from a
            manufacturer spec sheet or a verified reference table).
            See `r_value_to_u_value` docstring for how to combine
            multiple layers.

Units: SI throughout. Areas in m^2, U-values in W/(m^2*K), R-values in
m^2*K/W, temperatures in Celsius, heat flows in W, moisture flows in
kg/h.
"""

from __future__ import annotations

from dataclasses import dataclass

from pcis.core import bird_metabolism as bm


# ---------------------------------------------------------------------------
# Building envelope conduction
# ---------------------------------------------------------------------------

def r_value_to_u_value(r_value_si: float) -> float:
    """Convert thermal resistance (R, m^2*K/W) to a U-value (W/(m^2*K)).

    U = 1/R [ASHRAE17, Ch. 26, basic definition of thermal
    transmittance]. If a wall/ceiling/floor assembly has multiple
    layers, sum their individual R-values first (R_total = R1 + R2 +
    ... + R_air_films), then convert the sum to U with this function.

    Parameters
    ----------
    r_value_si : float
        Total thermal resistance of the assembly, m^2*K/W (must be > 0).

    Returns
    -------
    float
        U-value, W/(m^2*K).
    """
    if r_value_si <= 0:
        raise ValueError("r_value_si must be positive")
    return 1.0 / r_value_si


def envelope_conduction_loss(u_value: float, area_m2: float, t_in_c: float, t_out_c: float) -> float:
    """Steady-state conduction heat flow through a building surface, W.

    Q = U * A * (T_in - T_out)  [ASHRAE17, Fourier's law applied to a
    building assembly]. Positive return value means heat flows from
    inside to outside (a loss the house must make up, e.g. in cold
    weather); negative means heat flows inward (a gain, e.g. solar-
    heated roof in summer, if T_out here is taken as a sol-air
    temperature).

    Parameters
    ----------
    u_value : float
        Overall heat transfer coefficient of the surface, W/(m^2*K).
    area_m2 : float
        Surface area, m^2.
    t_in_c : float
        Indoor air temperature, degrees Celsius.
    t_out_c : float
        Outdoor (or sol-air) temperature, degrees Celsius.

    Returns
    -------
    float
        Conductive heat flow, W (positive = loss to outside).
    """
    if u_value <= 0:
        raise ValueError("u_value must be positive")
    if area_m2 < 0:
        raise ValueError("area_m2 must be non-negative")
    return u_value * area_m2 * (t_in_c - t_out_c)


@dataclass(frozen=True)
class Surface:
    """One building-envelope surface (a wall, the ceiling, etc.).

    name : str
        Descriptive label, e.g. "sidewall_north", "ceiling".
    u_value : float
        W/(m^2*K). Use `r_value_to_u_value` if you have an R-value
        instead.
    area_m2 : float
        Surface area, m^2.
    """

    name: str
    u_value: float
    area_m2: float


def total_envelope_conduction_loss(surfaces: list[Surface], t_in_c: float, t_out_c: float) -> float:
    """Sum of conduction heat flow across all given surfaces, W.

    Simple superposition of `envelope_conduction_loss` over a list of
    surfaces -- valid because conduction through independent parallel
    paths (walls, ceiling, etc.) adds linearly [ASHRAE17].

    Parameters
    ----------
    surfaces : list[Surface]
        The house's envelope surfaces (walls, ceiling; floor losses
        to the ground are NOT well represented by a simple U*A*dT
        model because of ground thermal mass/coupling -- see the
        "Not implemented" note below).
    t_in_c : float
        Indoor air temperature, degrees Celsius.
    t_out_c : float
        Outdoor air temperature, degrees Celsius.

    Returns
    -------
    float
        Total conductive heat flow, W (positive = net loss to
        outside).

    Note
    ----
    Below-grade or slab-on-grade floor heat loss is NOT included by
    simply adding a floor Surface here with an ordinary U-value --
    ground-coupled heat transfer needs a different method (e.g.
    F-factor/perimeter methods in ASHRAE Fundamentals Ch. 18). If your
    house has a floor heat-loss path you want modeled, flag it rather
    than approximating it with a wall-style U*A*dT term.
    """
    return sum(envelope_conduction_loss(s.u_value, s.area_m2, t_in_c, t_out_c) for s in surfaces)


# ---------------------------------------------------------------------------
# Flock-level (whole-house) bird loads
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class FlockLoad:
    """Whole-house bird heat/moisture/CO2 production at one instant.

    All fields are house totals (already multiplied by bird count),
    derived from `pcis.core.bird_metabolism` per-bird functions.
    """

    bird_count: int
    body_weight_kg: float
    t_c: float
    total_heat_w: float
    sensible_heat_w: float
    latent_heat_w: float
    moisture_kg_per_h: float
    co2_m3_per_h: float


def flock_load(bird_count: int, body_weight_kg: float, t_c: float) -> FlockLoad:
    """Compute whole-house bird loads for a flock of uniform weight.

    Multiplies the per-bird CIGR-based values from
    `pcis.core.bird_metabolism` by bird_count. Assumes a uniform flock
    (single representative body weight) -- for a real flock with
    weight variation, call this per weight cohort and sum, or use the
    flock's average weight as an approximation (standard practice for
    house-level sizing, per the CIGR method this is built on).

    Parameters
    ----------
    bird_count : int
        Number of birds in the house (must be > 0).
    body_weight_kg : float
        Representative live body weight per bird, kg.
    t_c : float
        Room dry-bulb air temperature, degrees Celsius.

    Returns
    -------
    FlockLoad
        House-total heat, moisture, and CO2 production.
    """
    if bird_count <= 0:
        raise ValueError("bird_count must be positive")

    q_total = bm.total_heat_production(body_weight_kg)
    q_sens = bm.sensible_heat_production(body_weight_kg, t_c)
    q_lat = bm.latent_heat_production(body_weight_kg, t_c)
    moisture = bm.moisture_production(body_weight_kg, t_c)
    co2 = bm.co2_production(body_weight_kg)

    return FlockLoad(
        bird_count=bird_count,
        body_weight_kg=body_weight_kg,
        t_c=t_c,
        total_heat_w=q_total * bird_count,
        sensible_heat_w=q_sens * bird_count,
        latent_heat_w=q_lat * bird_count,
        moisture_kg_per_h=moisture * bird_count,
        co2_m3_per_h=co2 * bird_count,
    )


# ---------------------------------------------------------------------------
# Net house load
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class NetHeatMoistureLoad:
    """Net sensible heat, latent heat, and moisture load on the house
    air, after combining bird production, envelope conduction, and any
    supplemental heating.

    net_sensible_w : float
        Net sensible heat that ventilation air must remove (positive)
        or that heaters must supply (negative), W.
    latent_w : float
        Latent heat added to house air by the birds, W (envelope
        conduction is treated as sensible-only; it does not add
        moisture).
    moisture_kg_per_h : float
        Moisture added to house air, kg/h (from the flock; equal to
        `FlockLoad.moisture_kg_per_h` -- ventilation air must carry
        this away to hold a target indoor humidity ratio).
    """

    net_sensible_w: float
    latent_w: float
    moisture_kg_per_h: float


def net_house_load(
    flock: FlockLoad,
    envelope_loss_w: float,
    supplemental_heat_w: float = 0.0,
) -> NetHeatMoistureLoad:
    """Combine bird production, envelope loss, and supplemental heat
    into the net sensible/latent/moisture load ventilation must handle.

    Energy balance on the house air (steady state):
        net_sensible = bird_sensible_heat - envelope_loss + supplemental_heat

    envelope_loss_w should be the value from
    `total_envelope_conduction_loss` (positive = heat lost to
    outside, which *reduces* the net sensible load ventilation must
    remove; negative = heat gained from outside, e.g. solar/hot
    climate, which *adds* to the load).

    Parameters
    ----------
    flock : FlockLoad
        House-total bird loads, from `flock_load`.
    envelope_loss_w : float
        Total conductive heat loss through the envelope, W (from
        `total_envelope_conduction_loss`). Positive = loss to
        outside.
    supplemental_heat_w : float, optional
        Heater output added to the house air, W. Defaults to 0
        (no supplemental heating).

    Returns
    -------
    NetHeatMoistureLoad
        The net sensible heat (W), latent heat (W), and moisture
        (kg/h) that ventilation must remove.
    """
    net_sensible = flock.sensible_heat_w - envelope_loss_w + supplemental_heat_w
    return NetHeatMoistureLoad(
        net_sensible_w=net_sensible,
        latent_w=flock.latent_heat_w,
        moisture_kg_per_h=flock.moisture_kg_per_h,
    )
