"""Broiler heat, moisture, and CO2 production.

References
----------
[CIGR2002]  CIGR (2002), "4th Report of Working Group on Climatization of
            Animal Houses - Heat and Moisture Production at Animal and
            House Levels", Pedersen, S. and Sallvik, K. (eds.),
            International Commission of Agricultural and Biosystems
            Engineering (CIGR), Research Centre Bygholm, Denmark, 45 p.

[Aarnink2018]  Aarnink, A.J.A. (2018), "Heat and moisture production in
            growing-finishing pigs and broilers", Agricultural
            Engineering International: CIGR Journal, Special Issue:
            Animal Housing in Hot Climate. This peer-reviewed paper
            reproduces the CIGR (2002) broiler equations verbatim
            (as its Eq. 11 and Eq. 13) while discussing their
            limitations. Used here as the traceable secondary source
            for the exact CIGR (2002) broiler formulas, since the
            primary CIGR (2002) report was not directly available in
            this session. https://cigrjournal.org/index.php/Ejounral/article/view/4781

[Pedersen2008]  Pedersen, S., Blanes-Vidal, V., Joergensen, H.,
            Chwalibog, A., Haeussermann, A., Heetkamp, M.J.W., and
            Aarnink, A.J.A. (2008), "Carbon Dioxide Production in
            Animal Houses: A Literature Review", Agricultural
            Engineering International: CIGR Ejournal, Manuscript
            BC 08 008, Vol. X, December 2008. Table 6 gives
            provisional CO2 production values (m3/h per heat
            production unit) for broilers at animal and house level.
            https://cigrjournal.org/index.php/Ejounral/article/download/1205/1132/0

[ASHRAE17]  ASHRAE Handbook -- Fundamentals, 2017, Chapter 1. Used here
            for the latent heat of vaporization of water at the 0 C
            reference state (2501 kJ/kg), the same constant already
            used in pcis.core.psychrometrics.enthalpy for consistency.

Known limitations of the CIGR (2002) broiler method (see [Aarnink2018]
Section 3 "Conclusions")
-----------------------------------------------------------------------
1. Total heat production (Eq. 11 below) depends only on live body
   weight, not on metabolizable-energy intake -- the actual driver of
   heat production. [Aarnink2018] found the CIGR formula averaged
   11.3% higher than measured heat production in respiration-chamber
   trials with modern (Ross/Cobb-era) genetics.
2. The sensible/latent split (Eq. 13 below) depends only on room
   temperature, not on live weight -- [Aarnink2018] recommends adding
   a weight dependency, which CIGR (2002) does not provide.
3. These are Northern-European-conditions averages from the CIGR
   working group's source data, not breed-specific figures from
   Aviagen (Ross 308) or Cobb (Cobb 500) documentation.

These limitations are inherent to the CIGR (2002) method itself, not
to this implementation. They should be accounted for during Stage 3
(validation & calibration) -- e.g. by applying a calibration factor
derived from real farm/house data, per the project's validation plan.
"""

from __future__ import annotations

#: CIGR (2002) broiler total heat production coefficients, Eq. 11
#: [CIGR2002, via Aarnink2018 Eq. 11]: Qtotal = A * BW^B (W per bird)
_CIGR_BROILER_HEAT_A = 10.62
_CIGR_BROILER_HEAT_B = 0.75

#: CIGR (2002) broiler sensible-heat-fraction coefficients, Eq. 13
#: [CIGR2002, via Aarnink2018 Eq. 13]
_CIGR_BROILER_SENSIBLE_K0 = 0.61
_CIGR_BROILER_SENSIBLE_K1 = 20.0
_CIGR_BROILER_SENSIBLE_K2 = 0.228

#: Latent heat of vaporization of water at the 0 C reference state,
#: kJ/kg [ASHRAE17] -- same value used in psychrometrics.enthalpy's
#: 2501 coefficient, kept consistent across the codebase.
LATENT_HEAT_OF_VAPORIZATION_KJ_PER_KG = 2501.0

#: Pedersen et al. (2008) Table 6: provisional CO2 production for
#: broilers, m3 per hour per heat-production-unit (hpu), where
#: 1 hpu = 1000 W of total animal heat production at 20 C.
#: Keyed by (weight_class, level); "animal" excludes manure/litter
#: CO2 contribution, "house" includes it.
_CO2_PRODUCTION_M3_PER_H_PER_HPU = {
    ("under_0.5kg", "animal"): 0.165,
    ("under_0.5kg", "house"): 0.170,
    ("over_0.5kg", "animal"): 0.165,
    ("over_0.5kg", "house"): 0.180,
}


