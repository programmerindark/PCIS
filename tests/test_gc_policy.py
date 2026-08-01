"""The IB Group GC policy, checked against real money.

PCIS refuses to output profit figures everywhere else, because an
uncited number is the one most likely to be believed uncritically. This
module is the exception: the payout is a PUBLISHED CONTRACT FORMULA, so
computing it is arithmetic over a stated rule.

That exception is only defensible if the arithmetic is exactly right, so
these tests check it two ways: against the policy's own worked
illustration, and against a real settlement paid to this farm.
"""
from __future__ import annotations

import pytest

from pcis.core import gc_policy as gc


# --- the policy's own illustration (three cases) --------------------------
# 15,000 housed, 5% mortality, FCR 1.600, Parivartan EC shed.

@pytest.mark.parametrize("abw,exp_cfcr,exp_rate,exp_earning", [
    (2.300, 1.525, 12.00, 393_300),
    (2.400, 1.500, 13.00, 444_600),
    (2.500, 1.475, 13.00, 463_125),
])
def test_reproduces_the_policy_illustration(abw, exp_cfcr, exp_rate, exp_earning):
    housed, lifted = 15000, 14250
    total = lifted * abw
    a = gc.assess(housed, lifted, total, total * 1.600, shed_type="parivartan_ec")
    assert a.cfcr == pytest.approx(exp_cfcr, abs=0.001)
    assert a.rate_per_kg == exp_rate
    assert a.rearing_charge == pytest.approx(exp_earning, abs=1)


# --- a real settlement: lot B924B95626 ------------------------------------
# 21,432 housed, 1,314 dead (6.131%), 66,624.35 kg, 107,880 kg feed.
# Slip states FCR 1.619, CBW 3.272, CFCR 1.301, rearing Rs 899,428.73.

LOT = dict(chicks_housed=21432, birds_lifted=20118,
           total_lifted_weight_kg=66624.350, feed_consumed_kg=107880.0)


def test_real_settlement_fcr():
    assert gc.assess(**LOT).fcr == pytest.approx(1.619, abs=0.001)


def test_real_settlement_cbw_uses_the_over_5pct_rule():
    a = gc.assess(**LOT)
    assert a.mortality_pct == pytest.approx(6.131, abs=0.001)
    assert a.cbw_penalised is True
    assert a.cbw_kg == pytest.approx(3.272, abs=0.001)


def test_real_settlement_cfcr():
    assert gc.assess(**LOT).cfcr == pytest.approx(1.301, abs=0.001)


def test_real_settlement_rearing_charge_to_the_rupee():
    """Rs 13.50/kg identifies the shed as 'other EC'."""
    a = gc.assess(**LOT, shed_type="other_ec")
    assert a.rate_per_kg == 13.50
    assert a.rearing_charge == pytest.approx(899_428.73, abs=1)


# --- the 5% mortality cliff ------------------------------------------------

def test_below_threshold_deaths_do_not_touch_cbw():
    """At or under 5%, CBW is simply the average weight of lifted birds."""
    a = gc.assess(20000, 19200, 19200 * 2.5, 19200 * 2.5 * 1.6)   # 4% mortality
    assert a.cbw_penalised is False
    assert a.cbw_kg == pytest.approx(2.5, abs=0.001)


def test_crossing_the_threshold_raises_cfcr():
    """The denominator locks, so the same birds score worse."""
    housed, wt, fcr = 20000, 2.5, 1.6
    under = gc.assess(housed, 19000, 19000 * wt, 19000 * wt * fcr)   # 5.0%
    over = gc.assess(housed, 18800, 18800 * wt, 18800 * wt * fcr)    # 6.0%
    assert under.cbw_penalised is False and over.cbw_penalised is True
    assert over.cfcr > under.cfcr


def test_the_threshold_is_explained_not_silent():
    a = gc.assess(**LOT)
    assert any("above the 5% threshold" in n for n in a.notes)


# --- slab behaviour --------------------------------------------------------

def test_rate_is_a_step_function_not_a_slope():
    assert gc.gc_rate_per_kg(1.3499, "other_ec") == gc.gc_rate_per_kg(1.3500, "other_ec")
    assert gc.gc_rate_per_kg(1.3501, "other_ec") < gc.gc_rate_per_kg(1.3500, "other_ec")


def test_above_1_800_pays_nothing_at_all():
    for shed in gc.SHED_TYPES:
        assert gc.gc_rate_per_kg(1.8001, shed) == 0.0


def test_zero_payment_is_called_out_explicitly():
    a = gc.assess(20000, 19000, 19000 * 1.8, 19000 * 1.8 * 2.0)
    assert a.rate_per_kg == 0.0
    assert any("ZERO" in n for n in a.notes)


def test_1_650_is_the_worst_cliff():
    """Every other boundary costs less; this one is worth knowing about."""
    drops = []
    for lo, hi in [(1.350, 1.351), (1.400, 1.401), (1.450, 1.451), (1.500, 1.501),
                   (1.550, 1.551), (1.600, 1.601), (1.650, 1.651)]:
        drops.append((gc.gc_rate_per_kg(lo, "other_ec") - gc.gc_rate_per_kg(hi, "other_ec"), lo))
    worst = max(drops)
    assert worst[1] == 1.600, f"expected the 1.600->1.601 step to be worst, got {worst}"


def test_shed_type_changes_the_money():
    assert gc.gc_rate_per_kg(1.35, "parivartan_ec") > gc.gc_rate_per_kg(1.35, "other_basic_ec")


def test_unknown_shed_type_is_rejected_not_defaulted():
    with pytest.raises(ValueError):
        gc.gc_rate_per_kg(1.4, "not_a_shed")


# --- distance to the boundary ---------------------------------------------

def test_margin_warns_before_the_drop():
    a = gc.assess(**LOT)
    assert a.distance.margin_to_worse_cfcr == pytest.approx(1.350 - 1.301, abs=0.002)
    assert a.distance.loss_per_kg == pytest.approx(0.50, abs=0.01)


def test_heavier_birds_lower_cfcr_via_the_correction():
    light = gc.assess(20000, 19000, 19000 * 2.2, 19000 * 2.2 * 1.6)
    heavy = gc.assess(20000, 19000, 19000 * 3.0, 19000 * 3.0 * 1.6)
    assert heavy.cfcr < light.cfcr


# --- guard rails on scope --------------------------------------------------

def test_result_states_it_is_rearing_charge_only():
    """Incentives are unpublished; the module must not imply completeness."""
    assert any("Rearing charge only" in n for n in gc.assess(**LOT).notes)


def test_in_crop_projection_is_a_position_not_a_forecast():
    p = gc.project_in_crop(23440, 16500, 2.5, 16500 * 2.5 * 1.55)
    assert p.cfcr > 0 and p.rate_per_kg >= 0
    assert p.avg_weight_kg == pytest.approx(2.5, abs=0.001)
