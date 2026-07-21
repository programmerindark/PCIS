"""Bird thermal comfort: target temperature, heat/cold stress indices,
and a composite Bird Comfort Index.

References
----------
[AviagenPocketGuide]  Aviagen, "Ross Broiler Pocket Guide" (Ross
    Broiler management handbook series). Table: "Principles of how
    optimum dry bulb temperatures for broilers may change at varying
    RH", giving target dry-bulb temperature (C) as a function of live
    body weight (g) and relative humidity (40/50/60/70%), based on a
    formula from Dr. Malcolm Mitchell (Scotland's Rural College).
    Also source of the CO2 (<3000 ppm ideal, >3500 ppm causes
    ascites), CO (<10 ppm ideal, >50 ppm affects health), and post-
    brooding humidity (50-60% ideal) guidance used below.
    https://aviagen.com/assets/Tech_Center/Ross_Broiler/Aviagen-ROSS-Broiler-PocketGuide-EN.pdf
    Retrieved 2026-07-20.

[TaoXin2003]  Tao, X., and H. Xin (2003), "Acute synergistic effects
    of air temperature, humidity, and velocity on homeostasis of
    market-size broilers", Transactions of the ASAE, 46(2):491-500.
    Source of the broiler temperature-humidity index
    THI = 0.85*Tdb + 0.15*Twb (weighting coefficients for broilers
    specifically, distinct from the dairy-cattle THI most commonly
    seen in general references).

[Marai2001]  Marai, I.F.M., et al. (2001), as reproduced/applied to
    broilers in Omomowo, O.O., and F.R. Falayi (2018), "Temperature-
    humidity index and thermal comfort of broilers in humid tropics",
    Agricultural Engineering International: CIGR Journal, 23(3),
    101-110. THI = Tdb - {(0.31 - 0.31*RH)*(Tdb - 14.4)}, RH as a
    fraction. Provided as an alternative THI formula that does not
    require a wet-bulb measurement.
    https://cigrjournal.org/index.php/Ejounral/article/download/6425/3677/34415

[Duduyemi2012]  Duduyemi, O.A., and S.O. Oseni (2012), "Modelling Heat
    Stress Characteristics on The Layers Performance Traits in South
    Western Nigeria" (conference poster, Tropentag 2012), as cited
    secondhand in [Omomowo2021] above, for THI stress-band thresholds:
    <26 comfort, 26-29 heat stress, >29 severe heat stress. NOTE: I
    have not read this source directly -- it is cited via the
    peer-reviewed [Omomowo2021] paper, which is itself a secondary
    citation. Treat these specific band edges as indicative, not as
    strongly validated as the Aviagen/Tao-and-Xin numbers above.

A note on relative humidity above 70% (or below 40%)
------------------------------------------------------
The [AviagenPocketGuide] target-temperature table is only tabulated
for RH 40-70%. Real broiler houses do go above that (farm operators
report indoor RH reaching 80% in humid weather), and refusing to
produce a number there previously made `target_temperature` crash the
whole recommendation. I searched for a wider-range Aviagen or
Mitchell-model source (the underlying "theoretical model" behind the
table is described in Zahoor, Mitchell et al. 2015, British Poultry
Science 57(1):134-141, but that paper's full method text was not
extractable in this session) and did not find one that publishes a
target temperature for RH>70% or RH<40%. Rather than crash, this
module now clamps the RH used for the table lookup to
[AVIAGEN_TARGET_TEMP_RH_MIN, AVIAGEN_TARGET_TEMP_RH_MAX] and sets
`ComfortAssessment.target_temp_rh_clamped = True` whenever the real
input RH fell outside that band, so callers can flag it rather than
silently trust the number.

Two things make this a defensible, non-dangerous fallback rather than
a guess dressed up as data:
1. Clamping high RH (e.g. 80%) down to the 70% column UNDERSTATES how
   much cooling is really needed (higher humidity impairs evaporative
   heat loss, so the true target temperature at 80% RH is lower than
   at 70%) -- so this is flagged, not treated as precise.
2. The THI metrics (`thi_tao_xin`, `thi_marai`) used alongside the
   target-temperature deviation in `bird_comfort_index` are NOT
   table-limited -- they are closed-form formulas valid at any RH, and
   `bird_comfort_index` already takes the *minimum* of the two
   sub-scores ("weakest dimension governs"). So even when the
   temperature-deviation sub-score is optimistic due to clamping, a
   genuinely dangerous high-RH/high-heat condition still gets caught
   by the (unrestricted) THI sub-score dragging the composite index
   down. Clamping the table lookup does not disable the app's ability
   to detect high-humidity heat stress -- it only means the specific
   "target temperature" number shown is a flagged floor, not a
   validated figure.

A note on the "Bird Comfort Index"
-----------------------------------
The composite `bird_comfort_index` function in this module combines
the temperature-deviation and THI metrics above into a single 0-100
score. **This composite index is PCIS's own synthesis, not a
published or validated instrument.** Each input metric is
individually cited (see above); the scoring constants used to combine
them (`TEMP_DEVIATION_TOLERANCE_C`, the point penalties per degree,
the THI stress-band penalties) are engineering judgment calls, not
literature values, and are declared as named module constants so they
are easy to find, question, and recalibrate. Do not treat the numeric
output as validated against real bird behavior or performance data --
that calibration is exactly what Stage 3 (validation) of this project
is for.
"""

