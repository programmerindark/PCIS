"""Psychrometric properties of moist air.

All functions use SI units internally:
    - temperature      : degrees Celsius (float), unless noted as Kelvin
    - pressure          : Pascals (Pa)
    - humidity ratio W  : kg water / kg dry air
    - relative humidity : percent (0-100)
    - enthalpy          : kJ / kg dry air
    - specific volume   : m^3 / kg dry air
    - density           : kg / m^3 (moist air, per unit total volume)

References
----------
[ASHRAE17]  ASHRAE Handbook -- Fundamentals, 2017, Chapter 1
            "Psychrometrics". Equations for humidity ratio, enthalpy,
            specific volume, and the wet-bulb energy balance are taken
            from this chapter (SI unit equations 22, 32, 28, and the
            wet-bulb/humidity-ratio relation, eq. 35).
[Buck1996]  Buck, A. L. (1996), "Buck Research CR-1A User's Manual",
            Appendix 1. Revised saturation vapor pressure formulas
            (an update of Buck, A. L., 1981, J. Appl. Meteorol., 20,
            1527-1532). Used here for saturation vapor pressure over
            water and over ice.

Every function below cites the specific equation it implements. If you
need a psychrometric quantity not covered here, add it with an explicit
citation -- do not interpolate or guess a formula.
"""

from __future__ import annotations

import math

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Standard atmospheric pressure at sea level, Pa [ASHRAE17, Ch.1]
STANDARD_ATM_PRESSURE_PA = 101_325.0

#: Ratio of molar mass of water to molar mass of dry air, M_w/M_da
#: = 18.015268 / 28.966 [ASHRAE17, Ch.1, Table 1]
WATER_TO_DRY_AIR_MOLAR_MASS_RATIO = 0.621945

#: Specific gas constant for dry air, J/(kg*K) [ASHRAE17, Ch.1]
R_DRY_AIR = 287.055

#: Absolute zero offset, K
KELVIN_OFFSET = 273.15


def c_to_k(t_c: float) -> float:
    """Convert Celsius to Kelvin."""
    return t_c + KELVIN_OFFSET


def k_to_c(t_k: float) -> float:
    """Convert Kelvin to Celsius."""
    return t_k - KELVIN_OFFSET


# ---------------------------------------------------------------------------
# Saturation vapor pressure
# ---------------------------------------------------------------------------

def saturation_vapor_pressure(t_c: float) -> float:
    """Saturation vapor pressure of water in moist air, Pa.

    Uses the Buck (1996) revised equations, which are accurate to
    within about 0.2% over -40 C to +50 C (over water) and -80 C to
    0 C (over ice) [Buck1996]. The water-phase formula is used for
    t_c >= 0; the ice-phase formula is used for t_c < 0 (sublimation
    equilibrium), consistent with ASHRAE's convention of using the
    ice curve below 0 C, e.g. for early-morning cold-stress checks.

    Parameters
    ----------
    t_c : float
        Dry-bulb air temperature, degrees Celsius.

    Returns
    -------
    float
        Saturation vapor pressure, Pa.
    """
    if t_c >= 0.0:
        # Buck (1996), over water, hPa -> Pa
        es_hpa = 6.1121 * math.exp((18.678 - t_c / 234.5) * (t_c / (257.14 + t_c)))
    else:
        # Buck (1996), over ice, hPa -> Pa
        es_hpa = 6.1115 * math.exp((23.036 - t_c / 333.7) * (t_c / (279.82 + t_c)))
    return es_hpa * 100.0


