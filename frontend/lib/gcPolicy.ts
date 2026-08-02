/**
 * The IB Group growing-charge formula, in the browser.
 *
 * This is a deliberate, narrow exception to the rule that all engine maths
 * lives in `pcis/core` and nowhere else. The public calculator has to give
 * an answer instantly on a phone with a poor connection, and a farmer
 * waiting on a cold-starting backend to find out what their crop is worth
 * will close the page.
 *
 * The exception is made safe two ways, both enforced by
 * tests/test_gc_export.py:
 *
 *   1. The slab tables are GENERATED from pcis/core/gc_policy.py
 *      (gcTables.generated.ts). A rate can only be changed in Python.
 *   2. The arithmetic below is cross-checked against the Python engine over
 *      a grid of inputs. Any divergence fails the test suite.
 *
 * So this file may be read as a port, not a second opinion. If it ever
 * disagrees with the engine, the engine is right and this is a bug.
 */

import {
  GC_SLABS, CBW_MORTALITY_THRESHOLD_PCT, CBW_REFERENCE_KG, CBW_CORRECTION,
  type ShedType,
} from "./gcTables.generated";

export type { ShedType };
export {
  SHED_TYPES, OFFERED_SHED_TYPES, CBW_MORTALITY_THRESHOLD_PCT,
  POLICY_ENTITY, POLICY_START_ISO, POLICY_END_ISO, policyCovers,
} from "./gcTables.generated";

export function gcRatePerKg(cfcr: number, shedType: ShedType): number {
  for (const [upper, rates] of GC_SLABS) {
    if (cfcr <= upper) return rates[shedType];
  }
  return 0;
}

/** Corrected Body Weight.
 *
 * The branch at 5% mortality is the whole point of the metric: below it the
 * grower is measured on the birds they delivered, above it on the birds
 * they should have delivered. */
export function correctedBodyWeight(
  totalLiftedWeightKg: number,
  birdsLifted: number,
  chicksHoused: number,
  mortalityPct: number
): number {
  if (mortalityPct <= CBW_MORTALITY_THRESHOLD_PCT) {
    return totalLiftedWeightKg / Math.max(1, birdsLifted);
  }
  return totalLiftedWeightKg / Math.max(1, 0.95 * chicksHoused);
}

/** cFCR = (2 - CBW) x 0.25 + FCR.
 *
 * Heavier birds are rewarded twice: directly through more kilograms, and
 * again here, because a CBW above the 2 kg reference SUBTRACTS from the FCR
 * used for grading. */
export function correctedFcr(cbwKg: number, fcr: number): number {
  return (CBW_REFERENCE_KG - cbwKg) * CBW_CORRECTION + fcr;
}

export type SlabDistance = {
  nextBetterCfcr: number | null;
  nextBetterRate: number | null;
  gainPerKg: number | null;
  marginToWorseCfcr: number | null;
  nextWorseRate: number | null;
  lossPerKg: number | null;
};

/** Distance to the slab boundaries either side of the current cFCR.
 *
 * The downside figure is the one that matters. The slabs are not evenly
 * spaced: crossing 1.650 costs Rs 2.50-3.50/kg depending on shed type,
 * several times any other boundary, and above 1.800 the payment is zero.
 * Knowing you are 0.008 away from that is actionable in a way the cFCR
 * number alone is not. */
export function slabDistance(cfcr: number, shedType: ShedType): SlabDistance {
  const here = gcRatePerKg(cfcr, shedType);

  let betterBound: number | null = null;
  let betterRate: number | null = null;
  for (const [upper, rates] of GC_SLABS) {
    if (rates[shedType] > here) {
      betterBound = upper;
      betterRate = rates[shedType];
    }
  }

  let worseRate: number | null = null;
  for (const [upper, rates] of GC_SLABS) {
    if (upper >= cfcr && rates[shedType] < here) {
      worseRate = rates[shedType];
      break;
    }
  }

  // The boundary that ENDS the current band is the one to stay under.
  let currentUpper: number | null = null;
  for (const [upper, rates] of GC_SLABS) {
    if (rates[shedType] === here && upper >= cfcr) {
      currentUpper = upper;
      break;
    }
  }

  return {
    nextBetterCfcr: betterBound,
    nextBetterRate: betterRate,
    gainPerKg: betterRate !== null ? betterRate - here : null,
    marginToWorseCfcr:
      currentUpper !== null && Number.isFinite(currentUpper) ? currentUpper - cfcr : null,
    nextWorseRate: worseRate,
    lossPerKg: worseRate !== null ? here - worseRate : null,
  };
}

