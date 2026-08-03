"""Emit the GC slab tables as TypeScript, so the public calculator can run
in the browser without a second source of truth for money.

Why this script exists
----------------------
CLAUDE.md says all engine maths lives in `pcis/core` and nowhere else, and
that rule is the reason the numbers can be trusted. The public calculator
strains it: it must work on a phone with a weak connection, instantly and
without waking a sleeping backend, which means the arithmetic has to run
client-side.

Hand-copying the slab tables into TypeScript would satisfy that and quietly
destroy the guarantee -- two copies of a payout table drift, and the drift
would show up as a wrong rupee figure shown to a farmer, which is the worst
possible place for it.

So the tables are GENERATED from `pcis.core.gc_policy` and the generated
file is checked by `tests/test_gc_export.py`, which fails if it is stale.
Python remains the only place a rate can be edited. The TypeScript
arithmetic that consumes these tables is separately cross-checked against
the Python engine over a grid of inputs by the same test module.

Run:
    python3 scripts/export_gc_tables.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pcis.core import gc_policy as gcp  # noqa: E402

OUT = Path(__file__).resolve().parents[1] / "frontend" / "lib" / "gcTables.generated.ts"

HEADER = """// GENERATED FILE -- DO NOT EDIT BY HAND.
//
// Produced by scripts/export_gc_tables.py from pcis/core/gc_policy.py, which
// is the only place a growing-charge rate may be changed. tests/test_gc_export.py
// fails if this file drifts from the engine.
//
// Source: IB Group GC Policy, EC Shed, valid for placements
// 16 October 2025 - 15 October 2026. Verified against settlement B924B95626.
"""


def main() -> None:
    lines = [HEADER, ""]

    lines.append("export const SHED_TYPES = [")
    for s in gcp.SHED_TYPES:
        lines.append(f'  "{s}",')
    lines.append("] as const;")
    lines.append("")
    lines.append("export type ShedType = (typeof SHED_TYPES)[number];")
    lines.append("")
    lines.append("/** The shed types to OFFER in a picker.")
    lines.append(" *")
    lines.append(" *  Narrower than SHED_TYPES on purpose: the Parivartan columns belong to")
    lines.append(" *  a separate scheme run by another company. They stay in the slab table")
    lines.append(" *  because the policy's own worked illustration is a Parivartan case and")
    lines.append(" *  validates the arithmetic -- they are simply not choices this farm's")
    lines.append(" *  growers can be on. */")
    lines.append("export const OFFERED_SHED_TYPES: ShedType[] = [")
    for s_ in gcp.OFFERED_SHED_TYPES:
        lines.append(f'  "{s_}",')
    lines.append("];")
    lines.append("")

    lines.append("/** The ONE settlement family these tables reproduce.")
    lines.append(" *")
    lines.append(" *  A crop from the other IB Group entity is wrong on the CBW denominator")
    lines.append(" *  AND the rate table at the same time, and reads HIGH. Show this. */")
    lines.append(f'export const POLICY_ENTITY = "{gcp.POLICY_ENTITY}";')
    lines.append(f'export const POLICY_START_ISO = "{gcp.POLICY_START_ISO}";')
    lines.append(f'export const POLICY_END_ISO = "{gcp.POLICY_END_ISO}";')
    lines.append("")
    lines.append("/** PLACEMENT date, not lift: lot B924B95625 (other entity, different rate")
    lines.append(" *  table) was LIFTED inside this window but PLACED eight days before it.")
    lines.append(" *  ISO strings sort chronologically, so a malformed date fails closed. */")
    lines.append("export function policyCovers(placementDateIso: string): boolean {")
    lines.append("  const d = (placementDateIso || '').trim().slice(0, 10);")
    lines.append("  if (d.length !== 10) return false;")
    lines.append("  return POLICY_START_ISO <= d && d <= POLICY_END_ISO;")
    lines.append("}")
    lines.append("")

    lines.append("/** Days before the window closes at which to start warning.")
    lines.append(" *")
    lines.append(" *  The rates changed COMPLETELY at the last transition, so a renewal must")
    lines.append(" *  not be assumed to continue these tables. */")
    lines.append(f"export const POLICY_EXPIRY_WARNING_DAYS = {gcp.POLICY_EXPIRY_WARNING_DAYS};")
    lines.append("")
    lines.append("export type PolicyStatus = 'current' | 'expiring' | 'expired';")
    lines.append("")
    lines.append("/** Evaluated against a date the caller supplies, so a build-time constant")
    lines.append(" *  can never freeze the tool into believing it is still current. */")
    lines.append("export function policyStatus(today: Date = new Date()): PolicyStatus {")
    lines.append("  const end = new Date(POLICY_END_ISO + 'T00:00:00');")
    lines.append("  const days = Math.floor((end.getTime() - today.getTime()) / 86400000);")
    lines.append("  if (days < 0) return 'expired';")
    lines.append("  if (days <= POLICY_EXPIRY_WARNING_DAYS) return 'expiring';")
    lines.append("  return 'current';")
    lines.append("}")
    lines.append("")
    lines.append("export function daysUntilPolicyEnds(today: Date = new Date()): number {")
    lines.append("  const end = new Date(POLICY_END_ISO + 'T00:00:00');")
    lines.append("  return Math.floor((end.getTime() - today.getTime()) / 86400000);")
    lines.append("}")
    lines.append("")
    lines.append("/** Mortality above this switches the CBW denominator to 95% of chicks housed. */")
    lines.append(f"export const CBW_MORTALITY_THRESHOLD_PCT = {gcp.CBW_MORTALITY_THRESHOLD_PCT};")
    lines.append(f"export const CBW_REFERENCE_KG = {gcp.CBW_REFERENCE_KG};")
    lines.append(f"export const CBW_CORRECTION = {gcp.CBW_CORRECTION};")
    lines.append("")

    lines.append("/** [upper bound of cFCR band, Rs per kg by shed type].")
    lines.append(" *  Read as 'cFCR at or below this bound pays this rate'. The last entry is")
    lines.append(" *  the cliff: above 1.800 the growing charge is zero, not merely reduced. */")
    lines.append("export const GC_SLABS: [number, Record<ShedType, number>][] = [")
    for upper, rates in gcp._GC_SLABS:  # noqa: SLF001 - this script is the exporter
        bound = "Infinity" if upper == float("inf") else f"{upper}"
        pairs = ", ".join(f'{k}: {v}' for k, v in rates.items())
        lines.append(f"  [{bound}, {{ {pairs} }}],")
    lines.append("];")
    lines.append("")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