def dew_point_temperature(
    pw_pa: float, tolerance_c: float = 1e-6, max_iterations: int = 100
) -> float:
    """Dew point temperature for a given water vapor partial pressure.

    The dew point is, by definition, the temperature at which the
    saturation vapor pressure equals pw_pa. Rather than using a
    closed-form inversion (which only exists in simple form for the
    older Buck (1981) equation and would be inconsistent with the
    Buck (1996) two-term correlation used in
    `saturation_vapor_pressure`), this solves
    saturation_vapor_pressure(Tdp) == pw_pa numerically (bisection),
    guaranteeing exact round-trip consistency with the forward
    function [Buck1996].

    Parameters
    ----------
    pw_pa : float
        Partial pressure of water vapor, Pa (must be > 0).
    tolerance_c : float, optional
        Convergence tolerance, degrees Celsius.
    max_iterations : int, optional
        Maximum bisection iterations.

    Returns
    -------
    float
        Dew point temperature, degrees Celsius.
    """
    if pw_pa <= 0.0:
        raise ValueError("pw_pa must be positive")

    lo, hi = -80.0, 50.0
    f_lo = saturation_vapor_pressure(lo) - pw_pa
    f_hi = saturation_vapor_pressure(hi) - pw_pa
    if f_lo * f_hi > 0:
        raise ValueError(
            f"pw_pa={pw_pa} Pa is outside the range representable by "
            f"a dew point between {lo} C and {hi} C"
        )

    for _ in range(max_iterations):
        mid = (lo + hi) / 2.0
        f_mid = saturation_vapor_pressure(mid) - pw_pa
        if abs(f_mid) < 1e-6 or (hi - lo) / 2.0 < tolerance_c:
            return mid
        if f_lo * f_mid <= 0:
            hi = mid
        else:
            lo = mid
            f_lo = f_mid
    return (lo + hi) / 2.0


# ---------------------------------------------------------------------------
# Humidity ratio / relative humidity
# ---------------------------------------------------------------------------

def humidity_ratio_from_partial_pressure(pw_pa: float, p_pa: float) -> float:
    """Humidity ratio W from water vapor partial pressure and total pressure.

    W = 0.621945 * pw / (P - pw)  [ASHRAE17, Ch.1, Eq. 22]

    Parameters
    ----------
    pw_pa : float
        Partial pressure of water vapor, Pa.
    p_pa : float
        Total (barometric) pressure, Pa.

    Returns
    -------
    float
        Humidity ratio, kg water / kg dry air.
    """
    if pw_pa >= p_pa:
        raise ValueError("pw_pa must be less than total pressure p_pa")
    return WATER_TO_DRY_AIR_MOLAR_MASS_RATIO * pw_pa / (p_pa - pw_pa)


def humidity_ratio_from_relative_humidity(
    t_c: float, rh_pct: float, p_pa: float = STANDARD_ATM_PRESSURE_PA
) -> float:
    """Humidity ratio from dry-bulb temperature, relative humidity, pressure.

    RH is defined as pw / pws * 100 [ASHRAE17, Ch.1], combined with
    the humidity ratio relation (Eq. 22).

    Parameters
    ----------
    t_c : float
        Dry-bulb temperature, degrees Celsius.
    rh_pct : float
        Relative humidity, percent (0-100).
    p_pa : float, optional
        Total pressure, Pa. Defaults to standard sea-level pressure.

    Returns
    -------
    float
        Humidity ratio, kg water / kg dry air.
    """
    if not (0.0 <= rh_pct <= 100.0):
        raise ValueError("rh_pct must be between 0 and 100")
    pws = saturation_vapor_pressure(t_c)
    pw = (rh_pct / 100.0) * pws
    return humidity_ratio_from_partial_pressure(pw, p_pa)


def relative_humidity_from_humidity_ratio(
    t_c: float, w: float, p_pa: float = STANDARD_ATM_PRESSURE_PA
) -> float:
    """Relative humidity from dry-bulb temperature, humidity ratio, pressure.

    Inversion of Eq. 22 [ASHRAE17, Ch.1] followed by RH = pw / pws * 100.

    Parameters
    ----------
    t_c : float
        Dry-bulb temperature, degrees Celsius.
    w : float
        Humidity ratio, kg water / kg dry air.
    p_pa : float, optional
        Total pressure, Pa.

    Returns
    -------
    float
        Relative humidity, percent.
    """
    if w < 0.0:
        raise ValueError("w must be non-negative")
    pws = saturation_vapor_pressure(t_c)
    pw = w * p_pa / (WATER_TO_DRY_AIR_MOLAR_MASS_RATIO + w)
    return (pw / pws) * 100.0


# ---------------------------------------------------------------------------
# Wet bulb temperature
# ---------------------------------------------------------------------------

