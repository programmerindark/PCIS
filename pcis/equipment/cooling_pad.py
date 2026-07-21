"""Evaporative cooling pad specifications and leaving-air-state
calculation.

STATUS: Physical specs and design-guidance parameters loaded from real
sources (see below), now including a SECOND independent citation
([UGAExt2014], user-supplied) that corroborates the 150mm design point
and upgrades the 100mm pad from an unverified estimate to a cited
design figure. Unlike `fan_curve.py`, a precise manufacturer
velocity-vs-efficiency CURVE (continuous, many points) was still NOT
obtainable as machine-readable data -- see "What's missing" below
before trusting this module for detailed sizing beyond the two cited
design points.

References
----------
[Munters2022]  Munters, "Product Sheet: Munters CELdek Evaporative
    cooling pad", CELdek-PS-EN-202204, 2022. Physical specs (depths
    100/150/200/300mm, standard heights, material, flute angles) and
    the statement that published saturation-efficiency curves are
    "calculated with the following wash rate: 60 l/min/m2".
    https://www.munters.com/globalassets/digizuite/6108-en-celdek-ps-en-202204.pdf
    Retrieved 2026-07-20.

[MSUExtP3329]  Linhoss, J., Purswell, J. (USDA ARS Poultry Research
    Unit), Davis, J., and Campbell, J. (National Poultry Technology
    Center, Auburn University), "How Much Water Does Your Evaporative
    Cooling System Need?", Mississippi State University Extension
    Publication P3329. States: typical design air velocity entering a
    6-inch (150mm) pad is ~350 ft/min (1.78 m/s), with actual
    operating velocity ranging 150-600+ ft/min; make-up water
    calculations in that publication assume 75% saturation efficiency
    for a 6-inch pad at design conditions.
    https://extension.msstate.edu/publications/how-much-water-does-your-evaporative-cooling-system-need
    Retrieved 2026-07-20.

[UGAExt2014]  Czarick, M. (Extension Engineer) and Fairchild, B.
    (Extension Poultry Scientist), University of Georgia College of
    Agricultural and Environmental Sciences Cooperative Extension,
    "Poultry Housing Tips: Evaporative Cooling Pad Design
    Spreadsheet", Volume 26, Number 4, May 2014. User-supplied PDF,
    retrieved from www.poultryventilation.com/spreadsheets. States the
    standard sizing rule of thumb for BOTH pad depths: one square foot
    of 6-inch (150mm) pad per 350 cfm of exhaust fan capacity (=350
    ft/min = 1.78 m/s face velocity) and one square foot of 4-inch
    (100mm) pad per 225 cfm (=225 ft/min = 1.14 m/s face velocity).
    Quote: "Using these sizing guidelines, the pressure drop across
    the pads will be approximately 0.05" and the cooling efficiency
    will run between 70 and 75%." Also states pad systems are
    generally designed for 70-80% efficiency (resulting incoming RH
    75-85%), and that total system static pressure (pad + inlet/door +
    transition + duct) is typically 0.10-0.20 in. W.C., of which the
    pad itself is ~0.05 in. W.C. at design velocity.

[Warke2017]  Warke, D.A., and Deshmukh, S.J. (2017), "Experimental
    Analysis of Cellulose Cooling Pads Used in Evaporative Coolers",
    International Journal of Energy Science and Engineering, 3(4),
    37-43 (open access). Defines thermal effectiveness as
    eps = (Tin - Tout) / (Tin - Twb) -- the standard evaporative-
    cooling-pad efficiency definition used in `leaving_air_state`
    below. Reports (for generic 150mm-thick cellulose pad, NOT
    specifically CELdek-branded) a measured maximum effectiveness of
    90.4% at low air velocity, versus 61.2% for a 50mm-thick pad at
    the same fan speed -- included here only as an order-of-magnitude
    cross-check, not as CELdek-specific data.

What's missing (read before relying on this for precise sizing)
-------------------------------------------------------------------
Both Munters' own datasheet and every extension source found so far
publish saturation-efficiency and pressure-drop as either chart images
or a single design-point rule of thumb -- not a continuous table of
(velocity, efficiency) pairs. This module now has TWO independently
cited design points (150mm @ 1.78 m/s and 100mm @ 1.14 m/s, both in
the 70-75% efficiency band, per [MSUExtP3329] and [UGAExt2014]), which
is enough to run realistic single-operating-point calculations and a
digital-twin simulation at that point, but it is still NOT enough to
interpolate efficiency at velocities away from the design point the
way `fan_curve.py` interpolates across its full manufacturer curve.
`leaving_air_state` takes efficiency as a plain parameter, so if you
obtain the actual chart data (image or export) later, replacing the
single design-point assumption with a real interpolated curve is a
drop-in change.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from pcis.core import psychrometrics as psy


@dataclass(frozen=True)
class CoolingPad:
    """Physical specification for one cooling pad product/depth.

    design_velocity_mps : float
        Typical design air-face velocity, m/s [MSUExtP3329 for the
        150mm depth; other depths are not independently sourced --
        see `assumed_efficiency` note].
    design_velocity_range_mps : tuple[float, float]
        Observed operating range, m/s [MSUExtP3329].
    assumed_saturation_efficiency : float
        Design-point saturation efficiency assumption (0-1)
        [MSUExtP3329 and/or UGAExt2014 -- see per-record source].
        This is a single design-point assumption, NOT a fitted
        velocity-dependent curve -- see module docstring.
    design_pad_pressure_drop_pa : float | None
        Static pressure drop across the pad itself at design velocity,
        Pa [UGAExt2014: ~0.05 in. W.C.]. This is the pad's own
        contribution only -- total system static pressure (pad +
        inlet/door + transition + duct) is typically 2.5x-4x this
        value per the same source. None if not available for a given
        record.
    source : str
        Citation for this record.
    """

    manufacturer: str
    model: str
    depth_mm: float
    material: str
    design_velocity_mps: float
    design_velocity_range_mps: tuple[float, float]
    assumed_saturation_efficiency: float
    source: str
    standard_heights_mm: list[float] = field(default_factory=list)
    standard_width_mm: float | None = None
    design_pad_pressure_drop_pa: float | None = None

    def __post_init__(self) -> None:
        if not self.source or not self.source.strip():
            raise ValueError(
                "CoolingPad.source is required -- record where this "
                "data came from"
            )
        if not (0.0 < self.assumed_saturation_efficiency <= 1.0):
            raise ValueError("assumed_saturation_efficiency must be in (0, 1]")
        if self.design_pad_pressure_drop_pa is not None and self.design_pad_pressure_drop_pa <= 0.0:
            raise ValueError("design_pad_pressure_drop_pa must be positive if given")


# Both depths now have a directly-sourced design velocity and
# efficiency figure, corroborated by two independent extension
# publications: [MSUExtP3329] (150mm-specific) and [UGAExt2014]
# (states the sizing rule of thumb for both 150mm and 100mm pads in
# the same sentence, both landing in the 70-75% efficiency band).
CELDEK_7090_15_150MM = CoolingPad(
    manufacturer="Munters (CELdek)",
    model="CELdek 7090-15, 150mm depth",
    depth_mm=150.0,
    material="Corrugated impregnated cellulose paper, cross-fluted 60deg/30deg",
    design_velocity_mps=1.78,  # 350 ft/min [MSUExtP3329, UGAExt2014]
    design_velocity_range_mps=(0.76, 3.05),  # 150-600 ft/min [MSUExtP3329]
    assumed_saturation_efficiency=0.75,  # [MSUExtP3329]; corroborated
    # by [UGAExt2014]'s stated 70-75% range for this sizing guideline.
    design_pad_pressure_drop_pa=12.45,  # 0.05 in. W.C. [UGAExt2014]
    standard_heights_mm=[1000.0, 1200.0, 1500.0, 1800.0, 2000.0],
    standard_width_mm=600.0,
    source=(
        "Depth/material/heights: Munters CELdek Product Sheet "
        "CELdek-PS-EN-202204 (2022), "
        "https://www.munters.com/globalassets/digizuite/6108-en-celdek-ps-en-202204.pdf . "
        "Design velocity and assumed 75% saturation efficiency: "
        "Linhoss, Purswell (USDA ARS), Davis & Campbell (Auburn NPTC), "
        "'How Much Water Does Your Evaporative Cooling System Need?', "
        "MSU Extension Pub. P3329, "
        "https://extension.msstate.edu/publications/how-much-water-does-your-evaporative-cooling-system-need "
        "(stated specifically for 6-inch/150mm pads). Retrieved 2026-07-20. "
        "Corroborated by Czarick & Fairchild, 'Poultry Housing Tips: "
        "Evaporative Cooling Pad Design Spreadsheet', UGA Cooperative "
        "Extension, Vol. 26 No. 4, May 2014 (user-supplied PDF): same "
        "350 ft/min design velocity for 6-inch pad, cooling efficiency "
        "70-75%, pad static pressure drop ~0.05 in. W.C. at that "
        "velocity. NOTE: this is a single design-point assumption, "
        "not a velocity-dependent curve -- see cooling_pad.py module "
        "docstring."
    ),
)

CELDEK_7090_15_100MM = CoolingPad(
    manufacturer="Munters (CELdek)",
    model="CELdek 7090-15, 100mm depth",
    depth_mm=100.0,
    material="Corrugated impregnated cellulose paper, cross-fluted 60deg/30deg",
    design_velocity_mps=1.14,  # 225 ft/min [UGAExt2014]
    design_velocity_range_mps=(0.51, 2.03),
    assumed_saturation_efficiency=0.725,  # midpoint of [UGAExt2014]'s
    # cited 70-75% efficiency range for this sizing guideline (the
    # source gives one range covering both the 150mm and 100mm design
    # points, not two separate numbers -- using the midpoint here
    # rather than reusing the 150mm's specific 75% keeps the two
    # records honestly distinguishable while staying inside the cited
    # band).
    design_pad_pressure_drop_pa=12.45,  # 0.05 in. W.C. [UGAExt2014],
    # same cited figure as the 150mm pad (source gives one pressure
    # figure for "these sizing guidelines" covering both depths).
    standard_heights_mm=[1000.0, 1200.0, 1500.0, 1800.0, 2000.0],
    standard_width_mm=600.0,
    source=(
        "Depth/material/heights: Munters CELdek Product Sheet "
        "CELdek-PS-EN-202204 (2022). Design velocity (225 fpm), "
        "cooling efficiency (70-75% band, midpoint used here), and "
        "pad pressure drop (~0.05 in. W.C.): Czarick & Fairchild, "
        "'Poultry Housing Tips: Evaporative Cooling Pad Design "
        "Spreadsheet', UGA Cooperative Extension, Vol. 26 No. 4, May "
        "2014 (user-supplied PDF), which states the sizing rule of "
        "thumb 'one square foot of pad for every 225 cfm of exhaust "
        "fan capacity' for a 4-inch pad, alongside the equivalent "
        "6-inch-pad figure, both yielding 70-75% cooling efficiency "
        "at ~0.05 in. W.C. pad pressure drop. This upgrades the "
        "previous unverified 0.65 estimate to a cited design figure."
    ),
)

COOLING_PAD_CATALOG: list[CoolingPad] = [CELDEK_7090_15_150MM, CELDEK_7090_15_100MM]


@dataclass(frozen=True)
class LeavingAirState:
    """Air state after passing through an evaporative cooling pad."""

    t_c: float
    rh_pct: float
    w: float
    wet_bulb_c: float
    efficiency: float


def leaving_air_state(
    inlet_t_c: float,
    inlet_rh_pct: float,
    efficiency: float,
    p_pa: float = psy.STANDARD_ATM_PRESSURE_PA,
) -> LeavingAirState:
    """Air state leaving a wetted evaporative cooling pad.

    Standard evaporative-cooling-pad physics: the process is
    approximated as adiabatic saturation, i.e. following a line of
    constant wet-bulb temperature. Saturation efficiency is defined
    as [Warke2017, and standard HVAC usage generally]:

        efficiency = (T_in - T_out) / (T_in - Twb_in)

    Solved for T_out, then the humidity ratio of the leaving air is
    recovered by holding wet-bulb temperature fixed at the inlet's
    wet-bulb value (`psychrometrics.humidity_ratio_from_wet_bulb`).

    Parameters
    ----------
    inlet_t_c : float
        Inlet (outdoor) dry-bulb temperature, degrees Celsius.
    inlet_rh_pct : float
        Inlet relative humidity, percent.
    efficiency : float
        Saturation efficiency, 0-1. Use a `CoolingPad.
        assumed_saturation_efficiency` value, or a precise
        manufacturer figure if you have one -- see module docstring
        for why this module doesn't ship a full velocity-dependent
        curve.
    p_pa : float, optional
        Atmospheric pressure, Pa.

    Returns
    -------
    LeavingAirState
        Dry-bulb temp, RH, humidity ratio, and wet-bulb temp of the
        air leaving the pad.
    """
    if not (0.0 < efficiency <= 1.0):
        raise ValueError("efficiency must be in (0, 1]")

    w_in = psy.humidity_ratio_from_relative_humidity(inlet_t_c, inlet_rh_pct, p_pa)
    twb_in = psy.wet_bulb_temperature(inlet_t_c, w_in, p_pa)

    t_out = inlet_t_c - efficiency * (inlet_t_c - twb_in)
    w_out = psy.humidity_ratio_from_wet_bulb(t_out, twb_in, p_pa)
    rh_out = psy.relative_humidity_from_humidity_ratio(t_out, w_out, p_pa)

    return LeavingAirState(t_c=t_out, rh_pct=rh_out, w=w_out, wet_bulb_c=twb_in, efficiency=efficiency)
