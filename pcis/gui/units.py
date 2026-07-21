"""Unit conversion for the PCIS user interface.

Scope and intent
----------------
This module exists so the GUI can *display* values in whatever units
the operator thinks in, while the engineering core keeps working
entirely in SI. Nothing here changes a calculation: `pcis.core.*` is
metric end to end, conversions happen only at the widget boundary, and
every value stored in the database is stored in SI regardless of what
the user had selected on screen. That separation is deliberate -- a
unit bug that reached the solver would be far worse than one that only
mis-labels a spinbox.

Why the factors below are exact
-------------------------------
Most of these are definitional rather than measured, so they are
written out to full precision rather than rounded:

- 1 inch = 0.0254 m exactly (international yard and pound agreement,
  1959), hence 1 ft = 0.3048 m exactly.
- 1 lb = 0.45359237 kg exactly (same agreement).
- degF = degC * 9/5 + 32 exactly (definition).
- 1 CFM = 1 ft^3/min, so 1 CFM = 0.3048^3 * 60 m^3/h exactly.

The one figure that is a convention rather than a definition is the
inch of water column, because water density depends on temperature:

- INCH_WATER_TO_PA = 249.0889 Pa, the "inch of water at 4 degC (39.2
  degF)" convention. This is the value consistent with the pad
  pressure-drop figure already cited in
  `pcis.equipment.cooling_pad` (0.05 in. W.C. = 12.45 Pa). Note that
  the 60 degF convention gives 248.84 Pa instead -- a 0.1% difference,
  irrelevant at the precision of ventilation work, but recorded here
  so the choice is visible rather than silent.
"""

from __future__ import annotations

from dataclasses import dataclass

# --- Definitional constants ------------------------------------------------

FOOT_TO_METRE = 0.3048  # exact
POUND_TO_KILOGRAM = 0.45359237  # exact
INCH_WATER_TO_PA = 249.0889  # convention: water at 4 degC -- see docstring

SQFT_TO_SQM = FOOT_TO_METRE**2  # exact
CFM_TO_M3_PER_H = FOOT_TO_METRE**3 * 60.0  # exact


# --- Temperature -----------------------------------------------------------


def c_to_f(celsius: float) -> float:
    """Degrees Celsius to degrees Fahrenheit."""
    return celsius * 9.0 / 5.0 + 32.0


def f_to_c(fahrenheit: float) -> float:
    """Degrees Fahrenheit to degrees Celsius."""
    return (fahrenheit - 32.0) * 5.0 / 9.0


def delta_c_to_delta_f(delta_c: float) -> float:
    """Convert a temperature DIFFERENCE, not an absolute temperature.

    Kept separate from `c_to_f` because the 32-degree offset must not
    be applied to a difference. Mixing these up is the single most
    common unit bug in this domain: a 3 degC allowed temperature rise
    is 5.4 degF, not 37.4 degF.
    """
    return delta_c * 9.0 / 5.0


def delta_f_to_delta_c(delta_f: float) -> float:
    """Convert a temperature DIFFERENCE from Fahrenheit to Celsius."""
    return delta_f * 5.0 / 9.0


# --- Length / area ---------------------------------------------------------


def m_to_ft(metres: float) -> float:
    return metres / FOOT_TO_METRE


def ft_to_m(feet: float) -> float:
    return feet * FOOT_TO_METRE


def m2_to_sqft(square_metres: float) -> float:
    return square_metres / SQFT_TO_SQM


def sqft_to_m2(square_feet: float) -> float:
    return square_feet * SQFT_TO_SQM


# --- Mass ------------------------------------------------------------------


def kg_to_lb(kilograms: float) -> float:
    return kilograms / POUND_TO_KILOGRAM


def lb_to_kg(pounds: float) -> float:
    return pounds * POUND_TO_KILOGRAM


# --- Airflow ---------------------------------------------------------------


def m3ph_to_cfm(m3_per_hour: float) -> float:
    return m3_per_hour / CFM_TO_M3_PER_H


def cfm_to_m3ph(cfm: float) -> float:
    return cfm * CFM_TO_M3_PER_H


# --- Pressure --------------------------------------------------------------


