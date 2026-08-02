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


# ---------------------------------------------------------------------------
# In-crop position: a thin must never be priced as mortality
# ---------------------------------------------------------------------------
#
# These numbers are this farm's real shape: ~26,000 placed, a 6,640-bird
# thin, 300 actual deaths. The same confusion booked as mortality once
# already and reported a 31.6% welfare breach on a routine day.


def test_thinned_birds_are_delivered_not_dead():
    """A recorded thin must not move mortality or the CBW denominator."""
    pos = gc.project_in_crop(
        chicks_housed=26_000,
        birds_alive=19_060,
        avg_weight_kg=2.10,
        feed_consumed_kg=88_000.0,
        depleted_birds=6_640,
        depleted_weight_kg=13_280.0,   # 2.00 kg on the lifting slip
    )
    # 26,000 - (19,060 + 6,640) = 300 dead.
    assert pos.mortality_pct == pytest.approx(300 / 26_000 * 100, abs=1e-3)
    assert pos.mortality_pct < gc.CBW_MORTALITY_THRESHOLD_PCT
    assert pos.cbw_penalised is False
    assert pos.incomplete_reason is None
    assert pos.rate_per_kg > 0


def test_treating_a_thin_as_mortality_prices_the_wrong_slab():
    """The old behaviour must be demonstrably wrong, not merely different.

    Passing only the live birds -- which is what this function used to do
    -- reads the thin as deaths. This asserts that the mistake is
    financially material, so nobody 'simplifies' the depletion arguments
    back out of the signature.
    """
    correct = gc.project_in_crop(
        chicks_housed=26_000, birds_alive=19_060, avg_weight_kg=2.10,
        feed_consumed_kg=88_000.0,
        depleted_birds=6_640, depleted_weight_kg=13_280.0,
    )
    as_if_dead = gc.project_in_crop(
        chicks_housed=26_000, birds_alive=19_060, avg_weight_kg=2.10,
        feed_consumed_kg=88_000.0,
    )
    assert as_if_dead.mortality_pct > 25.0          # absurd for a live crop
    assert as_if_dead.cbw_penalised is True         # trips the 5% rule
    assert as_if_dead.cfcr > correct.cfcr           # graded worse
    assert as_if_dead.rate_per_kg < correct.rate_per_kg


def test_lift_without_recorded_weight_refuses_to_price():
    """Missing lift weight suppresses the money rather than guessing it."""
    pos = gc.project_in_crop(
        chicks_housed=26_000, birds_alive=19_060, avg_weight_kg=2.10,
        feed_consumed_kg=88_000.0,
        depleted_birds=6_640, depleted_weight_kg=0.0,
    )
    assert pos.incomplete_reason is not None
    assert "lift weight" in pos.incomplete_reason
    assert "6,640" in pos.incomplete_reason


def test_no_depletion_still_works_unchanged():
    """A crop with no thin behaves exactly as before the change."""
    pos = gc.project_in_crop(
        chicks_housed=26_000, birds_alive=25_400, avg_weight_kg=2.05,
        feed_consumed_kg=80_000.0,
    )
    assert pos.incomplete_reason is None
    assert pos.birds_lifted == 25_400


# ---------------------------------------------------------------------------
# The WIRED path, not just the core function
# ---------------------------------------------------------------------------
#
# The engine matching the settlement proves the arithmetic. It does not
# prove the dashboard shows it: the web layer unpacks a different shape
# (birds ALIVE plus lifted birds and their weight, rather than one lifted
# total), and that repacking is exactly where a thin gets misread as
# mortality. This drives the real endpoint payload end to end.


def test_endpoint_reproduces_the_settlement_to_the_rupee():
    from backend.app import engine_api
    from backend.app.schemas import GCPositionRequest

    # Same lot, expressed as the dashboard would: nothing left in the house,
    # the whole crop delivered as one lift with its weight recorded.
    req = GCPositionRequest(
        chicks_housed=21_432,
        birds_alive=0,
        avg_weight_kg=3.312,          # ignored when birds_alive is 0
        feed_consumed_kg=107_880.0,
        shed_type="other_ec",
        depleted_birds=20_118,
        depleted_weight_kg=66_624.350,
    )
    out = engine_api.gc_position(req)

    assert out["incomplete_reason"] is None
    assert out["fcr"] == pytest.approx(1.619, abs=0.001)
    assert out["cbw_kg"] == pytest.approx(3.272, abs=0.001)
    assert out["cfcr"] == pytest.approx(1.301, abs=0.001)
    assert out["rate_per_kg"] == 13.50
    assert out["rearing_charge"] == pytest.approx(899_428.73, abs=1)
    # 6.131% — above the threshold, so the settlement's own CBW rule applied.
    assert out["cbw_penalised"] is True


# ---------------------------------------------------------------------------
# Scope: these tables belong to ONE entity and ONE contract period
# ---------------------------------------------------------------------------


def test_policy_covers_the_verified_settlement():
    """Lot B924B95626 was PLACED 22.12.2025, inside the period."""
    assert gc.policy_covers("2025-12-22") is True


def test_placement_date_rejects_the_other_entity_crop_but_lift_date_would_not():
    """Lot B924B95625 (ABIS Exports) ran 08.10.2025 to 18.11.2025.

    That crop was paid Rs 10.10/kg at cFCR 1.593 on a table these slabs do
    not contain, so it must be rejected. Its LIFT date sits comfortably
    inside the window -- checking that would wave it straight through. Only
    the placement date catches it, which is why the policy is written
    against placements and this function takes one.
    """
    assert gc.policy_covers("2025-10-08") is False   # placed: rejected
    assert gc.policy_covers("2025-11-18") is True    # lifted: would pass


def test_policy_boundaries_are_inclusive():
    assert gc.policy_covers(gc.POLICY_START_ISO) is True
    assert gc.policy_covers(gc.POLICY_END_ISO) is True
    assert gc.policy_covers("2025-10-15") is False
    assert gc.policy_covers("2026-10-16") is False


def test_malformed_date_fails_closed():
    """An unparseable date must not be treated as in-period."""
    for bad in ["", "   ", "08.02.2026", "2026-2-8", "tomorrow", None]:
        assert gc.policy_covers(bad) is False


def test_the_exports_rate_is_not_in_these_tables():
    """Rs 10.10/kg is absent from every shed column at every cFCR.

    This is the evidence that the two entities use different tables rather
    than a shifted version of one, and it is what justifies scoping the
    calculator by company name rather than by date alone.
    """
    rates = {r for _u, d in gc._GC_SLABS for r in d.values()}  # noqa: SLF001
    assert 10.10 not in rates


def test_offered_shed_types_exclude_parivartan_but_tables_keep_it():
    """The picker narrows; the cited table does not.

    Deleting the Parivartan columns to tidy the dropdown would also delete
    the only shed type the policy's own worked illustration uses, throwing
    away one of two external validations to save three list entries.
    """
    assert all("parivartan" not in s for s in gc.OFFERED_SHED_TYPES)
    assert set(gc.OFFERED_SHED_TYPES).issubset(set(gc.SHED_TYPES))
    # still priced by the engine, still checked by the illustration tests
    assert gc.gc_rate_per_kg(1.350, "parivartan_ec") == 14.75
