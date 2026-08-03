"use client";

/**
 * Public growing-charge calculator.
 *
 * Deliberately the opposite of the dashboard in almost every way:
 *
 *   - no login, no farm record, no database write
 *   - no sensor, no backend call, no cold start
 *   - five numbers a grower already has on the settlement slip
 *
 * Everything runs in the browser from a slab table generated out of the
 * cited engine (see lib/gcPolicy.ts). That matters for the audience: this
 * is meant to be opened from a WhatsApp link on a phone with two bars of
 * signal, and an answer that takes ten seconds to arrive is an answer
 * nobody sees.
 *
 * What it must never do is overstate itself. It computes the REARING
 * CHARGE from a published policy. It is not a prediction, not a profit,
 * and not the whole settlement -- incentives sit on top and their formulae
 * are not published. Those caveats are shown with the number, not hidden
 * behind a link, because a farmer comparing this against a real slip will
 * otherwise conclude the tool is wrong.
 */

import { useMemo, useState } from "react";
import {
  assess, OFFERED_SHED_TYPES, policyCovers,
  POLICY_ENTITY, POLICY_START_ISO, POLICY_END_ISO,
  policyStatus, daysUntilPolicyEnds,
  type ShedType,
} from "@/lib/gcPolicy";

/** Labels for the shed types a grower under this contract can be on.
 *  The Parivartan columns are a different company's scheme and are not
 *  offered -- see OFFERED_SHED_TYPES. */
const SHED_LABELS: Partial<Record<ShedType, string>> = {
  other_basic_ec: "Basic EC",
  other_semi_ec: "Semi EC",
  other_ec: "EC",
};

/** Indian broiler feed is normally delivered in 50 kg bags. The bag size is
 *  stated on screen rather than assumed silently -- a grower whose bags are
 *  a different weight must be able to see why the number looks wrong. */
const BAG_KG = 50;

const rupees = (n: number) =>
  "Rs " + Math.round(n).toLocaleString("en-IN");