from __future__ import annotations

from dataclasses import dataclass


# ---------------------------------------------------------------------------
# Aviagen target dry-bulb temperature table [AviagenPocketGuide]
# ---------------------------------------------------------------------------

#: Body weight (kg) -> {RH% : target dry-bulb temp, C}, transcribed
#: exactly from the Ross Broiler Pocket Guide table. The ">1530 g" row
#: is treated as the flat asymptote for any weight at or above 1.53 kg.
_AVIAGEN_TARGET_TEMP_TABLE: list[tuple[float, dict[int, float]]] = [
    (0.044, {40: 36.0, 50: 33.2, 60: 30.8, 70: 29.2}),
    (0.100, {40: 33.7, 50: 31.2, 60: 28.9, 70: 27.3}),
    (0.180, {40: 32.5, 50: 29.9, 60: 27.7, 70: 26.0}),
    (0.290, {40: 31.3, 50: 28.6, 60: 26.7, 70: 25.0}),
    (0.425, {40: 30.2, 50: 27.8, 60: 25.7, 70: 24.0}),
    (0.590, {40: 29.0, 50: 26.8, 60: 24.8, 70: 23.0}),
    (0.790, {40: 27.7, 50: 25.5, 60: 23.6, 70: 21.9}),
    (1.015, {40: 26.9, 50: 24.7, 60: 22.7, 70: 21.3}),
    (1.260, {40: 25.7, 50: 23.5, 60: 21.7, 70: 20.2}),
    (1.530, {40: 24.8, 50: 22.7, 60: 20.7, 70: 19.3}),
]

_AVIAGEN_TARGET_TEMP_RH_COLUMNS = (40, 50, 60, 70)

#: Public tested-range bounds for the RH columns above, so callers
#: (e.g. `recommendation_engine.recommend`, the GUI) can check whether
#: a given RH will be clamped before/after calling `target_temperature`
#: and flag it accordingly -- see the module docstring note on RH
#: above 70% / below 40%.
AVIAGEN_TARGET_TEMP_RH_MIN = float(_AVIAGEN_TARGET_TEMP_RH_COLUMNS[0])
AVIAGEN_TARGET_TEMP_RH_MAX = float(_AVIAGEN_TARGET_TEMP_RH_COLUMNS[-1])


def target_temperature_rh_is_clamped(rh_pct: float) -> bool:
    """True if `rh_pct` falls outside the Aviagen table's tested RH
    range [40, 70] and would be clamped by `target_temperature`.
    """
    return rh_pct < AVIAGEN_TARGET_TEMP_RH_MIN or rh_pct > AVIAGEN_TARGET_TEMP_RH_MAX

#: Air-quality thresholds [AviagenPocketGuide]
AVIAGEN_CO2_IDEAL_MAX_PPM = 3000.0
AVIAGEN_CO2_ASCITES_RISK_PPM = 3500.0
AVIAGEN_CO_IDEAL_MAX_PPM = 10.0
AVIAGEN_CO_HEALTH_EFFECT_PPM = 50.0
AVIAGEN_POST_BROODING_RH_IDEAL_RANGE_PCT = (50.0, 60.0)


