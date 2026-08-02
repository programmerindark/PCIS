"use client";

/**
 * Growing charge: what the contract pays for this crop, today.
 *
 * This is the only place on the dashboard that shows money, and it behaves
 * differently from everything around it on purpose.
 *
 * Every other tile is fed by a sensor reading a minute old. This one is
 * fed by two numbers a person types in — feed consumed and sample weight —
 * so it always displays HOW OLD they are. A three-week-old weight rendered
 * beside a live temperature looks equally current, and prices the crop
 * wrongly without ever looking wrong.
 *
 * It also refuses to show a rupee figure when it cannot stand behind one.
 * If birds have been lifted and nobody recorded their weight, the feed
 * those birds ate is already in the crop total while their kilograms are
 * missing, so FCR is overstated and the crop grades into a worse slab.
 * Rather than estimate the missing weight from a growth curve — the exact
 * kind of invented number this codebase forbids — the card says what it
 * needs and shows nothing until it has it.
 */

import { useCallback, useEffect, useState } from "react";
import { gcPosition, type GCPosition } from "@/lib/api";
import {
  getCropGCInputs, saveCropInputs, getDepletions, setDepletionWeight,
  type CropGCInputs, type DepletionRow,
} from "@/lib/db";

/** Only the columns this farm's contract can be on. The Parivartan
 *  columns remain in the engine's slab table (the policy's own worked
 *  illustration is a Parivartan case and validates the arithmetic) but
 *  they are a different company's scheme, so offering them here would add
 *  three ways to pick a wrong answer and none to pick a right one. */
const SHED_TYPES: { value: string; label: string }[] = [
  { value: "other_basic_ec", label: "Basic EC" },
  { value: "other_semi_ec", label: "Semi EC" },
  { value: "other_ec", label: "EC" },
];

/** "today" / "3 days ago" — staleness is the point, so it is never hidden. */
function enteredAgo(iso: string | null): { text: string; stale: boolean } {
  if (!iso) return { text: "never", stale: true };
  const days = Math.floor((Date.now() - new Date(iso).getTime()) / 86_400_000);
  if (days <= 0) return { text: "today", stale: false };
  if (days === 1) return { text: "yesterday", stale: false };
  // Broilers gain roughly 60-70 g/day near market age, so a weight more
  // than three days old is materially wrong, not merely old.
  return { text: `${days} days ago`, stale: days > 3 };
}

const rupees = (n: number) =>
  "Rs " + n.toLocaleString("en-IN", { maximumFractionDigits: 0 });

