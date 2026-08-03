"use client";

/**
 * Mortality and expected payout, in one block.
 *
 * They belong together because they are the same story told twice. Deaths
 * are a welfare number until they cross 5%, at which point they become a
 * money number: the CBW denominator switches to 95% of chicks housed and
 * every further death drags corrected FCR upward. Showing mortality in one
 * card and the payout in another hides the mechanism that links them.
 *
 * The compressed form sits beside flock health; opening it shows how the
 * expected payout has moved across this crop.
 *
 * What the trend deliberately is NOT
 * ----------------------------------
 * A comparison across crops. This farm's nine settlements span four
 * incentive schemes and two legal entities in two years -- lot B95625 and
 * lot B95626 are five weeks apart and share neither the CBW rule nor the
 * rate table. A line joining their payouts would draw a trend where there
 * is only a change of contract, which is the most confident-looking way to
 * be wrong. Within a single crop every point is priced by the same
 * published table, so the movement means something.
 */

import { useCallback, useEffect, useState } from "react";
import { gcPosition, type GCPosition } from "@/lib/api";
import {
  getCropGCInputs, getDepletions, getCropInputHistory, getMortalityHistory,
  type CropGCInputs, type DepletionRow, type CropInputRow, type MortalityRow,
} from "@/lib/db";

const rupees = (n: number) => "Rs " + Math.round(n).toLocaleString("en-IN");

/** One priced point in this crop's history. */
type PayoutPoint = {
  at: string;
  cfcr: number;
  ratePerKg: number;
  rearingCharge: number;
};

export default function CropValueCard({
  flockId,
  chicksHoused,
  birdsAlive,
  cumulativeDead,
  ageDays,
  ceilingPct,
  onOpen,
}: {
  flockId: string;
  chicksHoused: number;
  birdsAlive: number;
  cumulativeDead: number;
  ageDays: number;
  /** EU 2007/43/EC ceiling for this age: 1% + 0.06% x days. */
  ceilingPct: number | null;
  onOpen: () => void;
}) {
  const [pos, setPos] = useState<GCPosition | null>(null);
  const [inputs, setInputs] = useState<CropGCInputs | null>(null);

  const load = useCallback(async () => {
    const [gi, dep] = await Promise.all([
      getCropGCInputs(flockId).catch(() => null),
      getDepletions(flockId).catch(() => [] as DepletionRow[]),
    ]);
    setInputs(gi);
    if (gi?.feed_consumed_kg == null || gi?.avg_weight_kg == null) return;
    try {
      setPos(
        await gcPosition({
          chicks_housed: gi.chicks_housed,
          birds_alive: birdsAlive,
          avg_weight_kg: gi.avg_weight_kg,
          feed_consumed_kg: gi.feed_consumed_kg,
          shed_type: gi.shed_type ?? "other_ec",
          depleted_birds: gi.depleted_birds ?? 0,
          depleted_weight_kg: gi.depleted_weight_kg ?? 0,
        })
      );
    } catch {
      setPos(null);
    }
    void dep;
  }, [flockId, birdsAlive]);

  useEffect(() => { void load(); }, [load]);

  const mortalityPct = chicksHoused > 0 ? (100 * cumulativeDead) / chicksHoused : 0;
  const overCeiling = ceilingPct != null && mortalityPct > ceilingPct;
  const overCbwThreshold = mortalityPct > 5;

  return (
    <div
      className="tile"
      onClick={onOpen}
      style={{ cursor: "pointer", marginTop: 14 }}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") onOpen(); }}
    >
      <div className="tile-head">
        <div className="tile-title">Crop value</div>
        <div className="cap">mortality + expected payout</div>
      </div>

      <div style={{ display: "flex", gap: 18, flexWrap: "wrap", alignItems: "flex-end" }}>
        {/* Mortality first: it is the input, and above 5% it stops being
            only a welfare figure and starts moving the money. */}
        <div>
          <div className="k muted" style={{ fontSize: 11 }}>Mortality</div>
          <div
            style={{
              fontSize: 24, fontWeight: 800, letterSpacing: -0.6,
              color: overCeiling ? "var(--danger)" : overCbwThreshold ? "var(--warn)" : "var(--ink)",
            }}
          >
            {mortalityPct.toFixed(2)}%
          </div>
          <div style={{ fontSize: 11, color: "var(--ink-dim)" }}>
            {cumulativeDead.toLocaleString("en-IN")} birds
            {ceilingPct != null ? ` · EU limit ${ceilingPct.toFixed(2)}%` : ""}
          </div>
        </div>

        <div style={{ marginLeft: "auto", textAlign: "right" }}>
          <div className="k muted" style={{ fontSize: 11 }}>Expected payout</div>
          {pos && !pos.incomplete_reason ? (
            <>
              <div style={{ fontSize: 24, fontWeight: 800, letterSpacing: -0.6 }}>
                {rupees(pos.rearing_charge)}
              </div>
              <div style={{ fontSize: 11, color: "var(--ink-dim)" }}>
                Rs {pos.rate_per_kg.toFixed(2)}/kg · cFCR {pos.cfcr.toFixed(3)}
              </div>
            </>
          ) : (
            <>
              <div style={{ fontSize: 17, fontWeight: 700, color: "var(--ink-muted)" }}>—</div>
              <div style={{ fontSize: 11, color: "var(--ink-dim)", maxWidth: 210 }}>
                {pos?.incomplete_reason
                  ? "lift weight missing"
                  : inputs?.feed_consumed_kg == null
                    ? "enter feed + weight"
                    : "engine unreachable"}
              </div>
            </>
          )}
        </div>
      </div>

      {/* The link between the two halves, stated only when it is live. */}
      {overCbwThreshold && (
        <div style={{ marginTop: 10, fontSize: 11, color: "var(--warn)", lineHeight: 1.5 }}>
          Above 5%: corrected body weight now divides by 95% of chicks housed, so every
          further death raises cFCR and can cost a slab.
        </div>
      )}

      <div style={{ marginTop: 10, fontSize: 11, color: "var(--ink-dim)" }}>
        ✎ payout uses hand-entered feed and weight · tap for the trend
      </div>
      <div style={{ fontSize: 10.5, color: "var(--ink-dim)", marginTop: 2 }}>
        day {ageDays} · {birdsAlive.toLocaleString("en-IN")} birds in house
      </div>
    </div>
  );
}

