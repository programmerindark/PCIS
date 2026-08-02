// GENERATED FILE -- DO NOT EDIT BY HAND.
//
// Produced by scripts/export_gc_tables.py from pcis/core/gc_policy.py, which
// is the only place a growing-charge rate may be changed. tests/test_gc_export.py
// fails if this file drifts from the engine.
//
// Source: IB Group GC Policy, EC Shed, valid for placements
// 16 October 2025 - 15 October 2026. Verified against settlement B924B95626.


export const SHED_TYPES = [
  "other_basic_ec",
  "parivartan_basic_ec",
  "other_semi_ec",
  "parivartan_semi_ec",
  "other_ec",
  "parivartan_ec",
] as const;

export type ShedType = (typeof SHED_TYPES)[number];

/** The shed types to OFFER in a picker.
 *
 *  Narrower than SHED_TYPES on purpose: the Parivartan columns belong to
 *  a separate scheme run by another company. They stay in the slab table
 *  because the policy's own worked illustration is a Parivartan case and
 *  validates the arithmetic -- they are simply not choices this farm's
 *  growers can be on. */
export const OFFERED_SHED_TYPES: ShedType[] = [
  "other_basic_ec",
  "other_semi_ec",
  "other_ec",
];

/** The ONE settlement family these tables reproduce.
 *
 *  A crop from the other IB Group entity is wrong on the CBW denominator
 *  AND the rate table at the same time, and reads HIGH. Show this. */
export const POLICY_ENTITY = "ABIS Foods and Proteins Private Limited";
export const POLICY_START_ISO = "2025-10-16";
export const POLICY_END_ISO = "2026-10-15";

/** PLACEMENT date, not lift: lot B924B95625 (other entity, different rate
 *  table) was LIFTED inside this window but PLACED eight days before it.
 *  ISO strings sort chronologically, so a malformed date fails closed. */
export function policyCovers(placementDateIso: string): boolean {
  const d = (placementDateIso || '').trim().slice(0, 10);
  if (d.length !== 10) return false;
  return POLICY_START_ISO <= d && d <= POLICY_END_ISO;
}

/** Mortality above this switches the CBW denominator to 95% of chicks housed. */
export const CBW_MORTALITY_THRESHOLD_PCT = 5.0;
export const CBW_REFERENCE_KG = 2.0;
export const CBW_CORRECTION = 0.25;

/** [upper bound of cFCR band, Rs per kg by shed type].
 *  Read as 'cFCR at or below this bound pays this rate'. The last entry is
 *  the cliff: above 1.800 the growing charge is zero, not merely reduced. */
export const GC_SLABS: [number, Record<ShedType, number>][] = [
  [1.35, { other_basic_ec: 12.75, parivartan_basic_ec: 12.75, other_semi_ec: 13.0, parivartan_semi_ec: 13.5, other_ec: 13.5, parivartan_ec: 14.75 }],
  [1.4, { other_basic_ec: 12.25, parivartan_basic_ec: 12.25, other_semi_ec: 12.5, parivartan_semi_ec: 13.0, other_ec: 13.0, parivartan_ec: 14.25 }],
  [1.45, { other_basic_ec: 11.75, parivartan_basic_ec: 11.75, other_semi_ec: 12.0, parivartan_semi_ec: 12.5, other_ec: 12.5, parivartan_ec: 13.75 }],
  [1.5, { other_basic_ec: 11.25, parivartan_basic_ec: 11.25, other_semi_ec: 11.5, parivartan_semi_ec: 12.0, other_ec: 12.0, parivartan_ec: 13.0 }],
  [1.55, { other_basic_ec: 10.75, parivartan_basic_ec: 10.75, other_semi_ec: 11.0, parivartan_semi_ec: 11.25, other_ec: 11.25, parivartan_ec: 12.0 }],
  [1.6, { other_basic_ec: 10.0, parivartan_basic_ec: 10.0, other_semi_ec: 10.25, parivartan_semi_ec: 10.5, other_ec: 10.5, parivartan_ec: 11.5 }],
  [1.65, { other_basic_ec: 8.0, parivartan_basic_ec: 8.0, other_semi_ec: 8.0, parivartan_semi_ec: 8.0, other_ec: 8.0, parivartan_ec: 8.0 }],
  [1.7, { other_basic_ec: 7.0, parivartan_basic_ec: 7.0, other_semi_ec: 7.0, parivartan_semi_ec: 7.0, other_ec: 7.0, parivartan_ec: 7.0 }],
  [1.75, { other_basic_ec: 6.0, parivartan_basic_ec: 6.0, other_semi_ec: 6.0, parivartan_semi_ec: 6.0, other_ec: 6.0, parivartan_ec: 6.0 }],
  [1.8, { other_basic_ec: 5.0, parivartan_basic_ec: 5.0, other_semi_ec: 5.0, parivartan_semi_ec: 5.0, other_ec: 5.0, parivartan_ec: 5.0 }],
  [Infinity, { other_basic_ec: 0.0, parivartan_basic_ec: 0.0, other_semi_ec: 0.0, parivartan_semi_ec: 0.0, other_ec: 0.0, parivartan_ec: 0.0 }],
];
