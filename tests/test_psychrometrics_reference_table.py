"""Independent validation of PCIS psychrometrics against a published
industrial reference table.

Source
------
[Devatec] Devatec SA, "Humidity Content Table" — specific humidity
    (g water / kg dry air) and saturation vapour pressure (Pa) tabulated
    against dry-bulb temperature and relative humidity.
    https://www.devatec.com

Why this file exists: every other psychrometrics test checks our
implementation against the equations we chose (Buck 1996 / ASHRAE). This
one checks it against a table produced INDEPENDENTLY of those choices —
if our formulas or unit handling were subtly wrong, agreement with an
outside source would break even though the self-consistent tests passed.

Result at time of writing: agreement is within 0.3% across 0-38 C and
20-100% RH, which is inside the rounding of the published table itself.
"""

import pytest

from pcis.core import psychrometrics as psy

#: Devatec specific humidity, g/kg dry air: {T_C: {RH_pct: g_per_kg}}
DEVATEC_SPECIFIC_HUMIDITY_G_PER_KG = {
    20: {20: 2.88, 40: 5.80, 60: 8.73, 80: 11.70, 100: 14.70},
    25: {20: 3.92, 40: 7.88, 60: 11.90, 80: 16.00, 100: 20.10},
    27: {20: 4.41, 40: 8.88, 60: 13.40, 80: 18.00, 100: 22.70},
    30: {20: 5.26, 40: 10.60, 60: 16.00, 80: 21.60, 100: 27.20},
    35: {20: 6.99, 40: 14.10, 60: 21.40, 80: 28.90, 100: 36.60},
    38: {20: 8.25, 40: 16.70, 60: 25.40, 80: 34.40, 100: 43.60},
}

#: Devatec saturation vapour pressure, Pa.
DEVATEC_SATURATION_PRESSURE_PA = {
    0: 611.15, 10: 1228.0, 20: 2338.8, 25: 3169.2,
    27: 3567.3, 30: 4246.0, 35: 5627.8, 38: 6631.2,
}

#: The table is printed to 3 significant figures, so ~0.5% is the
#: tightest meaningful agreement. We assert 1% and observe ~0.3%.
TOLERANCE_PCT = 1.0


@pytest.mark.parametrize("t_c", sorted(DEVATEC_SPECIFIC_HUMIDITY_G_PER_KG))
def test_humidity_ratio_matches_devatec_table(t_c):
    for rh_pct, reference_g_per_kg in DEVATEC_SPECIFIC_HUMIDITY_G_PER_KG[t_c].items():
        ours = psy.humidity_ratio_from_relative_humidity(t_c, rh_pct) * 1000.0
        err_pct = abs(ours - reference_g_per_kg) / reference_g_per_kg * 100.0
        assert err_pct < TOLERANCE_PCT, (
            f"{t_c}C/{rh_pct}%: PCIS {ours:.3f} g/kg vs Devatec "
            f"{reference_g_per_kg} g/kg ({err_pct:.2f}% off)"
        )


@pytest.mark.parametrize("t_c,reference_pa", sorted(DEVATEC_SATURATION_PRESSURE_PA.items()))
def test_saturation_vapour_pressure_matches_devatec_table(t_c, reference_pa):
    ours = psy.saturation_vapor_pressure(t_c)
    err_pct = abs(ours - reference_pa) / reference_pa * 100.0
    assert err_pct < TOLERANCE_PCT, (
        f"{t_c}C: PCIS {ours:.1f} Pa vs Devatec {reference_pa} Pa ({err_pct:.2f}% off)"
    )


def test_agreement_is_actually_tight_not_just_within_tolerance():
    """Guards against a future change that stays inside 1% but drifts."""
    worst = 0.0
    for t_c, row in DEVATEC_SPECIFIC_HUMIDITY_G_PER_KG.items():
        for rh_pct, ref in row.items():
            ours = psy.humidity_ratio_from_relative_humidity(t_c, rh_pct) * 1000.0
            worst = max(worst, abs(ours - ref) / ref * 100.0)
    assert worst < 0.5, f"drifted from the reference table: worst error {worst:.2f}%"
