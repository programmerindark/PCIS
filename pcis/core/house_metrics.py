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

#: EU 2007/43/EC stocking-density limits, kg/m².
DENSITY_LIMIT_DEFAULT = 33.0
DENSITY_LIMIT_DEROGATION = 39.0
DENSITY_LIMIT_MAX = 42.0

#: Common operating guideline ceiling for in-house CO2, ppm.
CO2_GUIDELINE_PPM = 3000.0


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