export default function GCCard({
  flockId,
  birdsAlive,
}: {
  flockId: string;
  birdsAlive: number;
}) {
  const [inputs, setInputs] = useState<CropGCInputs | null>(null);
  const [lifts, setLifts] = useState<DepletionRow[]>([]);
  const [pos, setPos] = useState<GCPosition | null>(null);
  const [editing, setEditing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const [feed, setFeed] = useState("");
  const [weight, setWeight] = useState("");
  const [shed, setShed] = useState("other_ec");

  const load = useCallback(async () => {
    const [gi, dep] = await Promise.all([getCropGCInputs(flockId), getDepletions(flockId)]);
    setInputs(gi);
    setLifts(dep);
    if (gi?.feed_consumed_kg != null && gi?.avg_weight_kg != null) {
      setFeed(String(gi.feed_consumed_kg));
      setWeight(String(gi.avg_weight_kg));
      setShed(gi.shed_type ?? "other_ec");
      try {
        setPos(
          await gcPosition({
            chicks_housed: gi.chicks_housed,
            birds_alive: birdsAlive,
            avg_weight_kg: gi.avg_weight_kg,
            feed_consumed_kg: gi.feed_consumed_kg,
            shed_type: gi.shed_type ?? "other_ec",
            depleted_birds: gi.depleted_birds ?? 0,
            // NULL here means some lift is missing its weight. Sending 0
            // rather than omitting it is what triggers the engine's
            // refusal to price the crop, which is the behaviour we want
            // surfaced rather than papered over.
            depleted_weight_kg: gi.depleted_weight_kg ?? 0,
          })
        );
        setErr(null);
      } catch (e: any) {
        setErr(e?.message ?? "engine unreachable");
      }
    }
  }, [flockId, birdsAlive]);

  useEffect(() => {
    void load();
  }, [load]);

  async function save() {
    const f = Number(feed), w = Number(weight);
    if (!Number.isFinite(f) || f < 0 || !Number.isFinite(w) || w <= 0) {
      setErr("Enter feed in kg and average weight in kg.");
      return;
    }
    setBusy(true);
    try {
      await saveCropInputs(flockId, f, w, shed);
      setEditing(false);
      await load();
    } catch (e: any) {
      setErr(e?.message ?? "could not save");
    } finally {
      setBusy(false);
    }
  }

  async function saveLiftWeight(id: number, kg: number) {
    setBusy(true);
    try {
      await setDepletionWeight(id, kg);
      await load();
    } finally {
      setBusy(false);
    }
  }

  const age = enteredAgo(inputs?.entered_at ?? null);
  const missingLiftWeight = lifts.filter((l) => l.weight_kg == null && l.birds > 0);
  const hasInputs = inputs?.feed_consumed_kg != null && inputs?.avg_weight_kg != null;

  return (
    <div className="tile" style={{ marginTop: 14 }}>
      <div className="tile-head">
        <div className="tile-title">Growing charge</div>
        <div className="cap">IB Group GC policy</div>
      </div>

      {/* Provenance first. Every figure below comes from typed numbers, not
          sensors, and the card says so before showing any of them. */}
      <div style={{ fontSize: 11, color: "var(--ink-dim)", marginTop: -4 }}>
        ✎ entered by hand ·{" "}
        <span style={{ color: age.stale ? "var(--warn)" : "var(--ink-muted)" }}>{age.text}</span>
        {age.stale && hasInputs ? " — reweigh to price this accurately" : ""}
      </div>

      {!hasInputs && !editing && (
        <div style={{ marginTop: 12 }}>
          <div style={{ fontSize: 13, color: "var(--ink-muted)", lineHeight: 1.5 }}>
            No feed or weight recorded yet. The contract prices on corrected FCR,
            which needs both — and nothing on the farm measures them.
          </div>
          <button
            onClick={() => setEditing(true)}
            style={{ marginTop: 10, maxWidth: 210 }}
          >
            Enter feed and weight
          </button>
        </div>
      )}

      {editing && (
        <div style={{ marginTop: 12 }}>
          <div style={{ display: "flex", gap: 9, flexWrap: "wrap", alignItems: "end" }}>
            <div>
              <label style={{ marginTop: 0 }}>Feed to date (kg)</label>
              <input
                inputMode="decimal"
                value={feed}
                onChange={(e) => setFeed(e.target.value)}
                style={{ width: 140 }}
              />
            </div>
            <div>
              <label style={{ marginTop: 0 }}>Average weight (kg)</label>
              <input
                inputMode="decimal"
                value={weight}
                onChange={(e) => setWeight(e.target.value)}
                style={{ width: 140 }}
              />
            </div>
            <div>
              <label style={{ marginTop: 0 }}>Shed type</label>
              <select value={shed} onChange={(e) => setShed(e.target.value)} style={{ width: 190 }}>
                {SHED_TYPES.map((s) => (
                  <option key={s.value} value={s.value}>{s.label}</option>
                ))}
              </select>
            </div>
            <button className="primary" onClick={save} disabled={busy} style={{ maxWidth: 90, margin: 0 }}>
              {busy ? "Saving…" : "Save"}
            </button>
            <button onClick={() => setEditing(false)} style={{ maxWidth: 90, margin: 0 }}>
              Cancel
            </button>
          </div>
          {/* Worth its own warning: the same cFCR pays Rs 12.75 to Rs 14.75/kg
              across shed types. Choosing the wrong column is a 16% error that
              nothing downstream can detect. */}
          <div style={{ fontSize: 11, color: "var(--ink-dim)", marginTop: 8 }}>
            Shed type must match your contract — the same corrected FCR pays up to
            16% differently across shed types.
          </div>
        </div>
      )}

      {/* A lift with no recorded weight blocks the entire calculation. */}
      {missingLiftWeight.length > 0 && (
        <div
          style={{
            marginTop: 12, padding: 12, borderRadius: 12,
            border: "1px solid rgba(251,146,60,0.35)", background: "rgba(251,146,60,0.08)",
          }}
        >
          <div style={{ fontSize: 12, color: "var(--warn)", lineHeight: 1.5 }}>
            Lift weight missing. Those birds were delivered, not lost — without their
            kilograms the feed they ate inflates FCR and grades the crop into a worse slab.
          </div>
          {missingLiftWeight.map((l) => (
            <LiftWeightRow key={l.id} lift={l} busy={busy} onSave={saveLiftWeight} />
          ))}
        </div>
      )}

      {err && <div style={{ marginTop: 10, fontSize: 12, color: "var(--danger)" }}>{err}</div>}

      {pos?.incomplete_reason && (
        <div
          style={{
            marginTop: 12, padding: 12, borderRadius: 12,
            border: "1px solid var(--line)", fontSize: 12,
            color: "var(--ink-muted)", lineHeight: 1.55,
          }}
        >
          {pos.incomplete_reason}
        </div>
      )}

      {pos && !pos.incomplete_reason && (
        <>
          <div style={{ display: "flex", alignItems: "flex-end", gap: 16, marginTop: 14, flexWrap: "wrap" }}>
            <div>
              <div style={{ fontSize: 30, fontWeight: 800, letterSpacing: -1 }}>
                Rs {pos.rate_per_kg.toFixed(2)}
                <span style={{ fontSize: 15, fontWeight: 500, color: "var(--ink-muted)" }}>/kg</span>
              </div>
              <div style={{ fontSize: 12, color: "var(--ink-muted)", marginTop: 2 }}>
                {rupees(pos.rearing_charge)} on {pos.total_weight_kg.toLocaleString("en-IN")} kg
              </div>
            </div>
            <div style={{ marginLeft: "auto", textAlign: "right", fontSize: 12, color: "var(--ink-muted)", lineHeight: 1.6 }}>
              <div>cFCR <b style={{ color: "var(--ink)" }}>{pos.cfcr.toFixed(3)}</b></div>
              <div>FCR {pos.fcr.toFixed(3)} · CBW {pos.cbw_kg.toFixed(3)} kg</div>
              <div>mortality {pos.mortality_pct.toFixed(2)}%</div>
            </div>
          </div>

          {/* The slab margin is the actionable part. cFCR on its own does not
              tell an operator they are one bad day from a cliff. */}
          {pos.slab.margin_to_worse_cfcr != null && pos.slab.loss_per_kg ? (
            <div
              style={{
                marginTop: 12, padding: 12, borderRadius: 12,
                border: "1px solid var(--line)", background: "rgba(255,255,255,0.02)",
              }}
            >
              <div style={{ display: "flex", justifyContent: "space-between", fontSize: 12 }}>
                <span className="muted">Margin before the rate drops</span>
                <b style={{ color: pos.slab.margin_to_worse_cfcr < 0.02 ? "var(--warn)" : "var(--ink)" }}>
                  {pos.slab.margin_to_worse_cfcr.toFixed(3)} cFCR
                </b>
              </div>
              <div style={{ fontSize: 11, color: "var(--ink-dim)", marginTop: 5 }}>
                Crossing it costs Rs {pos.slab.loss_per_kg.toFixed(2)}/kg —{" "}
                {rupees(pos.slab.loss_per_kg * pos.total_weight_kg)} on this crop.
              </div>
            </div>
          ) : null}

          {pos.cbw_penalised && (
            <div style={{ marginTop: 9, fontSize: 11, color: "var(--warn)", lineHeight: 1.5 }}>
              Mortality is above {pos.mortality_threshold_pct}% — CBW now divides by 95% of
              chicks housed, so every further death moves cFCR.
            </div>
          )}

          <ul style={{ marginTop: 11, paddingLeft: 16 }}>
            {pos.notes.map((n, i) => (
              <li key={i} style={{ fontSize: 11, color: "var(--ink-dim)", lineHeight: 1.55, marginTop: 4 }}>
                {n}
              </li>
            ))}
          </ul>

          {!editing && (
            <button onClick={() => setEditing(true)} style={{ marginTop: 10, maxWidth: 190 }}>
              Update feed / weight
            </button>
          )}
        </>
      )}
    </div>
  );
}

function LiftWeightRow({
  lift,
  busy,
  onSave,
}: {
  lift: DepletionRow;
  busy: boolean;
  onSave: (id: number, kg: number) => void;
}) {
  const [kg, setKg] = useState("");
  return (
    <div style={{ display: "flex", gap: 9, alignItems: "center", marginTop: 9, flexWrap: "wrap" }}>
      <span style={{ fontSize: 12, color: "var(--ink-muted)" }}>
        {lift.removed_on} · {lift.birds.toLocaleString("en-IN")} birds
      </span>
      <input
        inputMode="decimal"
        value={kg}
        onChange={(e) => setKg(e.target.value)}
        placeholder="total kg"
        style={{ width: 120 }}
      />
      <button
        disabled={busy || !(Number(kg) > 0)}
        onClick={() => onSave(lift.id, Number(kg))}
        style={{ maxWidth: 80, margin: 0 }}
      >
        Save
      </button>
    </div>
  );
}
