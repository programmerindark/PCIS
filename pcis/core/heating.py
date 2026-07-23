"""Supplemental heating requirement for cold-weather / brooding.

The rest of PCIS answers "how do I get heat OUT" (fans, pads). This
answers the opposite, which dominates the first two weeks of a
grow-out: a day-old chick wants ~33 C in a house that is losing heat
to a cold outside, and the birds themselves produce almost none. Then
you need heaters, not fans.

The physics is a steady-state energy balance on the house air, built
entirely from pieces already cited elsewhere in PCIS -- no new
constants:

    heat the house LOSES  = envelope conduction loss      (U.A.dT, heat_moisture_balance)
                          + heat to warm the minimum-       (ASHRAE Q = m.cp.dT, same
                            ventilation air from outdoor      convention as
                            up to the target indoor temp      ventilation_solver)

    heat the house GAINS  = bird sensible heat             (CIGR, bird_metabolism)

    heating deficit       = losses - gains

If the deficit is positive, heaters must supply it to hold the target
temperature; if it is zero or negative the birds (plus solar/envelope)
already keep the house warm and no heating is needed.

Two honest boundaries:

  * Minimum ventilation is NOT optional even in the cold -- birds still
    need fresh air, and that cold incoming air is often the LARGER part
    of the winter heat load, not the envelope. Leaving it out would
    badly under-state the heat needed, so it is included.

  * On/off *timing* needs the heater's capacity (kW), exactly as fan
    staging needs the fan curve. Given a capacity, this returns a duty
    fraction (what share of the time the heater must run). Without one,
    it still returns the heat DEFICIT in watts and the fact that
    heating is needed -- it just cannot say "run it N minutes in six".
"""

from __future__ import annotations

from dataclasses import dataclass

from pcis.core import psychrometrics as psy
from pcis.core.heat_moisture_balance import FlockLoad


@dataclass(frozen=True)
class HeatingRequirement:
    """Whether heaters are needed, and by how much.

    heating_needed : bool
        True when the house cannot hold the target temperature on bird
        heat alone -- i.e. losses exceed gains.
    heat_deficit_w : float
        Supplemental heat required to hold target, W. Zero when no
        heating is needed.
    envelope_loss_w : float
        Conductive loss through walls/ceiling at these conditions, W.
    ventilation_loss_w : float
        Heat to warm the minimum-ventilation air from outdoor to
        target indoor temperature, W.
    bird_sensible_heat_w : float
        Sensible heat the flock contributes, W (offsets the losses).
    heater_capacity_w : float | None
        Installed heater capacity supplied by the caller, W, or None.
    heater_duty_fraction : float | None
        Share of the time the heater must run to meet the deficit
        (deficit / capacity). None if no capacity was given. May exceed
        1.0 -- see `heater_undersized`.
    heater_undersized : bool
        True when the deficit exceeds the installed heater capacity, so
        even running continuously it cannot hold target. False when no
        capacity was given (nothing to judge against).
    """

    heating_needed: bool
    heat_deficit_w: float
    envelope_loss_w: float
    ventilation_loss_w: float
    bird_sensible_heat_w: float
    heater_capacity_w: float | None = None
    heater_duty_fraction: float | None = None
    heater_undersized: bool = False


def ventilation_heat_loss_w(
    airflow_m3_per_h: float,
    indoor_t_c: float,
    outdoor_t_c: float,
    outdoor_rh_pct: float,
    p_pa: float = psy.STANDARD_ATM_PRESSURE_PA,
) -> float:
    """Heat needed to warm incoming ventilation air from outdoor to
    indoor temperature, W.

    Same ASHRAE sensible-heat balance the cooling side uses
    (`ventilation_solver.required_airflow_for_sensible_heat`), run
    forwards: Q = m_dot_da * cp_moist * dT, with the incoming (outdoor)
    air's specific volume converting the volumetric rate to a dry-air
    mass flow. Returns 0 when outdoor is already at or above indoor
    (no heating of the incoming air is needed).
    """
    if airflow_m3_per_h <= 0:
        return 0.0
    dt = indoor_t_c - outdoor_t_c
    if dt <= 0:
        return 0.0

    w_out = psy.humidity_ratio_from_relative_humidity(outdoor_t_c, outdoor_rh_pct, p_pa)
    cp_moist_j_per_kgk = (1.006 + 1.86 * w_out) * 1000.0  # [ASHRAE17]
    v_specific = psy.specific_volume(outdoor_t_c, w_out, p_pa)  # m^3 per kg dry air

    m_dot_da_kg_per_s = (airflow_m3_per_h / 3600.0) / v_specific
    return m_dot_da_kg_per_s * cp_moist_j_per_kgk * dt


def heating_requirement(
    flock: FlockLoad,
    envelope_loss_w: float,
    min_ventilation_m3_per_h: float,
    indoor_t_c: float,
    outdoor_t_c: float,
    outdoor_rh_pct: float,
    heater_capacity_w: float | None = None,
    p_pa: float = psy.STANDARD_ATM_PRESSURE_PA,
) -> HeatingRequirement:
    """Compute the supplemental heat needed to hold the target indoor
    temperature, from the house energy balance.

    Parameters
    ----------
    flock : FlockLoad
        House-total bird loads (`heat_moisture_balance.flock_load`);
        its `sensible_heat_w` is the heat the birds contribute.
    envelope_loss_w : float
        Conductive envelope loss, W, from
        `heat_moisture_balance.total_envelope_conduction_loss`
        (positive = losing heat to a colder outside).
    min_ventilation_m3_per_h : float
        The minimum ventilation the house must run for air quality even
        in the cold (e.g. `ventilation_solver.minimum_ventilation_rate_
        aviagen(weight) * bird_count`). Warming this cold incoming air
        is part of the heat load.
    indoor_t_c, outdoor_t_c, outdoor_rh_pct : float
        Target indoor temperature and current outdoor conditions.
    heater_capacity_w : float, optional
        Installed heater output, W. If given, a duty fraction and an
        undersized flag are returned; if omitted, only the deficit.

    Returns
    -------
    HeatingRequirement
    """
    vent_loss = ventilation_heat_loss_w(
        min_ventilation_m3_per_h, indoor_t_c, outdoor_t_c, outdoor_rh_pct, p_pa
    )
    total_loss = envelope_loss_w + vent_loss
    deficit = total_loss - flock.sensible_heat_w

    if deficit <= 0.0:
        return HeatingRequirement(
            heating_needed=False,
            heat_deficit_w=0.0,
            envelope_loss_w=envelope_loss_w,
            ventilation_loss_w=vent_loss,
            bird_sensible_heat_w=flock.sensible_heat_w,
            heater_capacity_w=heater_capacity_w,
            heater_duty_fraction=0.0 if heater_capacity_w else None,
            heater_undersized=False,
        )

    duty = None
    undersized = False
    if heater_capacity_w is not None and heater_capacity_w > 0:
        duty = deficit / heater_capacity_w
        undersized = duty > 1.0

    return HeatingRequirement(
        heating_needed=True,
        heat_deficit_w=deficit,
        envelope_loss_w=envelope_loss_w,
        ventilation_loss_w=vent_loss,
        bird_sensible_heat_w=flock.sensible_heat_w,
        heater_capacity_w=heater_capacity_w,
        heater_duty_fraction=duty,
        heater_undersized=undersized,
    )