export type GCAssessment = {
  mortalityPct: number;
  birdsLifted: number;
  avgWeightKg: number;
  fcr: number;
  cbwKg: number;
  cfcr: number;
  cbwPenalised: boolean;
  ratePerKg: number;
  rearingCharge: number;
  totalWeightKg: number;
  shedType: ShedType;
  distance: SlabDistance;
  notes: string[];
};

/** Price a crop against the IB Group GC policy.
 *
 * Returns the REARING CHARGE only. Real settlements add rate, body-weight,
 * brooding and loyalty incentives whose formulae are not stated in the
 * policy document, so this does not guess at them -- the note says so, and
 * the note must be shown. A farmer comparing this against a settlement slip
 * needs to know why the slip is larger. */
export function assess(
  chicksHoused: number,
  birdsLifted: number,
  totalLiftedWeightKg: number,
  feedConsumedKg: number,
  shedType: ShedType,
  /** Birds the settlement records as SHORT -- neither delivered nor dead.
   *  Keeping them out of mortality matters: on lot B924B95625 a 55-bird
   *  shortage is the difference between 8.635% and 8.884%, and a crop at
   *  4.9% true mortality would otherwise be pushed over the 5% threshold
   *  and penalised for birds it never received. */
  shortage: number = 0
): GCAssessment {
  chicksHoused = Math.max(1, chicksHoused);
  shortage = Math.max(0, Math.min(shortage, chicksHoused));
  birdsLifted = Math.max(0, Math.min(birdsLifted, chicksHoused));
  const dead = Math.max(0, chicksHoused - birdsLifted - shortage);
  const mortalityPct = (100 * dead) / chicksHoused;

  const fcr = totalLiftedWeightKg > 0 ? feedConsumedKg / totalLiftedWeightKg : 0;
  const cbw = correctedBodyWeight(totalLiftedWeightKg, birdsLifted, chicksHoused, mortalityPct);
  const cf = correctedFcr(cbw, fcr);
  const rate = gcRatePerKg(cf, shedType);
  const dist = slabDistance(cf, shedType);

  const notes: string[] = [];
  const penalised = mortalityPct > CBW_MORTALITY_THRESHOLD_PCT;
  if (penalised) {
    const unpenalised = correctedBodyWeight(totalLiftedWeightKg, birdsLifted, chicksHoused, 0);
    const cost = correctedFcr(cbw, fcr) - correctedFcr(unpenalised, fcr);
    notes.push(
      `Mortality ${mortalityPct.toFixed(2)}% is above the ${CBW_MORTALITY_THRESHOLD_PCT}% ` +
        `threshold, so CBW was divided by 95% of chicks housed instead of birds lifted. ` +
        `That added ${cost >= 0 ? "+" : ""}${cost.toFixed(3)} to cFCR.`
    );
  }
  if (rate === 0) {
    notes.push(
      "cFCR is above 1.800: the growing charge is ZERO under this policy, not merely reduced."
    );
  } else if (dist.marginToWorseCfcr !== null && dist.lossPerKg) {
    notes.push(
      `${dist.marginToWorseCfcr.toFixed(3)} of cFCR margin before the rate drops ` +
        `Rs ${dist.lossPerKg.toFixed(2)}/kg (worth Rs ` +
        `${Math.round(dist.lossPerKg * totalLiftedWeightKg).toLocaleString("en-IN")} on this crop).`
    );
  }
  notes.push(
    "Rearing charge only. Settlements also carry rate, body-weight, brooding and " +
      "loyalty incentives whose formulae are not published in the policy document, " +
      "so this does not estimate them — expect the real payment to be higher."
  );

  return {
    mortalityPct: round(mortalityPct, 3),
    birdsLifted,
    avgWeightKg: round(totalLiftedWeightKg / Math.max(1, birdsLifted), 3),
    fcr: round(fcr, 3),
    cbwKg: round(cbw, 3),
    cfcr: round(cf, 3),
    cbwPenalised: penalised,
    ratePerKg: rate,
    rearingCharge: round(totalLiftedWeightKg * rate, 2),
    totalWeightKg: round(totalLiftedWeightKg, 2),
    shedType,
    distance: dist,
    notes,
  };
}

function round(n: number, dp: number): number {
  const f = 10 ** dp;
  return Math.round(n * f) / f;
}
