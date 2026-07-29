"use client";

// Model validation page — how well PCIS's predictions match this house.
//
// The reason this page exists: every confidence number the engine reports
// today is one I assigned from how well-sourced the inputs are. That is a
// defensible starting point but it is not evidence. Once the cron has
// logged enough paired predictions and measurements, the error on THIS
// house becomes measurable, and an assigned confidence can be replaced by
// an earned one.

import { useEffect, useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import { supabase } from "@/lib/supabaseClient";
import { getMyFarm, getHouses } from "@/lib/db";
import AppShell from "@/components/AppShell";
import { ValidationChart } from "@/components/ValidationChart";
import {
  getValidationHistory, errorStats, type ValidationPair, type ErrorStats,
} from "@/lib/validation";
import type { Farm, House } from "@/lib/types";

const WINDOWS = [
  { label: "24 hours", hours: 24 },
  { label: "7 days", hours: 168 },
  { label: "30 days", hours: 720 },
];

function StatBlock({
  stats, unit, decimals,
}: { stats: ErrorStats | null; unit: string; decimals: number }) {
  if (!stats) {
    return <div className="muted" style={{ fontSize: 13 }}>No paired data in this window yet.</div>;
  }
  const f = (v: number) => `${v > 0 ? "+" : ""}${v.toFixed(decimals)}${unit}`;
  return (
    <div className="stats" style={{ marginTop: 12 }}>
      <div className="stat">
        <div className="k">Typical miss</div>
        <div className="v">{stats.mae.toFixed(decimals)}<span className="u"> {unit}</span></div>
        <div className="u" style={{ fontSize: 10.5 }}>mean absolute error</div>
      </div>
      <div className="stat">
        <div className="k">Bias</div>
        <div className="v">{f(stats.bias)}</div>
        <div className="u" style={{ fontSize: 10.5 }}>
          {Math.abs(stats.bias) < stats.mae / 2 ? "noisy, not skewed" : stats.bias > 0 ? "reads high" : "reads low"}
        </div>
      </div>
      <div className="stat">
        <div className="k">Worst miss</div>
        <div className="v">{f(stats.worst)}</div>
      </div>
      <div className="stat">
        <div className="k">Samples</div>
        <div className="v">{stats.n}</div>
      </div>
    </div>
  );
}

export default function ValidationPage() {
  const router = useRouter();
  const [email, setEmail] = useState<string | null>(null);
  const [houses, setHouses] = useState<House[]>([]);
  const [house, setHouse] = useState<House | null>(null);
  const [hours, setHours] = useState(168);
  const [pairs, setPairs] = useState<ValidationPair[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    (async () => {
      const { data } = await supabase.auth.getSession();
      if (!data.session) { router.replace("/login"); return; }
      setEmail(data.session.user.email ?? null);
      const f: Farm | null = await getMyFarm().catch(() => null);
      if (!f) { router.replace("/setup"); return; }
      const hs = await getHouses(f.id).catch(() => []);
      setHouses(hs);
      if (hs.length) setHouse(hs[0]);
      setLoading(false);
    })();
  }, [router]);

  const load = useCallback(async () => {
    if (!house) return;
    setError("");
    try {
      setPairs(await getValidationHistory(house.id, hours));
    } catch (e: any) {
      setError(e?.message ?? "Could not load validation history");
      setPairs([]);
    }
  }, [house, hours]);

  useEffect(() => { load(); }, [load]);

  const speedSeries = pairs.map((p) => ({ t: p.t, predicted: p.computedSpeed, measured: p.measuredSpeed }));
  const rhSeries = pairs.map((p) => ({ t: p.t, predicted: p.predictedRh, measured: p.measuredRh }));

  const speedStats = errorStats(pairs, (p) => [p.computedSpeed, p.measuredSpeed]);
  const rhStats = errorStats(pairs, (p) => [p.predictedRh, p.measuredRh]);

  if (loading) return <AppShell email={email}><div className="muted">Loading…</div></AppShell>;

  return (
    <AppShell email={email}>
      <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap", marginBottom: 6 }}>
        <h1 style={{ margin: 0, fontSize: 22 }}>Model Validation</h1>
        {houses.length > 1 && (
          <select
            value={house?.id ?? ""}
            onChange={(e) => setHouse(houses.find((h) => h.id === e.target.value) ?? null)}
          >
            {houses.map((h) => <option key={h.id} value={h.id}>{h.name}</option>)}
          </select>
        )}
        <div style={{ display: "flex", gap: 6, marginLeft: "auto" }}>
          {WINDOWS.map((w) => (
            <button
              key={w.hours}
              className="ghost-btn"
              onClick={() => setHours(w.hours)}
              style={hours === w.hours ? { borderColor: "var(--accent)", color: "var(--ink)" } : {}}
            >
              {w.label}
            </button>
          ))}
        </div>
      </div>

      <p className="muted" style={{ fontSize: 13, marginTop: 0, maxWidth: 760, lineHeight: 1.5 }}>
        Each automated reading is logged alongside what the engine predicted at that
        moment. Over time the gap between the two is the honest measure of how well
        PCIS models <em>this</em> house — as opposed to the confidence scores elsewhere
        in the app, which reflect how well-sourced the inputs are, not how right the
        answers turned out.
      </p>

      {error && <div className="msg" style={{ color: "var(--red)" }}>⚠ {error}</div>}

      {pairs.length === 0 && !error && (
        <div className="tile" style={{ maxWidth: 760 }}>
          <b>Nothing to score yet.</b>
          <p className="muted" style={{ fontSize: 13, lineHeight: 1.55 }}>
            This page fills in once the scheduled sensor poll has run a few times with
            an active flock in the house. Each run logs a measurement and the matching
            prediction. Two or more paired points are needed before a trend can be drawn.
          </p>
          <p className="muted" style={{ fontSize: 12.5 }}>
            If it stays empty: check that the cron job is running, that Ecowitt keys are
            saved on the farm, and that the house has an active flock.
          </p>
        </div>
      )}

      {pairs.length > 0 && (
        <>
          <div className="tile" style={{ marginTop: 14 }}>
            <div className="tile-head">
              <span className="tile-title">Air speed — computed vs measured</span>
              <span className="chip" style={{ background: "rgba(52,211,153,0.15)", color: "var(--ok)" }}>
                independent check
              </span>
            </div>
            <p className="muted" style={{ fontSize: 12.5, marginTop: 0, lineHeight: 1.5 }}>
              The strongest evidence on this page. The computed figure comes from the fan
              curve and the house cross-section; the anemometer knows nothing about either,
              so agreement here genuinely tests the model rather than restating an input.
              This is also the constraint that governs most of your recommendations, which
              makes it the one most worth being right about.
            </p>
            <ValidationChart series={speedSeries} unit="m/s" label="Air speed: computed vs measured" />
            <StatBlock stats={speedStats} unit=" m/s" decimals={2} />
          </div>

          <div className="tile" style={{ marginTop: 14 }}>
            <div className="tile-head">
              <span className="tile-title">Indoor humidity — predicted vs measured</span>
              <span className="chip" style={{ background: "rgba(251,191,36,0.15)", color: "var(--warn)" }}>
                partially circular
              </span>
            </div>
            <p className="muted" style={{ fontSize: 12.5, marginTop: 0, lineHeight: 1.5 }}>
              Weaker evidence, and labelled so deliberately. The measured humidity is fed
              into the engine, where it influences the ventilation rate that the moisture
              balance then uses to predict humidity. The prediction can still diverge from
              the measurement, and the size of that gap is informative — but a small error
              here does not prove as much as a small error in air speed above.
            </p>
            <ValidationChart series={rhSeries} unit="%" label="Indoor RH: predicted vs measured" />
            <StatBlock stats={rhStats} unit="%" decimals={1} />
          </div>

          <div className="tile" style={{ marginTop: 14 }}>
            <div className="tile-title">Reading these numbers</div>
            <ul className="muted" style={{ fontSize: 12.5, lineHeight: 1.6, paddingLeft: 18 }}>
              <li><b>Typical miss</b> is how far out the prediction usually is, ignoring direction.</li>
              <li><b>Bias</b> keeps the sign. A bias near zero with a large typical miss means the model is noisy; a bias close to the typical miss means it is consistently skewed one way — which is the fixable kind, since a systematic offset points at a wrong constant rather than at randomness.</li>
              <li><b>Worst miss</b> is there so a flattering average cannot hide a bad hour.</li>
              <li>Sample counts in the low tens are a hint, not a verdict. Hundreds of samples spanning different weather are what would justify changing a constant in the engine.</li>
            </ul>
          </div>
        </>
      )}
    </AppShell>
  );
}
