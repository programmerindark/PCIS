"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { supabase } from "@/lib/supabaseClient";
import { getMyFarm, getHouses, createHouse, type NewHouse } from "@/lib/db";
import { getCatalog } from "@/lib/api";
import Nav from "@/components/Nav";
import type { Farm, House, Catalog } from "@/lib/types";

const BLANK: NewHouse = {
  name: "",
  length_m: 120,
  width_m: 15,
  height_m: 3,
  insulation: "insulated",
  fan_index: 0,
  installed_fans: 10,
  static_pressure_pa: 30,
  has_cooling_pads: false,
  heater_kw: 0,
};

export default function HousesPage() {
  const router = useRouter();
  const [email, setEmail] = useState<string | null>(null);
  const [farm, setFarm] = useState<Farm | null>(null);
  const [houses, setHouses] = useState<House[]>([]);
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [form, setForm] = useState<NewHouse>(BLANK);
  const [showForm, setShowForm] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      const { data } = await supabase.auth.getSession();
      if (!data.session) {
        router.replace("/login");
        return;
      }
      setEmail(data.session.user.email ?? null);
      const f = await getMyFarm().catch(() => null);
      if (!f) {
        router.replace("/setup");
        return;
      }
      setFarm(f);
      setHouses(await getHouses(f.id).catch(() => []));
      setCatalog(await getCatalog().catch(() => null));
      setLoading(false);
    })();
  }, [router]);

  function set<K extends keyof NewHouse>(k: K, v: NewHouse[K]) {
    setForm((prev) => ({ ...prev, [k]: v }));
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!farm) return;
    setBusy(true);
    setError("");
    try {
      await createHouse(farm.id, form);
      setHouses(await getHouses(farm.id));
      setForm(BLANK);
      setShowForm(false);
    } catch (err: any) {
      setError(err?.message ?? "Could not add house.");
    } finally {
      setBusy(false);
    }
  }

  if (loading) {
    return (
      <div className="auth-wrap">
        <div className="muted">Loading…</div>
      </div>
    );
  }

  return (
    <>
      <Nav email={email} />
      <div className="page">
        <h2>{farm?.name} — Houses</h2>
        <p className="muted">Add each broiler house once; the dashboard reads them to advise you.</p>

        <div className="grid">
          {houses.map((h) => (
            <Link key={h.id} href={`/dashboard?house=${h.id}`} className="tile" style={{ display: "block" }}>
              <div className="cap">House</div>
              <div className="val" style={{ fontSize: 20 }}>{h.name}</div>
              <div className="muted" style={{ marginTop: 8 }}>
                {h.length_m}×{h.width_m}×{h.height_m} m · {h.installed_fans} fans ·{" "}
                {h.insulation.replace("_", " ")}
                {h.has_cooling_pads ? " · pads" : ""}
              </div>
            </Link>
          ))}
          {houses.length === 0 && (
            <div className="placeholder">No houses yet. Add your first one below.</div>
          )}
        </div>

        <div style={{ marginTop: 20 }}>
          {!showForm ? (
            <button className="primary" style={{ maxWidth: 220 }} onClick={() => setShowForm(true)}>
              + Add a house
            </button>
          ) : (
            <div className="tile" style={{ maxWidth: 640 }}>
              <h3 style={{ marginTop: 0 }}>New house</h3>
              <form onSubmit={submit}>
                <label>Name</label>
                <input value={form.name} onChange={(e) => set("name", e.target.value)} placeholder="House 02 - Broiler Shed" required />

                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 12 }}>
                  <div>
                    <label>Length (m)</label>
                    <input type="number" step="0.5" value={form.length_m} onChange={(e) => set("length_m", +e.target.value)} />
                  </div>
                  <div>
                    <label>Width (m)</label>
                    <input type="number" step="0.5" value={form.width_m} onChange={(e) => set("width_m", +e.target.value)} />
                  </div>
                  <div>
                    <label>Height (m)</label>
                    <input type="number" step="0.5" value={form.height_m} onChange={(e) => set("height_m", +e.target.value)} />
                  </div>
                </div>

                <label>Insulation</label>
                <select value={form.insulation} onChange={(e) => set("insulation", e.target.value as NewHouse["insulation"])}
                  style={selectStyle}>
                  <option value="uninsulated">Uninsulated</option>
                  <option value="insulated">Insulated (typical)</option>
                  <option value="well_insulated">Well insulated</option>
                </select>

                <label>Fan model</label>
                <select value={form.fan_index} onChange={(e) => set("fan_index", +e.target.value)} style={selectStyle}>
                  {(catalog?.fans ?? [{ index: 0, label: "Default fan" }]).map((f) => (
                    <option key={f.index} value={f.index}>{f.label}</option>
                  ))}
                </select>

                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
                  <div>
                    <label>Fans installed</label>
                    <input type="number" value={form.installed_fans} onChange={(e) => set("installed_fans", +e.target.value)} />
                  </div>
                  <div>
                    <label>Static pressure (Pa)</label>
                    <input type="number" value={form.static_pressure_pa} onChange={(e) => set("static_pressure_pa", +e.target.value)} />
                  </div>
                </div>

                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, alignItems: "end" }}>
                  <div>
                    <label>Heater capacity (kW, 0 = none)</label>
                    <input type="number" value={form.heater_kw} onChange={(e) => set("heater_kw", +e.target.value)} />
                  </div>
                  <label style={{ display: "flex", alignItems: "center", gap: 8, margin: "0 0 11px" }}>
                    <input type="checkbox" style={{ width: "auto" }} checked={form.has_cooling_pads}
                      onChange={(e) => set("has_cooling_pads", e.target.checked)} />
                    Cooling pads installed
                  </label>
                </div>

                <div style={{ display: "flex", gap: 10 }}>
                  <button className="primary" type="submit" disabled={busy} style={{ maxWidth: 200 }}>
                    {busy ? "Saving…" : "Save house"}
                  </button>
                  <button type="button" className="ghost-btn" onClick={() => setShowForm(false)}>Cancel</button>
                </div>
              </form>
              {error && <div className="msg error">{error}</div>}
            </div>
          )}
        </div>
      </div>
    </>
  );
}

const selectStyle: React.CSSProperties = {
  width: "100%",
  padding: "11px 12px",
  borderRadius: 9,
  background: "var(--surface-2)",
  border: "1px solid var(--line)",
  color: "var(--ink)",
  fontSize: 15,
};
