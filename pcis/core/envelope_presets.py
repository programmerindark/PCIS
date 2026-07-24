"""Typical building-envelope U-values for broiler houses.

Why this exists: the app needs an envelope U-value (thermal
transmittance, W/m^2K) for every surface to compute conduction
loss/gain (Q = U.A.dT), but most operators do not know the U-value of
their walls or ceiling off the top of their head. This module gives a
small set of **named construction types with published, cited
U-values** so the operator can pick "insulated wall (R-13)" instead of
having to supply a number.

Honesty note (same rule as the rest of PCIS): these are NOT invented.
Each U-value is derived from a published insulation R-value
recommendation for poultry housing, converted to an SI assembly
U-value by a standard, cited method. Where a value is an approximation
(e.g. the combined surface air films) that is stated here rather than
hidden. If an operator knows their real U-value they should still type
it in -- these are defensible defaults, not a substitute for a measured
figure.

Method
------
Each preset starts from a nominal insulation R-value in US customary
units, ``R_IP`` [ft^2.F.h/Btu]. The whole-assembly resistance adds the
inside and outside surface air films, taken as ASHRAE standard values
[ASHRAE Fundamentals, surface conductances: inside still air
R ~= 0.68, outside 15 mph wind R ~= 0.17, so ~0.85 combined]:

    R_total_IP = R_IP + FILMS_IP                       (FILMS_IP = 0.85)

converted to SI with the exact factor 1 ft^2.F.h/Btu = 0.176110 m^2K/W:

    R_total_SI = R_total_IP * 0.176110
    U          = 1 / R_total_SI                        [W/m^2K]

The stored ``u_value`` on each preset is that result rounded to three
decimals (the rounding is disclosed, not silent). The one-line
derivation is kept on each preset in ``source`` so the number is
traceable end to end.

References
----------
[UGA-Fairchild] Fairchild, B.D., University of Georgia Cooperative
    Extension / UGA Poultry House Environmental Management. Recommended
    insulation levels for broiler houses: walls a minimum of R-7 (R-13
    where the house is artificially heated), ceilings R-21 (Georgia
    minimum R-12). https://www.poultryventilation.com/ and UGA
    Extension bulletin B1264 "Basic Introduction to Broiler Housing
    Environmental Control". Retrieved 2026-07-23.
[ASHRAE-Films] ASHRAE Handbook -- Fundamentals, Chapter 26 (Heat, Air
    and Moisture Control), surface air-film conductances. Combined
    inside+outside film resistance ~= 0.85 ft^2.F.h/Btu used here.
"""

from __future__ import annotations

from dataclasses import dataclass

#: Exact conversion: 1 ft^2.F.h/Btu = 0.176110 m^2.K/W.
_R_IP_TO_SI = 0.176110

#: Combined inside+outside surface air-film resistance, IP units
#: [ASHRAE-Films]. Added to the nominal insulation R to get the whole
#: assembly resistance.
_FILMS_IP = 0.85


def u_from_r_ip(nominal_r_ip: float) -> float:
    """Assembly U-value [W/m^2K] from a nominal insulation R-value [IP].

    Adds the standard combined surface air films and converts to SI (see
    the module docstring for the full method). Rounded to 3 decimals.
    """
    r_total_si = (nominal_r_ip + _FILMS_IP) * _R_IP_TO_SI
    return round(1.0 / r_total_si, 3)


@dataclass(frozen=True)
class EnvelopePreset:
    """A named construction type with a cited assembly U-value.

    label : str
        What the user sees in the picker, e.g. "Insulated wall (R-13)".
    default_name : str
        The surface name pre-filled when this preset is inserted
        (editable afterwards), e.g. "sidewalls".
    u_value : float
        Assembly U-value, W/m^2K (SI), from `u_from_r_ip`.
    source : str
        One-line, human-readable derivation + citation tag.
    """

    label: str
    default_name: str
    u_value: float
    source: str


def _wall(label: str, name: str, r_ip: float, cite: str) -> EnvelopePreset:
    u = u_from_r_ip(r_ip)
    return EnvelopePreset(
        label=label, default_name=name, u_value=u,
        source=f"R-{r_ip:g} insulation + {_FILMS_IP:g} film (IP) -> U={u} W/m^2K [{cite}]",
    )


#: The picker list, ordered wall presets then ceiling/roof presets, from
#: least to most insulated. Every U-value is derived, not invented.
ENVELOPE_PRESETS: list[EnvelopePreset] = [
    _wall("Uninsulated wall (single-skin / curtain)", "sidewalls", 0.0, "ASHRAE-Films"),
    _wall("Minimally insulated wall (R-7)", "sidewalls", 7.0, "UGA-Fairchild"),
    _wall("Insulated wall (R-13, heated house)", "sidewalls", 13.0, "UGA-Fairchild"),
    _wall("Well-insulated wall (R-19)", "sidewalls", 19.0, "UGA-Fairchild/ASHRAE"),
    _wall("Uninsulated ceiling / roof", "ceiling", 0.0, "ASHRAE-Films"),
    _wall("Minimally insulated ceiling (R-12)", "ceiling", 12.0, "UGA-Fairchild"),
    _wall("Insulated ceiling (R-21, recommended)", "ceiling", 21.0, "UGA-Fairchild"),
    _wall("Well-insulated ceiling (R-30)", "ceiling", 30.0, "UGA-Fairchild/ASHRAE"),
]


def by_label(label: str) -> EnvelopePreset:
    """Look up a preset by its picker label. Raises KeyError if unknown."""
    for p in ENVELOPE_PRESETS:
        if p.label == label:
            return p
    raise KeyError(label)


#: The two surfaces the editor seeds by default -- a sensible, cited
#: starting point (an insulated, heated broiler house). Picked by label
#: so the seed can never drift away from the catalogue.
DEFAULT_WALL = by_label("Insulated wall (R-13, heated house)")
DEFAULT_CEILING = by_label("Insulated ceiling (R-21, recommended)")
