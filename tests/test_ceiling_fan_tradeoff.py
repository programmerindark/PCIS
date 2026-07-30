"""Lowering the ceiling instead of buying fans, priced per option.

Air speed is airflow divided by cross-section. A false ceiling shrinks the
cross-section, so the same target velocity needs proportionally less
airflow -- and airflow is what fans cost money for.

The velocity table used to report only the speed each height achieves,
which answers the wrong question. The operator's question is "how many
fans would that save me", so each row now carries a fan count.
"""
from __future__ import annotations

import pytest

from pcis.core import target_airspeed as tas
from pcis.core import tunnel_geometry as tgeo
from pcis.equipment.fan_curve import FAN_CATALOG

PER_FAN = FAN_CATALOG[0].airflow_at_static_pressure(30.0)
WIDTH = 15.0


def _table(heights):
    return tgeo.velocity_table(15 * PER_FAN, WIDTH, heights, airflow_per_fan_m3_per_h=PER_FAN)


def test_lower_ceiling_needs_fewer_fans():
    rows = _table([3.0, 2.0])
    assert rows[1].fans_needed < rows[0].fans_needed


def test_the_farms_actual_numbers():
    """3.0 m needs 15 fans; 2.0 m needs 10 -- which is what is installed."""
    rows = {r.ceiling_height_m: r for r in _table([3.0, 2.5, 2.0])}
    assert rows[3.0].fans_needed == 15
    assert rows[2.0].fans_needed == 10


def test_fan_count_is_rounded_up_never_down():
    """Rounding down would under-ventilate, which is the unsafe direction."""
    # Contrive an area needing a fractional fan count.
    n = tgeo.fans_for_velocity(3.0, 10.0, PER_FAN)
    exact = 3.0 * 10.0 * 3600.0 / PER_FAN
    assert n >= exact
    assert n - exact < 1.0


def test_velocity_and_fan_count_are_consistent():
    """The fan count must actually deliver the target at that section."""
    for r in _table([3.0, 2.7, 2.5, 2.2, 2.0]):
        delivered = r.fans_needed * PER_FAN / 3600.0 / r.cross_section_m2
        assert delivered >= tas.TUNNEL_TARGET_AIRSPEED_MPS


def test_fan_count_is_omitted_when_no_fan_airflow_given():
    """Older callers must not receive a fabricated number."""
    rows = tgeo.velocity_table(15 * PER_FAN, WIDTH, [3.0, 2.0])
    assert all(r.fans_needed is None for r in rows)


def test_zero_and_negative_inputs_do_not_crash():
    assert tgeo.fans_for_velocity(3.0, 0.0, PER_FAN) == 0
    assert tgeo.fans_for_velocity(3.0, 45.0, 0.0) == 0


@pytest.mark.parametrize("height", [2.0, 2.2, 2.5, 2.7, 3.0])
def test_every_option_reports_a_plausible_fan_count(height):
    row = _table([height])[0]
    assert row.fans_needed is not None
    assert 1 <= row.fans_needed <= 60


def test_savings_are_monotonic_in_ceiling_height():
    """A lower ceiling can never need MORE fans than a higher one."""
    rows = _table([3.0, 2.7, 2.5, 2.2, 2.0])
    counts = [r.fans_needed for r in rows]
    assert counts == sorted(counts, reverse=True)
