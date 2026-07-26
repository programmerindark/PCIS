"use client";

import { useState } from "react";
import { searchPlaces, type Place } from "@/lib/weather";

/** Set the FARM's location. Three ways: search by place name (works when
 *  you are away from the farm), use the device's current position, or
 *  type coordinates directly. */
export default function LocationPicker({
  currentLat,
  currentLon,
  onPick,
  onClose,
}: {
  currentLat: number | null;
  currentLon: number | null;
  onPick: (lat: number, lon: number, label?: string) => Promise<void> | void;
  onClose?: () => void;
}) {
  const [q, setQ] = useState("");
  const [results, setResults] = useState<Place[]>([]);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [lat, setLat] = useState(currentLat != null ? String(currentLat) : "");
  const [lon, setLon] = useState(currentLon != null ? String(currentLon) : "");

  async function doSearch(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true); setErr("");
    try {
      const r = await searchPlaces(q);
      setResults(r);
      if (r.length === 0) setErr("No places found — try a nearby town, or enter coordinates.");
    } catch {
      setErr("Search failed. Check your connection or enter coordinates.");
    } finally { setBusy(false); }
  }

  async function useDevice() {
    if (!navigator.geolocation) { setErr("This browser can't provide a location."); return; }
    setBusy(true); setErr("");
    navigator.geolocation.getCurrentPosition(
      async (pos) => {
        await onPick(+pos.coords.latitude.toFixed(4), +pos.coords.longitude.toFixed(4), "Current position");
        setBusy(false);
      },
      () => { setErr("Location permission denied."); setBusy(false); }
    );
  }

  async function useTyped() {
    const la = parseFloat(lat), lo = parseFloat(lon);
    if (Number.isNaN(la) || Number.isNaN(lo) || Math.abs(la) > 90 || Math.abs(lo) > 180) {
      setErr("Enter a valid latitude (-90..90) and longitude (-180..180)."); return;
    }
    setBusy(true);
    await onPick(la, lo);
    setBusy(false);
  }

  return (
    <div>
      <p className="muted" style={{ fontSize: 12.5, marginTop: 0, lineHeight: 1.5 }}>
        Weather is always fetched for the <b>farm's</b> location — so it stays correct even when
        you're checking from somewhere else.
      </p>

      <form onSubmit={doSearch} style={{ display: "flex", gap: 8, alignItems: "end" }}>
        <div style={{ flex: 1 }}>
          <label style={{ marginTop: 0 }}>Search by place</label>
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="e.g. Nizamabad" />
        </div>
        <button className="ghost-btn" type="submit" disabled={busy || q.trim().length < 2}>Search</button>
      </form>

      {results.length > 0 && (
        <div style={{ marginTop: 10, display: "flex", flexDirection: "column", gap: 6 }}>
          {results.map((p, i) => (
            <button
              key={i}
              className="ghost-btn"
              style={{ textAlign: "left", width: "100%" }}
              onClick={async () => {
                setBusy(true);
                await onPick(p.latitude, p.longitude, [p.name, p.admin1, p.country].filter(Boolean).join(", "));
                setBusy(false);
              }}
            >
              <b>{p.name}</b>
              <span className="muted"> · {[p.admin1, p.country].filter(Boolean).join(", ")}</span>
              <span className="muted" style={{ float: "right", fontSize: 11 }}>
                {p.latitude.toFixed(2)}, {p.longitude.toFixed(2)}
              </span>
            </button>
          ))}
        </div>
      )}

      <div style={{ display: "flex", alignItems: "center", gap: 10, margin: "14px 0 6px" }}>
        <div style={{ flex: 1, height: 1, background: "var(--line)" }} />
        <span className="muted" style={{ fontSize: 11 }}>or</span>
        <div style={{ flex: 1, height: 1, background: "var(--line)" }} />
      </div>

      <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "end" }}>
        <button className="ghost-btn" onClick={useDevice} disabled={busy}>📍 Use my position</button>
        <div><label style={{ marginTop: 0 }}>Latitude</label>
          <input value={lat} onChange={(e) => setLat(e.target.value)} style={{ width: 110 }} placeholder="17.38" /></div>
        <div><label style={{ marginTop: 0 }}>Longitude</label>
          <input value={lon} onChange={(e) => setLon(e.target.value)} style={{ width: 110 }} placeholder="78.48" /></div>
        <button className="ghost-btn" onClick={useTyped} disabled={busy}>Save</button>
      </div>

      {err && <div className="msg error" style={{ fontSize: 12.5 }}>{err}</div>}
      {onClose && (
        <div style={{ marginTop: 12 }}>
          <button className="ghost-btn" onClick={onClose}>Close</button>
        </div>
      )}
    </div>
  );
}
