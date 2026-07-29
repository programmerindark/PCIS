"use client";

// The minute-by-minute record, readable.
//
// Defaults to the CHANGE LOG rather than the raw stream. At one poll a
// minute, a steady afternoon produces hundreds of identical rows; showing
// them all buries the three moments that actually mattered. The full
// stream is one click away for when someone is diagnosing a specific
// minute.

import { useEffect, useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import { supabase } from "@/lib/supabaseClient";
import { getMyFarm, getHouses } from "@/lib/db";
import AppShell from "@/components/AppShell";
import { getRecentActivity, type ActivityRow } from "@/lib/activity";
import { useUnits, cToDisplay, tempSuffix } from "@/lib/units";
import type { Farm, House } from "@/lib/types";

const WINDOWS = [
  { label: "1 hour", hours: 1 },
  { label: "6 hours", hours: 6 },
  { label: "24 hours", hours: 24 },
];

const RISK_COLOR: Record<string, string> = {
  Low: "var(--ok)", Moderate: "var(--warn)", High: "var(--danger)", Severe: "var(--danger)",
};

function clock(t: string) {
  return new Date(t).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

export default function HistoryPage() {
  const router = useRouter();
  const [email, setEmail] = useState<string | null>(null);
  const [houses, setHouses] = useState<House[]>([]);
  const [house, setHouse] = useState<House | null>(null);
  const [hours, setHours] = useState(6);
  const [changesOnly, setChangesOnly] = useState(true);
  const [rows, setRows] = useState<ActivityRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [live, setLive] = useState(true);
  const [units] = useUnits();
  const ts = tempSuffix(units);
  const T = (c: number | null) => (c == null ? "—" : cToDisplay(c, units).toFixed(1));

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
    try { setRows(await getRecentActivity(house.id, hours)); }
    catch { setRows([]); }
  }, [house, hours]);

  useEffect(() => {
    load();
    if (!live) return;
    // Matches the poll rate: refreshing faster would just re-fetch rows
    // that have not been written yet.
    const timer = setInterval(load, 60_000);
    return () => clearInterval(timer);
  }, [load, live]);

  const shown = changesOnly ? rows.filter((r, i) => r.changed || i === 0) : rows;
  const changeCount = rows.filter((r) => r.changed).length;

  if (loading) return <AppShell email={email}><div className="muted">Loading…</div></AppShell>;

  return (
    <AppShell email={email}>
      <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
        <h1 style={{ margin: 0, fontSize: 22 }}>House Log</h1>
        {houses.length > 1 && (
          <select value={house?.id ?? ""} onChange={(e) => setHouse(houses.find((h) => h.id === e.target.value) ?? null)}>
            {houses.map((h) => <option key={h.id} value={h.id}>{h.name}</option>)}
          </select>
        )}
        <div style={{ display: "flex", gap: 6, marginLeft: "auto", flexWrap: "wrap" }}>
          {WINDOWS.map((w) => (
            <button key={w.hours} className="ghost-btn" onClick={() => setHours(w.hours)}
              style={hours === w.hours ? { borderColor: "var(--accent)", color: "var(--ink)" } : {}}>
              {w.label}
            </button>
          ))}
          <button className="ghost-btn" onClick={() => setLive((v) => !v)}
            style={live ? { borderColor: "var(--ok)", color: "var(--ok)" } : {}}>
            {live ? "● Live" : "Paused"}
          </button>
        </div>
      </div>

      <div style={{ display: "flex", gap: 10, alignItems: "center", marginTop: 12, flexWrap: "wrap" }}>
        <button className="ghost-btn" onClick={() => setChangesOnly(true)}
          style={changesOnly ? { borderColor: "var(--accent)", color: "var(--ink)" } : {}}>
          Changes only ({changeCount})
        </button>
        <button className="ghost-btn" onClick={() => setChangesOnly(false)}
          style={!changesOnly ? { borderColor: "var(--accent)", color: "var(--ink)" } : {}}>
          Every minute ({rows.length})
        </button>
        <span className="muted" style={{ fontSize: 12 }}>
          {changesOnly
            ? "Only the moments the recommendation moved — a steady hour is one line, not sixty."
            : "Every logged reading. Rows where the decision changed are marked."}
        </span>
      </div>

      {rows.length === 0 ? (
        <div className="tile" style={{ marginTop: 14, maxWidth: 700 }}>
          <b>No readings logged in this window.</b>
          <p className="muted" style={{ fontSize: 13, lineHeight: 1.55 }}>
            The scheduled poll writes a row every minute once it is running. If this
            stays empty, check that the cron job is firing, that Ecowitt keys are saved
            on the farm, and that the house has an active flock.
          </p>
        </div>
      ) : (
        <div className="tile" style={{ marginTop: 14, overflowX: "auto" }}>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
            <thead>
              <tr style={{ textAlign: "left", color: "var(--ink-muted)", fontSize: 11.5 }}>
                <th style={{ padding: "6px 8px" }}>Time</th>
                <th style={{ padding: "6px 8px" }}>Inside {ts}</th>
                <th style={{ padding: "6px 8px" }}>RH %</th>
                <th style={{ padding: "6px 8px" }}>Outside {ts}</th>
                <th style={{ padding: "6px 8px" }}>Air m/s</th>
                <th style={{ padding: "6px 8px" }}>Fans</th>
                <th style={{ padding: "6px 8px" }}>Governed by</th>
                <th style={{ padding: "6px 8px" }}>Heat risk</th>
              </tr>
            </thead>
            <tbody>
              {shown.map((r, i) => (
                <tr key={r.t + i}
                  style={{
                    borderTop: "1px solid var(--surface-3)",
                    background: r.changed ? "rgba(56,189,248,0.07)" : undefined,
                  }}>
                  <td style={{ padding: "6px 8px", whiteSpace: "nowrap" }}>
                    {r.changed && <span style={{ color: "var(--blue)" }}>▸ </span>}
                    {clock(r.t)}
                  </td>
                  <td style={{ padding: "6px 8px" }}>{T(r.indoorT)}</td>
                  <td style={{ padding: "6px 8px" }}>{r.indoorRh ?? "—"}</td>
                  <td style={{ padding: "6px 8px", color: "var(--ink-muted)" }}>{T(r.outdoorT)}</td>
                  <td style={{ padding: "6px 8px" }}>
                    {r.measuredSpeed ?? "—"}
                    {r.computedSpeed != null && (
                      <span className="muted" style={{ fontSize: 11 }}> / {r.computedSpeed} calc</span>
                    )}
                  </td>
                  <td style={{ padding: "6px 8px", fontWeight: r.changed ? 800 : 400 }}>{r.fansOn ?? "—"}</td>
                  <td style={{ padding: "6px 8px", color: "var(--ink-muted)" }}>
                    {r.governing ? r.governing.replace(/_/g, " ") : "—"}
                  </td>
                  <td style={{ padding: "6px 8px", color: r.heatRisk ? RISK_COLOR[r.heatRisk] : undefined }}>
                    {r.heatRisk ?? "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="muted" style={{ fontSize: 11, marginTop: 10, lineHeight: 1.5 }}>
            Air speed shows the anemometer reading and, after the slash, what the engine
            computed from the fan curve and cross-section. They are produced
            independently, so a persistent gap between them is worth investigating —
            the Validation page tracks that over time.
          </div>
        </div>
      )}
    </AppShell>
  );
}