def pa_to_inwc(pascals: float) -> float:
    return pascals / INCH_WATER_TO_PA


def inwc_to_pa(inches_water: float) -> float:
    return inches_water * INCH_WATER_TO_PA


# --- U-value ---------------------------------------------------------------
#
# W/(m^2*K) vs BTU/(h*ft^2*degF). 1 W = 3.412141633 BTU/h, and the
# area/temperature parts convert as above.

WATT_TO_BTU_PER_H = 3.412141633


def u_si_to_imperial(u_si: float) -> float:
    """W/(m^2*K) -> BTU/(h*ft^2*degF)."""
    return u_si * WATT_TO_BTU_PER_H * SQFT_TO_SQM / (9.0 / 5.0)


def u_imperial_to_si(u_imp: float) -> float:
    """BTU/(h*ft^2*degF) -> W/(m^2*K)."""
    return u_imp / (WATT_TO_BTU_PER_H * SQFT_TO_SQM / (9.0 / 5.0))


# --- Unit-system description ----------------------------------------------


@dataclass(frozen=True)
class UnitSystem:
    """Display units and conversions for one unit system.

    Each `*_from_si` / `*_to_si` pair converts a single quantity. The
    GUI calls `_from_si` when populating a widget and `_to_si` when
    reading one back, so the engineering core only ever sees SI.
    """

    name: str

    length_suffix: str
    area_suffix: str
    temp_suffix: str
    delta_temp_suffix: str
    mass_suffix: str
    airflow_suffix: str
    pressure_suffix: str
    u_value_suffix: str

    length_from_si: callable
    length_to_si: callable
    area_from_si: callable
    area_to_si: callable
    temp_from_si: callable
    temp_to_si: callable
    delta_temp_from_si: callable
    delta_temp_to_si: callable
    mass_from_si: callable
    mass_to_si: callable
    airflow_from_si: callable
    airflow_to_si: callable
    pressure_from_si: callable
    pressure_to_si: callable
    u_value_from_si: callable
    u_value_to_si: callable


def _identity(x: float) -> float:
    return x


METRIC = UnitSystem(
    name="Metric (SI)",
    length_suffix=" m",
    area_suffix=" m²",
    temp_suffix=" °C",
    delta_temp_suffix=" °C",
    mass_suffix=" kg",
    airflow_suffix=" m³/h",
    pressure_suffix=" Pa",
    u_value_suffix=" W/m²K",
    length_from_si=_identity, length_to_si=_identity,
    area_from_si=_identity, area_to_si=_identity,
    temp_from_si=_identity, temp_to_si=_identity,
    delta_temp_from_si=_identity, delta_temp_to_si=_identity,
    mass_from_si=_identity, mass_to_si=_identity,
    airflow_from_si=_identity, airflow_to_si=_identity,
    pressure_from_si=_identity, pressure_to_si=_identity,
    u_value_from_si=_identity, u_value_to_si=_identity,
)

IMPERIAL = UnitSystem(
    name="Imperial (US)",
    length_suffix=" ft",
    area_suffix=" ft²",
    temp_suffix=" °F",
    delta_temp_suffix=" °F",
    mass_suffix=" lb",
    airflow_suffix=" CFM",
    pressure_suffix=' in.WC',
    u_value_suffix=" BTU/h·ft²·°F",
    length_from_si=m_to_ft, length_to_si=ft_to_m,
    area_from_si=m2_to_sqft, area_to_si=sqft_to_m2,
    temp_from_si=c_to_f, temp_to_si=f_to_c,
    delta_temp_from_si=delta_c_to_delta_f, delta_temp_to_si=delta_f_to_delta_c,
    mass_from_si=kg_to_lb, mass_to_si=lb_to_kg,
    airflow_from_si=m3ph_to_cfm, airflow_to_si=cfm_to_m3ph,
    pressure_from_si=pa_to_inwc, pressure_to_si=inwc_to_pa,
    u_value_from_si=u_si_to_imperial, u_value_to_si=u_imperial_to_si,
)

#: Selectable systems, in the order the GUI dropdown should list them.
UNIT_SYSTEMS: list[UnitSystem] = [METRIC, IMPERIAL]
