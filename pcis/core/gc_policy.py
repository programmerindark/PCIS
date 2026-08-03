"""IB Group growing-charge (GC) policy: what the crop actually pays.

This is the one place PCIS is allowed to produce a money figure, and the
reason is worth stating because it is the exception to a rule the rest of
the codebase keeps strictly.

PCIS otherwise refuses to output profit or yield, on the grounds that such
a number would be the only uncited value in the app and the one most
likely to be believed uncritically. That objection does not apply here.
The IB Group GC policy is a PUBLISHED CONTRACT FORMULA. Computing a payout
from measured weight, feed and mortality is arithmetic over a stated rule,
exactly like the EU 2007/43/EC mortality ceiling already in
`pcis.core.mortality`. Nothing is modelled, forecast or assumed.

What this module will NOT do, and must never be extended to do:

  * predict what FCR or body weight a crop will end at
  * price feed, chicks, electricity or labour
  * report a "profit" that nets contract income against farm costs

Those need data PCIS does not have and coefficients nobody has published.
This module answers only: given these MEASURED outcomes, what does the
contract pay?

Validation
----------
The slab tables and formulae below were checked against the policy's own
worked illustration (three cases) and against a real settlement from this
farm (lot B924B95626, 22.12.2025-08.02.2026). Both reproduce to the rupee.
See tests/test_gc_policy.py.

References
----------
[IBGC2025]  IB Group GC Policy, EC Shed, valid for placements
    16 October 2025 - 15 October 2026. Defines Corrected Body Weight
    (CBW), corrected FCR (cFCR) and the GC/kg slab tables reproduced here.
[LOT95626]  ABIS Foods and Proteins settlement for order B924B95626,
    used to verify the payout decomposition against real money paid.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

# ---------------------------------------------------------------------------
# Slab tables  [IBGC2025]
# ---------------------------------------------------------------------------

#: The six shed classifications the policy prices separately. The label is
#: the operator-facing name; the farm must know which one its contract
#: says, because the same cFCR pays differently across columns (at cFCR
#: 1.35 the spread is Rs 12.75 to Rs 14.75/kg -- 16%).
SHED_TYPES: tuple[str, ...] = (
    "other_basic_ec",
    "parivartan_basic_ec",
    "other_semi_ec",
    "parivartan_semi_ec",
    "other_ec",
    "parivartan_ec",
)

#: (upper bound of cFCR band, {shed type: Rs per kg})  [IBGC2025]
#:
#: Read as "cFCR at or below this bound pays this rate". The final entry is
#: the cliff edge: above 1.800 the entire growing charge is zero, not
#: merely reduced.
_GC_SLABS: list[tuple[float, dict[str, float]]] = [
    (1.350, {"other_basic_ec": 12.75, "parivartan_basic_ec": 12.75,
             "other_semi_ec": 13.00, "parivartan_semi_ec": 13.50,
             "other_ec": 13.50, "parivartan_ec": 14.75}),
    (1.400, {"other_basic_ec": 12.25, "parivartan_basic_ec": 12.25,
             "other_semi_ec": 12.50, "parivartan_semi_ec": 13.00,
             "other_ec": 13.00, "parivartan_ec": 14.25}),
    (1.450, {"other_basic_ec": 11.75, "parivartan_basic_ec": 11.75,
             "other_semi_ec": 12.00, "parivartan_semi_ec": 12.50,
             "other_ec": 12.50, "parivartan_ec": 13.75}),
    (1.500, {"other_basic_ec": 11.25, "parivartan_basic_ec": 11.25,
             "other_semi_ec": 11.50, "parivartan_semi_ec": 12.00,
             "other_ec": 12.00, "parivartan_ec": 13.00}),
    (1.550, {"other_basic_ec": 10.75, "parivartan_basic_ec": 10.75,
             "other_semi_ec": 11.00, "parivartan_semi_ec": 11.25,
             "other_ec": 11.25, "parivartan_ec": 12.00}),
    (1.600, {"other_basic_ec": 10.00, "parivartan_basic_ec": 10.00,
             "other_semi_ec": 10.25, "parivartan_semi_ec": 10.50,
             "other_ec": 10.50, "parivartan_ec": 11.50}),
    (1.650, {"other_basic_ec": 8.00, "parivartan_basic_ec": 8.00,
             "other_semi_ec": 8.00, "parivartan_semi_ec": 8.00,
             "other_ec": 8.00, "parivartan_ec": 8.00}),
    (1.700, {k: 7.00 for k in SHED_TYPES}),
    (1.750, {k: 6.00 for k in SHED_TYPES}),
    (1.800, {k: 5.00 for k in SHED_TYPES}),
    (float("inf"), {k: 0.00 for k in SHED_TYPES}),
]

# ---------------------------------------------------------------------------
# Scope  [IBGC2025]
# ---------------------------------------------------------------------------
#
# These tables reproduce ONE settlement family. That is not pedantry: the
# same farm's lot B924B95625 (ABIS Exports, Oct 2025) and lot B924B95626
# (ABIS Foods and Proteins, Dec 2025) are five weeks apart and agree on
# almost nothing that matters.
#
#   * CBW divides by chicks housed under Exports, by 0.95 x chicks under
#     Foods and Proteins
#   * Exports paid Rs 10.10/kg at cFCR 1.593 -- a rate that appears NOWHERE
#     in the slab grid below, at any cFCR, in any of the six shed columns.
#     It is a different table, not a shifted one.
#   * Exports deducts production-cost and M recovery (Rs 33,724 on that
#     lot); Foods and Proteins deducts medicine only (Rs 666)
#
# So a crop from the wrong entity does not come out slightly off -- it comes
# out wrong on the denominator AND the rate simultaneously, and it reads
# HIGH, which is the direction that gets a grower a phone call. Callers must
# check `policy_covers()` before showing a figure to anyone.
#: The shed types this farm's contract can actually be on.
#:
#: "Parivartan" is a separate scheme run by another company, so offering it
#: in a calculator aimed at growers under THIS contract adds three ways to
#: pick a wrong answer and no way to pick a right one -- and a wrong shed
#: type is undetectable, worth up to 16%.
#:
#: The Parivartan columns stay in `_GC_SLABS` rather than being deleted,
#: because the tables are a faithful reproduction of a published document
#: and the policy's OWN worked illustration is a Parivartan EC case. That
#: illustration is one of only two external validations this module has
#: (the other is a real settlement). Deleting the rows to tidy the UI would
#: throw away a check on the arithmetic to save a dropdown entry.
OFFERED_SHED_TYPES: tuple[str, ...] = (
    "other_basic_ec",
    "other_semi_ec",
    "other_ec",
)

POLICY_ENTITY = "ABIS Foods and Proteins Private Limited"
POLICY_START_ISO = "2025-10-16"
POLICY_END_ISO = "2026-10-15"


def policy_covers(placement_date_iso: str) -> bool:
    """Is a crop PLACED on this date priced by the tables in this module?

    Placement, not lifting, and the distinction decides real cases. The
    policy is stated as valid for placements in the window, and lot
    B924B95625 -- the other entity, on a different rate table -- was lifted
    18.11.2025, comfortably INSIDE the window. Checking the lift date would
    wave it through. It was placed 08.10.2025, eight days before the window
    opens, so checking placement rejects it correctly.

    Compared as ISO strings, which sort chronologically, so no date parsing
    is needed and a malformed input fails closed rather than silently
    passing.
    """
    d = (placement_date_iso or "").strip()[:10]
    if len(d) != 10:
        return False
    return POLICY_START_ISO <= d <= POLICY_END_ISO


#: How long before the window closes to start saying so.
#:
#: A crop takes roughly six weeks from placement to lift, so a grower
#: placing birds inside the last stretch of the window will be settled
#: under it, but the NEXT crop will not be. The warning exists to get the
#: replacement document in hand before the tables silently go stale --
#: the rates changed entirely at the last transition, so assuming
#: continuity across a renewal is exactly the mistake to avoid.
POLICY_EXPIRY_WARNING_DAYS = 90


def policy_status(today_iso: str) -> str:
    """'current' | 'expiring' | 'expired' for the tables in this module.

    Evaluated against a date the CALLER supplies rather than a captured
    "now", so the answer is testable and so a build-time constant can never
    freeze the tool into permanently believing it is current.
    """
    from datetime import date

    try:
        today = date.fromisoformat((today_iso or "").strip()[:10])
        end = date.fromisoformat(POLICY_END_ISO)
    except ValueError:
        # Fail loud rather than silently claiming currency.
        return "expired"
    if today > end:
        return "expired"
    if (end - today).days <= POLICY_EXPIRY_WARNING_DAYS:
        return "expiring"
    return "current"


#: Mortality above this switches the CBW denominator  [IBGC2025].
#:
#: At or below 5%, CBW divides by birds actually lifted, so deaths do not
#: touch CBW at all. Above it the denominator LOCKS to 95% of chicks
#: housed, so every further death drags CBW down, raises cFCR, and can
#: push the crop off a slab. It is a genuine cliff and worth warning on.
CBW_MORTALITY_THRESHOLD_PCT = 5.0

#: cFCR = (CBW_REFERENCE_KG - CBW) x CBW_CORRECTION + FCR   [IBGC2025]
CBW_REFERENCE_KG = 2.0
CBW_CORRECTION = 0.25


def gc_rate_per_kg(cfcr: float, shed_type: str = "other_ec") -> float:
    """Rs/kg growing charge for a corrected FCR  [IBGC2025]."""
    if shed_type not in SHED_TYPES:
        raise ValueError(f"unknown shed type {shed_type!r}; expected one of {SHED_TYPES}")
    for upper, rates in _GC_SLABS:
        if cfcr <= upper:
            return rates[shed_type]
    return 0.0


def corrected_body_weight(
    total_lifted_weight_kg: float,
    birds_lifted: int,
    chicks_housed: int,
    mortality_pct: float,
) -> float:
    """Corrected Body Weight  [IBGC2025].

    The branch at 5% mortality is the whole point of the metric: below it
    the grower is measured on the birds they delivered, above it on the
    birds they should have delivered.
    """
    if mortality_pct <= CBW_MORTALITY_THRESHOLD_PCT:
        return total_lifted_weight_kg / max(1, birds_lifted)
    return total_lifted_weight_kg / max(1.0, 0.95 * chicks_housed)


def corrected_fcr(cbw_kg: float, fcr: float) -> float:
    """cFCR = (2 - CBW) x 0.25 + FCR   [IBGC2025].

    Heavier birds are rewarded twice: directly through more kilograms, and
    again here, because a CBW above the 2 kg reference SUBTRACTS from the
    FCR used for grading.
    """
    return (CBW_REFERENCE_KG - cbw_kg) * CBW_CORRECTION + fcr


@dataclass(frozen=True)
class SlabDistance:
    """How close the crop is sitting to a change in Rs/kg."""

    next_better_cfcr: float | None      # cFCR needed to reach the better rate
    next_better_rate: float | None
    gain_per_kg: float | None
    margin_to_worse_cfcr: float | None  # how much cFCR may worsen before dropping
    next_worse_rate: float | None
    loss_per_kg: float | None


def slab_distance(cfcr: float, shed_type: str = "other_ec") -> SlabDistance:
    """Distance to the slab boundaries either side of the current cFCR.

    The downside figure is the one that matters operationally. The slabs
    are not evenly spaced: crossing 1.650 costs Rs 2.50-3.50/kg depending
    on shed type, several times any other boundary, and above 1.800 the
    payment is zero. Knowing you are 0.008 away from that is actionable in
    a way that the cFCR number alone is not.
    """
    here = gc_rate_per_kg(cfcr, shed_type)
    better_bound = better_rate = None
    for upper, rates in _GC_SLABS:
        if rates[shed_type] > here:
            better_bound, better_rate = upper, rates[shed_type]
    worse_bound = worse_rate = None
    for upper, rates in _GC_SLABS:
        if upper >= cfcr and rates[shed_type] < here:
            worse_bound, worse_rate = upper, rates[shed_type]
            break
    # The boundary that ENDS the current band is the one to stay under.
    current_upper = next((u for u, r in _GC_SLABS if r[shed_type] == here and u >= cfcr), None)
    return SlabDistance(
        next_better_cfcr=better_bound,
        next_better_rate=better_rate,
        gain_per_kg=(better_rate - here) if better_rate is not None else None,
        margin_to_worse_cfcr=(current_upper - cfcr) if current_upper not in (None, float("inf")) else None,
        next_worse_rate=worse_rate,
        loss_per_kg=(here - worse_rate) if worse_rate is not None else None,
    )


@dataclass(frozen=True)
class GCAssessment:
    """A crop priced against the contract. Every figure is arithmetic."""

    mortality_pct: float
    birds_lifted: int
    avg_weight_kg: float
    fcr: float
    cbw_kg: float
    cfcr: float
    cbw_penalised: bool          # True when the >5% denominator rule applied
    rate_per_kg: float
    rearing_charge: float
    total_weight_kg: float
    shed_type: str
    distance: SlabDistance
    notes: list[str]
    #: Set when an input the contract formula REQUIRES is missing, so the
    #: figures above cannot be stood behind. Callers must show this instead
    #: of the money, never alongside it. Reporting a payout computed from
    #: an incomplete crop is worse than reporting nothing, because it looks
    #: exactly like a payout computed from a complete one.
    incomplete_reason: str | None = None


def assess(
    chicks_housed: int,
    birds_lifted: int,
    total_lifted_weight_kg: float,
    feed_consumed_kg: float,
    shed_type: str = "other_ec",
    shortage: int = 0,
) -> GCAssessment:
    """Price a crop against the IB Group GC policy  [IBGC2025].

    Returns the rearing charge only. The real settlement adds incentives
    (rate, body-weight, brooding, loyalty) whose formulae are not stated in
    the policy document, so PCIS does not guess at them -- see the note
    attached to the result.

    `shortage` is birds the settlement records as short, i.e. neither
    delivered nor dead. Settlements carry it as its own line, and it must
    stay out of mortality: on lot B924B95625 a 55-bird shortage is the
    difference between the slip's 8.635% and the 8.884% you get from
    (housed - lifted). Both sit above the 5% threshold there so nothing
    moved, but a crop at 4.9% true mortality with a shortage would be
    pushed over the line by this alone and have its CBW divided by 95% of
    housed birds -- penalised for birds it never received.
    """
    chicks_housed = max(1, chicks_housed)
    shortage = max(0, min(shortage, chicks_housed))
    birds_lifted = max(0, min(birds_lifted, chicks_housed))
    dead = max(0, chicks_housed - birds_lifted - shortage)
    mortality_pct = 100.0 * dead / chicks_housed

    fcr = feed_consumed_kg / total_lifted_weight_kg if total_lifted_weight_kg > 0 else 0.0
    cbw = corrected_body_weight(total_lifted_weight_kg, birds_lifted, chicks_housed, mortality_pct)
    cf = corrected_fcr(cbw, fcr)
    rate = gc_rate_per_kg(cf, shed_type)
    dist = slab_distance(cf, shed_type)

    notes: list[str] = []
    penalised = mortality_pct > CBW_MORTALITY_THRESHOLD_PCT
    if penalised:
        unpenalised = corrected_body_weight(total_lifted_weight_kg, birds_lifted, chicks_housed, 0.0)
        cost = corrected_fcr(cbw, fcr) - corrected_fcr(unpenalised, fcr)
        notes.append(
            f"Mortality {mortality_pct:.2f}% is above the {CBW_MORTALITY_THRESHOLD_PCT:.0f}% "
            f"threshold, so CBW was divided by 95% of chicks housed instead of birds "
            f"lifted [IBGC2025]. That added {cost:+.3f} to cFCR."
        )
    if rate == 0.0:
        notes.append(
            "cFCR is above 1.800: the growing charge is ZERO under this policy, "
            "not merely reduced [IBGC2025]."
        )
    elif dist.margin_to_worse_cfcr is not None and dist.loss_per_kg:
        notes.append(
            f"{dist.margin_to_worse_cfcr:.3f} of cFCR margin before the rate drops "
            f"Rs {dist.loss_per_kg:.2f}/kg (worth Rs "
            f"{dist.loss_per_kg * total_lifted_weight_kg:,.0f} on this crop)."
        )
    notes.append(
        "Rearing charge only. Settlements also carry rate, body-weight, brooding "
        "and loyalty incentives whose formulae are not published in the policy "
        "document, so PCIS does not estimate them -- expect the real payment to "
        "be higher than the figure above."
    )

    return GCAssessment(
        mortality_pct=round(mortality_pct, 3),
        birds_lifted=birds_lifted,
        avg_weight_kg=round(total_lifted_weight_kg / max(1, birds_lifted), 3),
        fcr=round(fcr, 3),
        cbw_kg=round(cbw, 3),
        cfcr=round(cf, 3),
        cbw_penalised=penalised,
        rate_per_kg=rate,
        rearing_charge=round(total_lifted_weight_kg * rate, 2),
        total_weight_kg=round(total_lifted_weight_kg, 2),
        shed_type=shed_type,
        distance=dist,
        notes=notes,
    )


def project_in_crop(
    chicks_housed: int,
    birds_alive: int,
    avg_weight_kg: float,
    feed_consumed_kg: float,
    shed_type: str = "other_ec",
    depleted_birds: int = 0,
    depleted_weight_kg: float = 0.0,
    shortage: int = 0,
) -> GCAssessment:
    """Where the crop stands if the rest were lifted today.

    Deliberately NOT a forecast. It applies the contract formula to what
    has been measured so far, so the operator can see which slab they are
    currently sitting in and how much margin is left. It assumes nothing
    about the days remaining -- weight will rise and FCR will worsen, and
    both move cFCR, so treat this as a position, not a prediction.

    Depletion handling is the dangerous part
    ----------------------------------------
    Birds already thinned out have been DELIVERED, not lost. An earlier
    version of this function passed `birds_alive` straight in as
    `birds_lifted`, which made `assess` compute mortality as
    housed - alive -- counting every thinned bird as a death.

    That is not a rounding error. A routine 6,940-bird thin out of ~26,000
    reads as roughly 27% mortality, which is far past the 5% threshold, so
    CBW switches to the 95%-of-housed denominator, cFCR jumps, and the crop
    is priced in the wrong slab. The number would be wrong in the exact
    place the operator is most likely to trust it. The same confusion
    already produced a false welfare breach on the mortality page; here it
    produces a false payout.

    So thinned birds are added back to both the delivered count and the
    delivered weight. Their weight is required, not optional -- see
    `incomplete_reason`.
    """
    depleted_birds = max(0, depleted_birds)
    delivered_birds = birds_alive + depleted_birds
    total_weight = birds_alive * avg_weight_kg + max(0.0, depleted_weight_kg)

    # A thin whose weight was never recorded cannot be priced. Feed for
    # those birds is already in `feed_consumed_kg` while their kilograms
    # are missing from the denominator, so FCR would be overstated and the
    # crop would appear to sit in a worse slab than it does. Guessing the
    # weight from a growth curve would be exactly the kind of invented
    # number this codebase forbids, so PCIS says what it cannot do instead.
    incomplete = None
    if depleted_birds > 0 and depleted_weight_kg <= 0.0:
        incomplete = (
            f"{depleted_birds:,} birds have been lifted but no lift weight was "
            f"recorded. FCR cannot be computed without those kilograms, so no GC "
            f"rate is shown. Enter the weight from the lifting slip to see the "
            f"position."
        )

    out = assess(
        chicks_housed=chicks_housed,
        birds_lifted=delivered_birds,
        total_lifted_weight_kg=total_weight,
        feed_consumed_kg=feed_consumed_kg,
        shed_type=shed_type,
        shortage=shortage,
    )
    if incomplete is None:
        return out
    return replace(out, incomplete_reason=incomplete)