export default function GCCalculatorPage() {
  const [housed, setHoused] = useState("");
  const [lifted, setLifted] = useState("");
  const [weight, setWeight] = useState("");
  const [feed, setFeed] = useState("");
  const [feedUnit, setFeedUnit] = useState<"kg" | "bags">("kg");
  const [shed, setShed] = useState<ShedType>("other_ec");
  // PLACEMENT, not lift: the other entity's crop was lifted inside this
  // window but placed before it, so only the placement date catches it.
  const [placementDate, setPlacementDate] = useState("");

  const n = (s: string) => {
    const v = Number(s.replace(/,/g, "").trim());
    return Number.isFinite(v) ? v : 0;
  };

  const feedKg = feedUnit === "bags" ? n(feed) * BAG_KG : n(feed);
  const ready = n(housed) > 0 && n(lifted) > 0 && n(weight) > 0 && feedKg > 0;

  const result = useMemo(
    () => (ready ? assess(n(housed), n(lifted), n(weight), feedKg, shed) : null),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [housed, lifted, weight, feedKg, shed, ready]
  );

  // Computed at render, never at build: a constant baked in at deploy
  // time would leave the page permanently claiming the tables are current.
  const status = policyStatus();
  const daysLeft = daysUntilPolicyEnds();

  const impliedAvg =
    n(lifted) > 0 && n(weight) > 0 ? n(weight) / n(lifted) : null;

  return (
    <main style={{ maxWidth: 720, margin: "0 auto", padding: "28px 18px 64px" }}>
      <h1 style={{ fontSize: 25, fontWeight: 800, letterSpacing: -0.7, margin: 0 }}>
        Growing charge calculator
      </h1>
      <p className="muted" style={{ fontSize: 13.5, lineHeight: 1.55, marginTop: 8 }}>
        Works out your Rs/kg rate under the IB Group GC policy, and — more useful —
        how far your corrected FCR is from the next slab boundary. Nothing is sent
        anywhere; the whole calculation runs on your phone.
      </p>

      {/* Scope, stated before any number rather than in small print at the
          bottom. A crop from the other IB Group entity comes out wrong on
          the CBW denominator and the rate table simultaneously, and reads
          HIGH -- so this has to be the first thing read, not the last. */}
      <div
        style={{
          marginTop: 16, padding: 12, borderRadius: 12,
          border: "1px solid rgba(56,189,248,0.32)", background: "rgba(56,189,248,0.07)",
          fontSize: 12, lineHeight: 1.55,
        }}
      >
        <b>For {POLICY_ENTITY} crops only</b>, placements{" "}
        {POLICY_START_ISO.split("-").reverse().join(".")} to{" "}
        {POLICY_END_ISO.split("-").reverse().join(".")}. Other IB Group entities pay on a
        different rate table and a different CBW rule — this will read too high for them.
        Check the company name printed at the top of your slip.
      </div>

      {/* The tables have a stated end date and the previous transition
          changed the rates COMPLETELY -- a renewal cannot be assumed to
          continue them. So the page says when it is about to go stale
          rather than quietly carrying on quoting expired numbers. */}
      {status !== "current" && (
        <div
          style={{
            marginTop: 10, padding: 12, borderRadius: 12,
            border: `1px solid ${status === "expired" ? "rgba(239,68,68,0.45)" : "rgba(251,146,60,0.4)"}`,
            background: status === "expired" ? "rgba(239,68,68,0.09)" : "rgba(251,146,60,0.08)",
            fontSize: 12, lineHeight: 1.55,
          }}
        >
          {status === "expired" ? (
            <>
              <b>These rates have expired.</b> The policy period ended{" "}
              {POLICY_END_ISO.split("-").reverse().join(".")}. When this contract last
              changed hands the entire rate table changed with it, so do not assume these
              slabs carried over — get the current policy document before relying on any
              figure below.
            </>
          ) : (
            <>
              <b>This policy period ends in {daysLeft} days</b> (
              {POLICY_END_ISO.split("-").reverse().join(".")}). Crops placed after that are
              priced by a document nobody has yet. Worth asking your field officer for the
              renewal now — last time, every rate changed.
            </>
          )}
        </div>
      )}

      <div className="tile" style={{ marginTop: 14 }}>
        <div style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
          <Field label="Chicks housed" value={housed} onChange={setHoused} />
          <Field label="Birds lifted" value={lifted} onChange={setLifted} />
          <Field label="Total weight lifted (kg)" value={weight} onChange={setWeight} wide />
        </div>

        <div style={{ display: "flex", gap: 12, flexWrap: "wrap", marginTop: 4 }}>
          <div>
            <label style={{ marginTop: 0 }}>Feed consumed</label>
            <div style={{ display: "flex", gap: 8 }}>
              <input
                inputMode="decimal"
                value={feed}
                onChange={(e) => setFeed(e.target.value)}
                style={{ width: 130 }}
              />
              <select
                value={feedUnit}
                onChange={(e) => setFeedUnit(e.target.value as "kg" | "bags")}
                style={{ width: 120 }}
              >
                <option value="kg">kg</option>
                <option value="bags">bags ({BAG_KG} kg)</option>
              </select>
            </div>
          </div>
          <div>
            <label style={{ marginTop: 0 }}>Placement date (optional)</label>
            <input
              type="date"
              value={placementDate}
              onChange={(e) => setPlacementDate(e.target.value)}
              style={{ width: 165 }}
            />
          </div>
          <div>
            <label style={{ marginTop: 0 }}>Shed type</label>
            <select
              value={shed}
              onChange={(e) => setShed(e.target.value as ShedType)}
              style={{ width: 210 }}
            >
              {OFFERED_SHED_TYPES.map((s) => (
                <option key={s} value={s}>{SHED_LABELS[s] ?? s}</option>
              ))}
            </select>
          </div>
        </div>

        {/* The shed type is the one input with no sanity check available:
            a wrong choice produces a perfectly plausible number that is up
            to 16% out. Saying so is the only defence. */}
        <div style={{ fontSize: 11, color: "var(--ink-dim)", marginTop: 10, lineHeight: 1.5 }}>
          Shed type must match your contract — the same corrected FCR pays up to 16%
          differently across shed types, and nothing here can detect a wrong choice.
          {impliedAvg ? ` · That weight works out to ${impliedAvg.toFixed(3)} kg per bird.` : ""}
        </div>
      </div>

      {!ready && (
        <div className="muted" style={{ fontSize: 13, marginTop: 18, lineHeight: 1.6 }}>
          Fill in all five figures to see the rate. They are all on your settlement
          slip, or on the lifting slip plus your feed record.
        </div>
      )}

      {placementDate && !policyCovers(placementDate) && (
        <div
          style={{
            marginTop: 16, padding: 13, borderRadius: 12,
            border: "1px solid rgba(239,68,68,0.4)", background: "rgba(239,68,68,0.08)",
            fontSize: 12.5, lineHeight: 1.55, color: "var(--ink)",
          }}
        >
          <b>That placement date is outside this policy period.</b> Crops placed before{" "}
          {POLICY_START_ISO.split("-").reverse().join(".")} were paid under earlier
          contracts with different slab rates — on this farm&apos;s own older settlements
          these tables overstate the rearing charge by Rs 1–2 lakh. The figure below does
          not apply to that crop.
        </div>
      )}

      {result && (
        <div className="tile" style={{ marginTop: 16 }}>
          <div style={{ display: "flex", alignItems: "flex-end", gap: 16, flexWrap: "wrap" }}>
            <div>
              <div className="cap">Growing charge</div>
              <div style={{ fontSize: 38, fontWeight: 800, letterSpacing: -1.4, lineHeight: 1.1 }}>
                Rs {result.ratePerKg.toFixed(2)}
                <span style={{ fontSize: 16, fontWeight: 500, color: "var(--ink-muted)" }}>/kg</span>
              </div>
              <div style={{ fontSize: 13, color: "var(--ink-muted)", marginTop: 4 }}>
                {rupees(result.rearingCharge)} on{" "}
                {result.totalWeightKg.toLocaleString("en-IN")} kg
              </div>
            </div>
            <div
              style={{
                marginLeft: "auto", textAlign: "right",
                fontSize: 12.5, color: "var(--ink-muted)", lineHeight: 1.7,
              }}
            >
              <div>
                corrected FCR{" "}
                <b style={{ color: "var(--ink)", fontSize: 14 }}>{result.cfcr.toFixed(3)}</b>
              </div>
              <div>FCR {result.fcr.toFixed(3)} · CBW {result.cbwKg.toFixed(3)} kg</div>
              <div>
                mortality{" "}
                <span style={{ color: result.cbwPenalised ? "var(--warn)" : "var(--ink-muted)" }}>
                  {result.mortalityPct.toFixed(2)}%
                </span>
              </div>
            </div>
          </div>

          {/* The reason this tool is worth opening. cFCR alone does not tell
              a grower they are one bad day from losing a slab. */}
          {result.distance.marginToWorseCfcr !== null && result.distance.lossPerKg ? (
            <div
              style={{
                marginTop: 16, padding: 13, borderRadius: 12,
                border: "1px solid var(--line)", background: "rgba(255,255,255,0.02)",
              }}
            >
              <div style={{ display: "flex", justifyContent: "space-between", gap: 10, fontSize: 12.5 }}>
                <span className="muted">Margin before the rate drops</span>
                <b
                  style={{
                    color:
                      result.distance.marginToWorseCfcr < 0.02 ? "var(--warn)" : "var(--ink)",
                  }}
                >
                  {result.distance.marginToWorseCfcr.toFixed(3)} cFCR
                </b>
              </div>
              <div style={{ fontSize: 11.5, color: "var(--ink-dim)", marginTop: 6, lineHeight: 1.5 }}>
                Crossing it costs Rs {result.distance.lossPerKg.toFixed(2)}/kg —{" "}
                {rupees(result.distance.lossPerKg * result.totalWeightKg)} on this crop.
              </div>
              {result.distance.gainPerKg && result.distance.nextBetterCfcr ? (
                <div style={{ fontSize: 11.5, color: "var(--ink-dim)", marginTop: 5, lineHeight: 1.5 }}>
                  Reaching cFCR {result.distance.nextBetterCfcr.toFixed(3)} would pay Rs{" "}
                  {result.distance.gainPerKg.toFixed(2)}/kg more —{" "}
                  {rupees(result.distance.gainPerKg * result.totalWeightKg)}.
                </div>
              ) : null}
            </div>
          ) : null}

          <ul style={{ marginTop: 14, paddingLeft: 17 }}>
            {result.notes.map((note, i) => (
              <li
                key={i}
                style={{ fontSize: 11.5, color: "var(--ink-dim)", lineHeight: 1.6, marginTop: 6 }}
              >
                {note}
              </li>
            ))}
          </ul>
        </div>
      )}

      <div
        style={{
          marginTop: 22, fontSize: 11, color: "var(--ink-dim)",
          lineHeight: 1.65, borderTop: "1px solid var(--line)", paddingTop: 14,
        }}
      >
        Slab rates from the IB Group GC Policy (EC Shed), placements 16 Oct 2025 –
        15 Oct 2026. Check the rate against your own contract before relying on it.
        This is a calculator for a published formula, not financial advice, and not
        affiliated with IB Group.
      </div>
    </main>
  );
}

function Field({
  label,
  value,
  onChange,
  wide,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  wide?: boolean;
}) {
  return (
    <div>
      <label style={{ marginTop: 0 }}>{label}</label>
      <input
        inputMode="decimal"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        style={{ width: wide ? 200 : 150 }}
      />
    </div>
  );
}
