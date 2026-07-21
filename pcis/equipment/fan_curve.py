"""Fan performance curves (airflow vs. static pressure).

STATUS: Big Dutchman ~130 cm (51", "50-inch class") wall/gable fans
loaded from an official Big Dutchman datasheet (see [BigDutchman2019]
below). No SKOV data yet.

Every FanCurve instance must carry its data provenance (manufacturer,
model number, source document, and date retrieved) so that anyone
reviewing the equipment database can trace a number back to its
datasheet.

A naming note (read before using the "Multifan 130" records)
---------------------------------------------------------------
The user identified their fans as "Big Dutchman Multifan 130, 50-inch
box fans." Big Dutchman's own catalog does not use the name
"Multifan 130" -- it brands its 130 cm impeller wall/gable fans as
the "AirMaster V130" (no cone) and "AirMaster VC130" (with cone)
series. "Multifan" is the brand name used by Vostermans Ventilation,
who I found (via a Vostermans/DirectIndustry product page) sells a
"Multifan 130" with near-identical headline specs (45,600 m3/h @ 0 Pa,
36.9 W/1000 m3/h) to Big Dutchman's AirMaster V130/VC130 (130 cm =
~51.2 in diameter, matching "50-inch box fan"). Big Dutchman very
likely sources this fan family from Vostermans and rebrands it, or
sells a closely related product line -- but I could not confirm the
two names refer to the byte-for-byte identical model, and the
Vostermans page I reached did not expose its numeric performance
table (image-based, not machine-readable text).

Given that, the records below are loaded from Big Dutchman's own
published datasheet under the AirMaster V130/VC130 names, not
"Multifan 130." If your Viper Touch simulator shows a specific
"Multifan 130" model code (e.g. from the fan's nameplate or the
simulator's equipment list), share it and I will verify whether it
matches one of these records exactly or needs its own entry.

References
----------
[BigDutchman2019]  Big Dutchman, "Wall Fans -- High air performance
    and low energy consumption", en 9/2019 edition, Big Dutchman Inc.
    (USA). Table "Technical data of the AirMaster V130, VC130, V140
    and VC140 fans: 3~400V, 50Hz" and the accompanying airflow/
    pressure/power table.
    https://www.bigdutchmanusa.com/wp-content/uploads/2021/09/Wall-fans_en_2019.pdf
    Retrieved 2026-07-20.

Absolute power at each point (power_w) is not printed directly in the
source table -- it publishes "spec. fan power" normalized as
W per 1000 m3/h. Absolute power_w values below are computed as
spec_power * (airflow_m3_per_h / 1000), which is arithmetically
equivalent to the source's own normalization and does not introduce
a new engineering assumption.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class FanCurve:
    """A single fan's airflow-vs-static-pressure performance curve.

    Attributes
    ----------
    manufacturer : str
        e.g. "Big Dutchman", "SKOV", "Munters".
    model : str
        Manufacturer's model/part number.
    diameter_m : float
        Fan blade diameter, meters.
    static_pressure_pa : list[float]
        Static pressure test points, Pa, ascending.
    airflow_m3_per_h : list[float]
        Airflow at each static pressure point, m^3/h. Must be the same
        length as static_pressure_pa.
    power_w : list[float]
        Electrical power draw at each point, W (if available).
    source : str
        Full citation of where this data came from (datasheet name,
        revision, URL or document ID, and date retrieved). Required --
        a FanCurve without a source should not be trusted downstream.
    """

    manufacturer: str
    model: str
    diameter_m: float
    static_pressure_pa: list[float]
    airflow_m3_per_h: list[float]
    source: str
    power_w: list[float] = field(default_factory=list)

    def __post_init__(self) -> None:
        if len(self.static_pressure_pa) != len(self.airflow_m3_per_h):
            raise ValueError(
                "static_pressure_pa and airflow_m3_per_h must have the "
                "same length"
            )
        if not self.source or not self.source.strip():
            raise ValueError(
                "FanCurve.source is required -- record the datasheet or "
                "test report this data came from"
            )

    def airflow_at_static_pressure(self, sp_pa: float) -> float:
        """Interpolate airflow at a given static pressure, m^3/h.

        Uses linear interpolation between the loaded test points.
        Raises if sp_pa falls outside the tested range rather than
        extrapolating silently.
        """
        pts = sorted(zip(self.static_pressure_pa, self.airflow_m3_per_h))
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        if sp_pa < xs[0] or sp_pa > xs[-1]:
            raise ValueError(
                f"{sp_pa} Pa is outside the tested static pressure range "
                f"[{xs[0]}, {xs[-1]}] for {self.manufacturer} {self.model}; "
                "refusing to extrapolate beyond measured data"
            )
        for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
            if x0 <= sp_pa <= x1:
                if x1 == x0:
                    return y0
                frac = (sp_pa - x0) / (x1 - x0)
                return y0 + frac * (y1 - y0)
        return ys[-1]


def _make_curve(model: str, diameter_m: float, points: list[tuple[float, float, float]]) -> FanCurve:
    """Build a FanCurve from (pressure_pa, airflow_m3h, spec_power_w_per_1000m3h) rows."""
    sp = [p[0] for p in points]
    flow = [p[1] for p in points]
    power = [p[2] * (p[1] / 1000.0) for p in points]
    return FanCurve(
        manufacturer="Big Dutchman",
        model=model,
        diameter_m=diameter_m,
        static_pressure_pa=sp,
        airflow_m3_per_h=flow,
        power_w=power,
        source=(
            "Big Dutchman, 'Wall Fans' catalog, en 9/2019 edition, "
            "table 'Technical data of the AirMaster V130, VC130, V140 "
            "and VC140 fans: 3~400V, 50Hz'. "
            "https://www.bigdutchmanusa.com/wp-content/uploads/2021/09/"
            "Wall-fans_en_2019.pdf ; retrieved 2026-07-20. "
            "NOTE: catalog brands this fan family 'AirMaster', not "
            "'Multifan' -- see module docstring for the naming "
            "discrepancy versus the user's 'Multifan 130' fans; "
            "diameter 130cm (~51in) matches the '50-inch box fan' "
            "description but the exact model code has not been "
            "confirmed against the Viper Touch simulator."
        ),
    )


# Big Dutchman AirMaster V130 / VC130 (130 cm / ~51in diameter) --
# see module docstring for the naming note relative to "Multifan 130".
# Pressure points are exactly as published (missing pressures in the
# source mean the motor could not sustain that pressure -- not
# omitted data).
FAN_CATALOG: list[FanCurve] = [
    _make_curve(
        "V130-3-1.0 PS (no cone, 1.0 HP motor)",
        1.30,
        [(0, 40400, 27.5), (20, 36100, 32.4), (30, 33100, 35.8), (40, 29900, 40.2)],
    ),
    _make_curve(
        "V130-3-1.5 PS (no cone, 1.5 HP motor)",
        1.30,
        [
            (0, 46700, 34.5),
            (20, 42600, 39.1),
            (30, 40700, 41.0),
            (40, 38300, 44.1),
            (60, 31900, 53.4),
        ],
    ),
    _make_curve(
        "VC130-3-1.0 PS (with cone, 1.0 HP motor)",
        1.30,
        [(0, 44500, 24.6), (20, 40400, 28.6), (30, 37800, 31.5), (40, 35400, 34.1)],
    ),
    _make_curve(
        "VC130-3-1.5 PS (with cone, 1.5 HP motor)",
        1.30,
        [
            (0, 50700, 30.7),
            (20, 47000, 34.8),
            (30, 45000, 37.0),
            (40, 42600, 40.1),
            (60, 37800, 46.1),
        ],
    ),
]