def humidity_ratio_from_wet_bulb(
    t_c: float, twb_c: float, p_pa: float = STANDARD_ATM_PRESSURE_PA
) -> float:
    """Humidity ratio from dry-bulb and wet-bulb temperature.

    Direct evaluation of the ASHRAE psychrometric wet-bulb relation
    [ASHRAE17, Ch.1, Eq. 35, SI form], solved for W (no iteration
    needed in this direction -- `wet_bulb_temperature` uses this same
    relation but iterates because it solves for Twb instead):

        W = ((2501 - 2.326*Twb)*Ws(Twb) - 1.006*(T - Twb))
            / (2501 + 1.86*T - 4.186*Twb)

    Useful for evaporative-cooling process calculations, which are
    commonly approximated as following a line of constant wet-bulb
    temperature (adiabatic saturation) on the psychrometric chart: if
    you know a process's wet-bulb temperature stays fixed while dry-
    bulb temperature drops (e.g. air passing through a wetted cooling
    pad), this recovers the resulting humidity ratio at the new dry-
    bulb temperature.

    Parameters
    ----------
    t_c : float
        Dry-bulb temperature, degrees Celsius.
    twb_c : float
        Wet-bulb temperature, degrees Celsius.
    p_pa : float, optional
        Total pressure, Pa.

    Returns
    -------
    float
        Humidity ratio, kg water / kg dry air.
    """
    pws_wb = saturation_vapor_pressure(twb_c)
    ws_wb = humidity_ratio_from_partial_pressure(pws_wb, p_pa)
    return (
        (2501.0 - 2.326 * twb_c) * ws_wb - 1.006 * (t_c - twb_c)
    ) / (2501.0 + 1.86 * t_c - 4.186 * twb_c)


def wet_bulb_temperature(
    t_c: float,
    w: float,
    p_pa: float = STANDARD_ATM_PRESSURE_PA,
    tolerance_c: float = 1e-5,
    max_iterations: int = 100,
) -> float:
    """Thermodynamic wet-bulb temperature via the ASHRAE energy balance.

    Solves iteratively (bisection) for Twb in the ASHRAE psychrometric
    wet-bulb relation [ASHRAE17, Ch.1, Eq. 35, SI form]:

        W = ((2501 - 2.326*Twb)*Ws(Twb) - 1.006*(T - Twb))
            / (2501 + 1.86*T - 4.186*Twb)

    where Ws(Twb) is the saturation humidity ratio at Twb and the
    system pressure P (Eq. 22 applied at saturation).

    Parameters
    ----------
    t_c : float
        Dry-bulb temperature, degrees Celsius.
    w : float
        Humidity ratio, kg water / kg dry air.
    p_pa : float, optional
        Total pressure, Pa.
    tolerance_c : float, optional
        Convergence tolerance on Twb, degrees Celsius.
    max_iterations : int, optional
        Maximum bisection iterations.

    Returns
    -------
    float
        Thermodynamic wet-bulb temperature, degrees Celsius.
    """

    def w_residual(twb_c: float) -> float:
        return humidity_ratio_from_wet_bulb(t_c, twb_c, p_pa) - w

    # Wet bulb is bounded between dew point and dry-bulb temperature.
    pw = w * p_pa / (WATER_TO_DRY_AIR_MOLAR_MASS_RATIO + w)
    lo = dew_point_temperature(pw) if pw > 0 else -50.0
    hi = t_c

    if hi - lo < tolerance_c:
        return hi

    f_lo = w_residual(lo)
    f_hi = w_residual(hi)
    if f_lo * f_hi > 0:
        # Numerical edge case (e.g. near-zero humidity ratio); fall back
        # to a wider bracket rather than silently returning a bad value.
        lo = lo - 5.0
        f_lo = w_residual(lo)
        if f_lo * f_hi > 0:
            raise RuntimeError(
                "wet_bulb_temperature: could not bracket a root; "
                "check inputs (t_c=%.3f, w=%.6f, p_pa=%.1f)" % (t_c, w, p_pa)
            )

    for _ in range(max_iterations):
        mid = (lo + hi) / 2.0
        f_mid = w_residual(mid)
        if abs(f_mid) < 1e-9 or (hi - lo) / 2.0 < tolerance_c:
            return mid
        if f_lo * f_mid <= 0:
            hi = mid
            f_hi = f_mid
        else:
            lo = mid
            f_lo = f_mid
    return (lo + hi) / 2.0


# ---------------------------------------------------------------------------
# Enthalpy, specific volume, density
# ---------------------------------------------------------------------------