/**
 * The expanded view: how the expected payout has moved across this crop.
 *
 * Each point re-prices the crop from one feed/weight entry, so the line
 * shows what the contract would have paid had the crop been lifted that
 * day. It is a history of positions, not a forecast -- weight rises and
 * FCR worsens as a crop ages, and both move cFCR in opposite directions.
 */
export function CropValueDetail({
  flockId,
  chicksHoused,
  birdsAlive,
  depletedBirds,
  depletedWeightKg,
}: {
  flockId: string;
  chicksHoused: number;
  birdsAlive: number;
  depletedBirds: number;
  depletedWeightKg: number | null;
}) {
  const [points, setPoints] = useState<PayoutPoint[] | null>(null);
  const [deaths, setDeaths] = useState<MortalityRow[]>([]);
  const [rows, setRows] = useState<CropInputRow[]>([]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const [hist, mort] = await Promise.all([
        getCropInputHistory(flockId),
        getMortalityHistory(flockId),
      ]);
      if (cancelled) return;
      setRows(hist);
      setDeaths(mort);

      // Price each historical entry through the SAME engine endpoint the
      // live card uses, so the trend cannot drift from the headline.
      const priced: PayoutPoint[] = [];
      for (const r of hist) {
        try {
          const p = await gcPosition({
            chicks_housed: chicksHoused,
            birds_alive: birdsAlive,
            avg_weight_kg: r.avg_weight_kg,
            feed_consumed_kg: r.feed_consumed_kg,
            shed_type: r.shed_type,
            depleted_birds: depletedBirds,
            depleted_weight_kg: depletedWeightKg ?? 0,
          });
          if (!p.incomplete_reason) {
            priced.push({
              at: r.entered_at,
              cfcr: p.cfcr,
              ratePerKg: p.rate_per_kg,
              rearingCharge: p.rearing_charge,
            });
          }
        } catch {
          /* one bad point must not empty the chart */
        }
      }
      if (!cancelled) setPoints(priced);
    })();
    return () => { cancelled = true; };
  }, [flockId, chicksHoused, birdsAlive, depletedBirds, depletedWeightKg]);

  if (points === null) {
    return <div className="muted" style={{ fontSize: 13 }}>Pricing this crop's history…</div>;
  }

  if (points.length === 0) {
    return (
      <div className="muted" style={{ fontSize: 13, lineHeight: 1.6 }}>
        No priced history yet. Each time you record feed and sample weight, this crop
        gets another point — the line then shows what the contract would have paid had
        the crop been lifted on each of those days.
        {rows.length > 0 && " Entries exist but could not be priced; a lift with no recorded weight will do that."}
      </div>
    );
  }

  const maxCharge = Math.max(...points.map((p) => p.rearingCharge));
  const minCharge = Math.min(...points.map((p) => p.rearingCharge));
  const span = Math.max(1, maxCharge - minCharge);
  const totalDeaths = deaths.reduce((a, d) => a + d.dead, 0);

  return (
    <>
      <p className="muted" style={{ fontSize: 13, lineHeight: 1.6, marginTop: 0 }}>
        What the contract would have paid had this crop been lifted on each entry date.
        A <b>position</b> at that moment, not a forecast — weight rises and FCR worsens
        as a crop ages, and the two move corrected FCR in opposite directions.
      </p>

      <div className="stats" style={{ marginTop: 14 }}>
        <div className="stat">
          <div className="k">Latest position</div>
          <div className="v">{rupees(points[points.length - 1].rearingCharge)}</div>
        </div>
        <div className="stat">
          <div className="k">Rate now</div>
          <div className="v">Rs {points[points.length - 1].ratePerKg.toFixed(2)}<span className="u"> /kg</span></div>
        </div>
        <div className="stat">
          <div className="k">cFCR now</div>
          <div className="v">{points[points.length - 1].cfcr.toFixed(3)}</div>
        </div>
        <div className="stat">
          <div className="k">Deaths logged</div>
          <div className="v">{totalDeaths.toLocaleString("en-IN")}</div>
        </div>
      </div>

      {/* Deliberately a bar per entry rather than a smooth line: the points
          are irregularly spaced (whenever someone weighed birds), and a
          smoothed curve would imply readings on days nobody measured. */}
      <div style={{ marginTop: 18 }}>
        <div className="cap">Expected payout by entry</div>
        <div style={{ display: "flex", alignItems: "flex-end", gap: 8, height: 150, marginTop: 12 }}>
          {points.map((p, i) => {
            const h = 24 + (110 * (p.rearingCharge - minCharge)) / span;
            return (
              <div key={i} style={{ flex: 1, textAlign: "center", minWidth: 34 }}>
                <div style={{ fontSize: 10, color: "var(--ink-dim)", marginBottom: 4 }}>
                  {(p.rearingCharge / 1000).toFixed(0)}k
                </div>
                <div
                  title={`${rupees(p.rearingCharge)} · Rs ${p.ratePerKg.toFixed(2)}/kg · cFCR ${p.cfcr.toFixed(3)}`}
                  style={{
                    height: h, borderRadius: "8px 8px 0 0",
                    background: "linear-gradient(180deg, var(--teal), rgba(20,184,166,0.25))",
                  }}
                />
                <div style={{ fontSize: 10, color: "var(--ink-dim)", marginTop: 5 }}>
                  {new Date(p.at).toLocaleDateString("en-IN", { day: "numeric", month: "short" })}
                </div>
              </div>
            );
          })}
        </div>
      </div>

      <div style={{ marginTop: 16, fontSize: 11.5, color: "var(--ink-dim)", lineHeight: 1.6 }}>
        Rearing charge only — settlements add rate, body-weight and brooding incentives
        whose formulae are not published, so the real payment is higher (about a fifth,
        on the last settled crop). Priced on the IB Group slab table for
        placements 16.10.2025–15.10.2026; earlier crops were paid under different
        contracts and are not comparable, which is why only this crop is shown.
      </div>
    </>
  );
}