def target_temperature(body_weight_kg: float, rh_pct: float) -> float:
    """Ideal dry-bulb temperature for a bird of given weight and RH, C.

    Bilinear interpolation on the [AviagenPocketGuide] table (body
    weight rows x RH columns), based on a formula from Dr. Malcolm
    Mitchell (Scotland's Rural College). For weight at or above the
    table's top row (1.53 kg), the top row's values are used directly
    (the guide labels this row ">1530 g", i.e. a flat asymptote, not
    a bound to refuse).

    Parameters
    ----------
    body_weight_kg : float
        Live body weight, kg. Below the table's minimum (0.044 kg)
        raises -- extrapolating below day-old chick weight is not
        supported.
    rh_pct : float
        Relative humidity, percent, 0-100. Values outside the table's
        tested range [40, 70] are CLAMPED to the nearest edge (40 or
        70) rather than raising -- see the module docstring note on
        RH above 70% / below 40% for why this is flagged rather than
        silently trusted. Use `target_temperature_rh_is_clamped` to
        check whether a given call will be clamped, and
        `bird_comfort_index`'s `target_temp_rh_clamped` field for the
        same signal on a full comfort assessment.

    Returns
    -------
    float
        Target dry-bulb temperature, degrees Celsius.
    """
    if rh_pct < 0.0 or rh_pct > 100.0:
        raise ValueError(f"rh_pct={rh_pct} is not a valid relative humidity (must be 0-100)")
    rh_pct = max(AVIAGEN_TARGET_TEMP_RH_MIN, min(AVIAGEN_TARGET_TEMP_RH_MAX, rh_pct))
    min_weight = _AVIAGEN_TARGET_TEMP_TABLE[0][0]
    if body_weight_kg < min_weight:
        raise ValueError(
            f"body_weight_kg={body_weight_kg} is below the Aviagen "
            f"table's minimum ({min_weight} kg, ~day-old chick); "
            "refusing to extrapolate"
        )

    # Interpolate across RH first, at each of the two bracketing
    # weight rows, then interpolate across weight.
    def rh_interp(row: dict[int, float]) -> float:
        cols = _AVIAGEN_TARGET_TEMP_RH_COLUMNS
        for c0, c1 in zip(cols, cols[1:]):
            if c0 <= rh_pct <= c1:
                if c1 == c0:
                    return row[c0]
                frac = (rh_pct - c0) / (c1 - c0)
                return row[c0] + frac * (row[c1] - row[c0])
        return row[cols[-1]]

    max_weight = _AVIAGEN_TARGET_TEMP_TABLE[-1][0]
    if body_weight_kg >= max_weight:
        return rh_interp(_AVIAGEN_TARGET_TEMP_TABLE[-1][1])

    for (w0, row0), (w1, row1) in zip(_AVIAGEN_TARGET_TEMP_TABLE, _AVIAGEN_TARGET_TEMP_TABLE[1:]):
        if w0 <= body_weight_kg <= w1:
            t0 = rh_interp(row0)
            t1 = rh_interp(row1)
            if w1 == w0:
                return t0
            frac = (body_weight_kg - w0) / (w1 - w0)
            return t0 + frac * (t1 - t0)

    # Unreachable given the checks above, but keep a safe fallback.
    return rh_interp(_AVIAGEN_TARGET_TEMP_TABLE[-1][1])


def temperature_deviation(actual_t_c: float, body_weight_kg: float, rh_pct: float) -> float:
    """Actual temperature minus target temperature, C.

    Positive = warmer than ideal (heat-stress direction); negative =
    cooler than ideal (cold-stress direction).
    """
    return actual_t_c - target_temperature(body_weight_kg, rh_pct)


# ---------------------------------------------------------------------------
# Temperature-humidity index (THI)
# ---------------------------------------------------------------------------

def thi_tao_xin(t_db_c: float, t_wb_c: float) -> float:
    """Broiler temperature-humidity index [TaoXin2003].

    THI = 0.85*Tdb + 0.15*Twb

    Parameters
    ----------
    t_db_c : float
        Dry-bulb temperature, degrees Celsius.
    t_wb_c : float
        Wet-bulb temperature, degrees Celsius (e.g. from
        `pcis.core.psychrometrics.wet_bulb_temperature`).

    Returns
    -------
    float
        THI, degrees Celsius (same units as input temperatures).
    """
    return 0.85 * t_db_c + 0.15 * t_wb_c


def thi_marai(t_db_c: float, rh_pct: float) -> float:
    """Alternative broiler THI not requiring wet-bulb temperature
    [Marai2001, via Omomowo2021].

    THI = Tdb - {(0.31 - 0.31*RH)*(Tdb - 14.4)}, RH as a fraction
    (0-1).

    Parameters
    ----------
    t_db_c : float
        Dry-bulb temperature, degrees Celsius.
    rh_pct : float
        Relative humidity, percent (0-100).

    Returns
    -------
    float
        THI, degrees Celsius.
    """
    rh_fraction = rh_pct / 100.0
    return t_db_c - ((0.31 - 0.31 * rh_fraction) * (t_db_c - 14.4))


#: THI stress-band thresholds [Duduyemi2012, via Omomowo2021] -- see
#: module docstring caveat on this being a secondhand citation.
THI_COMFORT_MAX = 26.0
THI_HEAT_STRESS_MAX = 29.0


