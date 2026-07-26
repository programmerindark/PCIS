"""Operator-facing house metrics derived from the engine's own numbers.

Three readouts that need no new hardware, each grounded:

* **Stocking density (kg/m²)** — the welfare-regulated measure. EU
  Directive 2007/43/EC sets the maximum at **33 kg/m²**, rising to
  **39 kg/m²** where the producer meets extra documentation/housing
  conditions, and **42 kg/m²** where additional mortality/welfare
  criteria are also met. Birds/m² is a weaker proxy because it ignores
  bird size; kg/m² is what the limit is actually written in.
      [EU2007/43] Council Directive 2007/43/EC, Articles 3(2)-3(5).

* **Estimated indoor CO₂ (ppm)** — steady-state mass balance:
      indoor = outdoor + (CO₂ produced / ventilation rate) x 1e6
  with CO₂ production from the CIGR bird-metabolism model already in
  `bird_metabolism`/`heat_moisture_balance`. This is an ESTIMATE of the
  well-mixed average, not a sensor reading: real houses stratify and
  dead-spots run higher. Reported so an operator can sanity-check air
  quality; the common in-house guideline ceiling is 3000 ppm.

* **Air changes per hour (ACH)** — ventilation rate divided by house
  volume. A plain unit conversion, no new physics.
"""

from __future__ import annotations

from dataclasses import dataclass

from pcis.core import psychrometrics as psy

#: EU 2007/43/EC stocking-density limits, kg/m².
DENSITY_LIMIT_DEFAULT = 33.0
DENSITY_LIMIT_DEROGATION = 39.0
DENSITY_LIMIT_MAX = 42.0

#: Common operating guideline ceiling for in-house CO2, ppm.
CO2_GUIDELINE_PPM = 3000.0


@dataclass(frozen=True)
class PredictedHumidity:
    """Steady-state indoor humidity predicted from the moisture balance.

    indoor_rh_pct : float
        Predicted indoor relative humidity, % (capped at 100).
    indoor_humidity_ratio_g_per_kg : float
        Predicted indoor absolute humidity, g water / kg dry air.
    supply_humidity_ratio_g_per_kg : float
        The incoming air's absolute humidity, for comparison.
    moisture_added_g_per_kg : float
        How much water the birds add to each kg of air passing through.
    saturated : bool
        True when the balance predicts condensation (>= 100% RH) -- the
        house cannot hold this much moisture at this temperature.
    """

    indoor_rh_pct: float
    indoor_humidity_ratio_g_per_kg: float
    supply_humidity_ratio_g_per_kg: float
    moisture_added_g_per_kg: float
    saturated: bool
    note: str


def predict_indoor_humidity(
    *,
    indoor_t_c: float,
    supply_t_c: float,
    supply_rh_pct: float,
    moisture_load_kg_per_h: float,
    airflow_m3_per_h: float,
) -> PredictedHumidity | None:
    """Predict indoor RH from the steady-state moisture mass balance.

        W_indoor = W_supply + moisture_load / dry-air mass flow

    Every term already exists in PCIS: the moisture load is the CIGR
    flock figure from `heat_moisture_balance.flock_load`, and the
    psychrometric conversions are ASHRAE/Buck. This adds no new
    engineering -- it re-arranges the same balance the ventilation solver
    uses to SIZE fans, in order to REPORT the humidity that results.

    Useful in two ways: it gives a humidity figure on farms with no
    hygrometer, and where a measurement IS available it acts as a
    cross-check -- a measured RH well above prediction points at wet
    litter, leaking drinkers or air short-circuiting past the birds.

    Returns None when airflow is zero (nothing to balance against).
    """
    if airflow_m3_per_h <= 0:
        return None

    w_supply = psy.humidity_ratio_from_relative_humidity(supply_t_c, supply_rh_pct)
    # Dry-air mass flow: volumetric flow / specific volume of the supply air.
    v_specific = psy.specific_volume(supply_t_c, w_supply)
    m_dry_air_kg_per_h = airflow_m3_per_h / v_specific
    added = moisture_load_kg_per_h / m_dry_air_kg_per_h
    w_indoor = w_supply + added

    rh = psy.relative_humidity_from_humidity_ratio(indoor_t_c, w_indoor)
    saturated = rh >= 100.0
    rh = min(rh, 100.0)

    if saturated:
        note = (
            f"Moisture balance predicts saturation at {indoor_t_c:.1f}C — the birds add "
            f"{added * 1000:.1f} g/kg and the air cannot hold it. Expect condensation and "
            "wet litter; increase ventilation or house temperature."
        )
    else:
        note = (
            f"Predicted indoor {rh:.0f}% RH: incoming air at {w_supply * 1000:.1f} g/kg "
            f"plus {added * 1000:.1f} g/kg added by the birds. A measured value much "
            "higher than this suggests wet litter, drinker leaks or air bypassing the birds."
        )

    return PredictedHumidity(
        indoor_rh_pct=round(rh, 0),
        indoor_humidity_ratio_g_per_kg=round(w_indoor * 1000, 2),
        supply_humidity_ratio_g_per_kg=round(w_supply * 1000, 2),
        moisture_added_g_per_kg=round(added * 1000, 2),
        saturated=saturated,
        note=note,
    )