def enthalpy(t_c: float, w: float) -> float:
    """Specific enthalpy of moist air, kJ per kg of dry air.

    h = 1.006*t + W*(2501 + 1.86*t)  [ASHRAE17, Ch.1, Eq. 32, SI form]

    Parameters
    ----------
    t_c : float
        Dry-bulb temperature, degrees Celsius.
    w : float
        Humidity ratio, kg water / kg dry air.

    Returns
    -------
    float
        Specific enthalpy, kJ / kg dry air.
    """
    return 1.006 * t_c + w * (2501.0 + 1.86 * t_c)


def specific_volume(t_c: float, w: float, p_pa: float = STANDARD_ATM_PRESSURE_PA) -> float:
    """Specific volume of moist air, m^3 per kg of dry air.

    v = R_da * T * (1 + 1.6078*W) / P  [ASHRAE17, Ch.1, Eq. 28, SI form]

    Parameters
    ----------
    t_c : float
        Dry-bulb temperature, degrees Celsius.
    w : float
        Humidity ratio, kg water / kg dry air.
    p_pa : float, optional
        Total pressure, Pa.

    Returns
    -------
    float
        Specific volume, m^3 / kg dry air.
    """
    t_k = c_to_k(t_c)
    return R_DRY_AIR * t_k * (1.0 + 1.6078 * w) / p_pa


def moist_air_density(t_c: float, w: float, p_pa: float = STANDARD_ATM_PRESSURE_PA) -> float:
    """Density of moist air, kg per m^3 of total (moist) volume.

    Derived from specific volume: rho = (1 + W) / v, with v from
    Eq. 28 [ASHRAE17, Ch.1].

    Parameters
    ----------
    t_c : float
        Dry-bulb temperature, degrees Celsius.
    w : float
        Humidity ratio, kg water / kg dry air.
    p_pa : float, optional
        Total pressure, Pa.

    Returns
    -------
    float
        Moist air density, kg / m^3.
    """
    v = specific_volume(t_c, w, p_pa)
    return (1.0 + w) / v


# ---------------------------------------------------------------------------
# Convenience: full state from (T, RH, P)
# ---------------------------------------------------------------------------

class PsychrometricState:
    """A fully resolved moist-air state, computed from dry-bulb
    temperature, relative humidity, and total pressure.

    All derived quantities are computed via the cited ASHRAE/Buck
    equations in this module; see individual function docstrings for
    references.
    """

    __slots__ = (
        "t_c",
        "rh_pct",
        "p_pa",
        "pws_pa",
        "pw_pa",
        "w",
        "dew_point_c",
        "wet_bulb_c",
        "enthalpy_kj_per_kg",
        "specific_volume_m3_per_kg",
        "density_kg_per_m3",
    )

    def __init__(self, t_c: float, rh_pct: float, p_pa: float = STANDARD_ATM_PRESSURE_PA):
        self.t_c = t_c
        self.rh_pct = rh_pct
        self.p_pa = p_pa

        self.pws_pa = saturation_vapor_pressure(t_c)
        self.pw_pa = (rh_pct / 100.0) * self.pws_pa
        self.w = humidity_ratio_from_partial_pressure(self.pw_pa, p_pa)
        self.dew_point_c = dew_point_temperature(self.pw_pa) if self.pw_pa > 0 else float("-inf")
        self.wet_bulb_c = wet_bulb_temperature(t_c, self.w, p_pa)
        self.enthalpy_kj_per_kg = enthalpy(t_c, self.w)
        self.specific_volume_m3_per_kg = specific_volume(t_c, self.w, p_pa)
        self.density_kg_per_m3 = moist_air_density(t_c, self.w, p_pa)

    def __repr__(self) -> str:
        return (
            f"PsychrometricState(t_c={self.t_c:.2f}, rh_pct={self.rh_pct:.1f}, "
            f"w={self.w:.5f}, twb_c={self.wet_bulb_c:.2f}, "
            f"tdp_c={self.dew_point_c:.2f}, h_kj_kg={self.enthalpy_kj_per_kg:.2f}, "
            f"v_m3_kg={self.specific_volume_m3_per_kg:.4f}, "
            f"rho_kg_m3={self.density_kg_per_m3:.3f})"
        )