def total_heat_production(body_weight_kg: float) -> float:
    """Total heat production per bird, W.

    Qtotal = 10.62 * BW^0.75  [CIGR2002, via Aarnink2018 Eq. 11]

    This is NOT corrected for room temperature (the CIGR (2002)
    report gives temperature correction for the sensible/latent
    split -- see `sensible_heat_production` -- but not, in the
    source available here, for total heat itself; see module
    docstring, "Known limitations", item 1).

    Parameters
    ----------
    body_weight_kg : float
        Live body weight per bird, kg.

    Returns
    -------
    float
        Total heat production, W per bird.
    """
    if body_weight_kg <= 0:
        raise ValueError("body_weight_kg must be positive")
    return _CIGR_BROILER_HEAT_A * body_weight_kg ** _CIGR_BROILER_HEAT_B


def sensible_heat_production(body_weight_kg: float, t_c: float) -> float:
    """Sensible heat production per bird, W.

    Qsensible = [0.61*(1000 + 20*(20-Ti) - 0.228*Ti^2)] * Qtotal / 1000
    [CIGR2002, via Aarnink2018 Eq. 13]

    where Ti is room (dry-bulb) air temperature, degrees Celsius, and
    Qtotal is from `total_heat_production`.

    Parameters
    ----------
    body_weight_kg : float
        Live body weight per bird, kg.
    t_c : float
        Room dry-bulb air temperature, degrees Celsius.

    Returns
    -------
    float
        Sensible heat production, W per bird.
    """
    q_total = total_heat_production(body_weight_kg)
    bracket = _CIGR_BROILER_SENSIBLE_K0 * (
        1000.0
        + _CIGR_BROILER_SENSIBLE_K1 * (20.0 - t_c)
        - _CIGR_BROILER_SENSIBLE_K2 * t_c ** 2
    )
    fraction = bracket / 1000.0
    return fraction * q_total


def latent_heat_production(body_weight_kg: float, t_c: float) -> float:
    """Latent heat production per bird, W.

    Qlatent = Qtotal - Qsensible, per [CIGR2002, via Aarnink2018]
    (the CIGR method defines latent heat as the residual after
    subtracting sensible heat from total heat).

    Parameters
    ----------
    body_weight_kg : float
        Live body weight per bird, kg.
    t_c : float
        Room dry-bulb air temperature, degrees Celsius.

    Returns
    -------
    float
        Latent heat production, W per bird.
    """
    q_total = total_heat_production(body_weight_kg)
    q_sensible = sensible_heat_production(body_weight_kg, t_c)
    return q_total - q_sensible


def moisture_production(body_weight_kg: float, t_c: float) -> float:
    """Moisture production per bird, kg/h.

    Moisture production = Qlatent / h_fg, where h_fg is the latent
    heat of vaporization of water [CIGR2002 method, via Aarnink2018:
    "moisture production is calculated by dividing latent heat by the
    evaporative heat of water"]. h_fg is taken as 2501 kJ/kg
    [ASHRAE17], matching the reference-state constant already used in
    `pcis.core.psychrometrics.enthalpy`.

    Parameters
    ----------
    body_weight_kg : float
        Live body weight per bird, kg.
    t_c : float
        Room dry-bulb air temperature, degrees Celsius.

    Returns
    -------
    float
        Moisture production, kg water / hour per bird.
    """
    q_latent_w = latent_heat_production(body_weight_kg, t_c)
    q_latent_kj_per_h = q_latent_w * 3.6  # W = J/s -> kJ/h: *3600/1000
    return q_latent_kj_per_h / LATENT_HEAT_OF_VAPORIZATION_KJ_PER_KG


def co2_production(body_weight_kg: float, level: str = "animal") -> float:
    """CO2 production per bird, m^3/h.

    CO2 = c * (Qtotal / 1000), where c is the provisional CO2
    production factor (m3/h per heat-production-unit) from
    [Pedersen2008] Table 6, and Qtotal/1000 converts total heat
    production (W) to heat-production-units (1 hpu = 1000 W of total
    heat production at 20 C, the CIGR reference condition).

    c is selected by broiler weight class per [Pedersen2008] Table 6:
    under 0.5 kg or 0.5 kg and over. These are "provisional" literature
    averages from mixed European experiments, not breed-specific
    (Ross 308 / Cobb 500) or manufacturer figures -- treat as a
    first-pass estimate pending Stage 3 validation against real data.

    Parameters
    ----------
    body_weight_kg : float
        Live body weight per bird, kg.
    level : {"animal", "house"}, optional
        "animal" excludes manure/litter CO2 contribution (default);
        "house" includes it, per [Pedersen2008] Table 6.

    Returns
    -------
    float
        CO2 production, m^3 / hour per bird.
    """
    if level not in ("animal", "house"):
        raise ValueError("level must be 'animal' or 'house'")
    weight_class = "under_0.5kg" if body_weight_kg < 0.5 else "over_0.5kg"
    c = _CO2_PRODUCTION_M3_PER_H_PER_HPU[(weight_class, level)]
    q_total = total_heat_production(body_weight_kg)
    hpu = q_total / 1000.0
    return c * hpu