@dataclass(frozen=True)
class HouseMetrics:
    stocking_density_kg_m2: float
    density_limit_kg_m2: float
    density_pct_of_limit: float
    density_within_limit: bool
    estimated_co2_ppm: float | None
    co2_within_guideline: bool
    air_changes_per_hour: float | None
    airflow_per_bird_m3_h: float | None
    note: str


def assess(
    *,
    bird_count: int,
    body_weight_kg: float,
    floor_area_m2: float,
    house_volume_m3: float,
    delivered_airflow_m3_per_h: float | None,
    co2_production_m3_per_h: float | None,
    outdoor_co2_ppm: float = 420.0,
    density_limit_kg_m2: float = DENSITY_LIMIT_DEROGATION,
) -> HouseMetrics:
    """Compute the three metrics. All inputs come from the engine or the
    house record; nothing is invented here."""
    area = max(1e-6, floor_area_m2)
    density = bird_count * body_weight_kg / area
    pct = 100.0 * density / max(1e-6, density_limit_kg_m2)

    co2 = None
    if delivered_airflow_m3_per_h and delivered_airflow_m3_per_h > 0 and co2_production_m3_per_h is not None:
        co2 = outdoor_co2_ppm + (co2_production_m3_per_h / delivered_airflow_m3_per_h) * 1_000_000.0

    ach = None
    if delivered_airflow_m3_per_h and house_volume_m3 > 0:
        ach = delivered_airflow_m3_per_h / house_volume_m3

    per_bird = None
    if delivered_airflow_m3_per_h and bird_count > 0:
        per_bird = delivered_airflow_m3_per_h / bird_count

    within = density <= density_limit_kg_m2
    if not within:
        note = (
            f"Stocking density {density:.1f} kg/m² exceeds the {density_limit_kg_m2:.0f} kg/m² "
            "limit [EU 2007/43/EC] — reduce bird numbers or split the flock."
        )
    else:
        note = (
            f"Stocking density {density:.1f} of {density_limit_kg_m2:.0f} kg/m² "
            f"({pct:.0f}% of limit) [EU 2007/43/EC]."
        )

    return HouseMetrics(
        stocking_density_kg_m2=round(density, 1),
        density_limit_kg_m2=density_limit_kg_m2,
        density_pct_of_limit=round(pct, 0),
        density_within_limit=within,
        estimated_co2_ppm=round(co2, 0) if co2 is not None else None,
        co2_within_guideline=(co2 is None or co2 <= CO2_GUIDELINE_PPM),
        air_changes_per_hour=round(ach, 1) if ach is not None else None,
        airflow_per_bird_m3_h=round(per_bird, 2) if per_bird is not None else None,
        note=note,
    )