def thi_stress_classification(thi: float) -> str:
    """Classify a THI value into a stress band [Duduyemi2012].

    Returns "comfort" (THI < 26), "heat_stress" (26 <= THI <= 29), or
    "severe_heat_stress" (THI > 29).
    """
    if thi < THI_COMFORT_MAX:
        return "comfort"
    if thi <= THI_HEAT_STRESS_MAX:
        return "heat_stress"
    return "severe_heat_stress"


# ---------------------------------------------------------------------------
# Composite Bird Comfort Index (PCIS synthesis -- see module docstring)
# ---------------------------------------------------------------------------

#: Degrees C of deviation from target temperature tolerated before any
#: penalty is applied. PCIS engineering judgment, not a literature
#: value -- see module docstring.
TEMP_DEVIATION_TOLERANCE_C = 1.0

#: Points lost per degree C of deviation beyond the tolerance band.
#: PCIS engineering judgment -- see module docstring.
TEMP_DEVIATION_PENALTY_PER_C = 15.0

#: Points lost for THI stress bands. PCIS engineering judgment -- see
#: module docstring.
THI_PENALTY_HEAT_STRESS = 15.0
THI_PENALTY_SEVERE_HEAT_STRESS = 35.0


@dataclass(frozen=True)
class ComfortAssessment:
    """A full thermal-comfort assessment at one point in time.

    target_temp_c : float
        Ideal dry-bulb temperature for this bird weight/RH
        [AviagenPocketGuide].
    deviation_c : float
        actual - target, C (positive = too hot, negative = too cold).
    thi : float
        Temperature-humidity index [TaoXin2003].
    thi_class : str
        "comfort" / "heat_stress" / "severe_heat_stress"
        [Duduyemi2012].
    comfort_index : float
        Composite 0-100 score. See module docstring: this is a PCIS
        synthesis, not a validated published index.
    target_temp_rh_clamped : bool
        True if `rh_pct` fell outside the Aviagen table's tested [40,
        70] range, meaning `target_temp_c`/`deviation_c` were computed
        against a clamped RH rather than the real value -- see the
        module docstring note on RH above 70% / below 40%. The THI
        component (`thi`, `thi_class`) is NOT affected by this, since
        those formulas have no table range restriction.
    """

    t_c: float
    rh_pct: float
    body_weight_kg: float
    target_temp_c: float
    deviation_c: float
    thi: float
    thi_class: str
    comfort_index: float
    target_temp_rh_clamped: bool = False


def bird_comfort_index(
    t_c: float,
    t_wb_c: float,
    rh_pct: float,
    body_weight_kg: float,
) -> ComfortAssessment:
    """Composite thermal comfort assessment for one bird weight/climate
    state.

    See module docstring -- this combines two individually-cited
    metrics (target-temperature deviation, THI) using PCIS's own
    "weakest dimension governs" scoring logic (the overall score is
    the minimum of the two component sub-scores, not an average) --
    this reflects the fact that a bird suffering on one axis is not
    "comforted" by being fine on the other. The specific penalty
    constants are named module-level constants, not published values.

    Parameters
    ----------
    t_c : float
        Dry-bulb air temperature, degrees Celsius.
    t_wb_c : float
        Wet-bulb temperature, degrees Celsius (for THI; see
        `pcis.core.psychrometrics.wet_bulb_temperature`).
    rh_pct : float
        Relative humidity, percent.
    body_weight_kg : float
        Live body weight per bird, kg.

    Returns
    -------
    ComfortAssessment
        Full breakdown plus the composite 0-100 comfort_index.
    """
    target_c = target_temperature(body_weight_kg, rh_pct)
    deviation = t_c - target_c
    thi = thi_tao_xin(t_c, t_wb_c)
    thi_class = thi_stress_classification(thi)

    excess_deviation = max(0.0, abs(deviation) - TEMP_DEVIATION_TOLERANCE_C)
    temp_score = max(0.0, 100.0 - TEMP_DEVIATION_PENALTY_PER_C * excess_deviation)

    thi_penalty = {
        "comfort": 0.0,
        "heat_stress": THI_PENALTY_HEAT_STRESS,
        "severe_heat_stress": THI_PENALTY_SEVERE_HEAT_STRESS,
    }[thi_class]
    thi_score = max(0.0, 100.0 - thi_penalty)

    composite = min(temp_score, thi_score)

    return ComfortAssessment(
        t_c=t_c,
        rh_pct=rh_pct,
        body_weight_kg=body_weight_kg,
        target_temp_c=target_c,
        deviation_c=deviation,
        thi=thi,
        thi_class=thi_class,
        comfort_index=composite,
        target_temp_rh_clamped=target_temperature_rh_is_clamped(rh_pct),
    )
