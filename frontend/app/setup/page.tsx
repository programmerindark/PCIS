"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { supabase } from "@/lib/supabaseClient";
import ChickenLoader from "@/components/ChickenLoader";
import { getMyFarm, createFarm } from "@/lib/db";

export default function SetupPage() {
  const router = useRouter();
  const [ready, setReady] = useState(false);
  const [name, setName] = useState("");
  const [location, setLocation] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    supabase.auth.getSession().then(async ({ data }) => {
      if (!data.session) {
        router.replace("/login");
        return;
      }
      // If a farm already exists, skip setup.
      const farm = await getMyFarm().catch(() => null);
      if (farm) {
        router.replace("/houses");
        return;
      }
      setReady(true);
    });
  }, [router]);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      await createFarm(name, location);
      router.replace("/houses");
    } catch (err: any) {
      setError(err?.message ?? "Could not create farm.");
      setBusy(false);
    }
  }

  if (!ready) {
    return (
      <div className="auth-wrap">
        <ChickenLoader />
      </div>
    );
  }

  return (
    <div className="auth-wrap">
      <div className="card">
        <div className="brand">
          <span className="logo">P</span> PCIS
        </div>
        <h1>Set up your farm</h1>
        <p className="sub">One quick step — then we add your houses and flock.</p>
        <form onSubmit={submit}>
          <label htmlFor="name">Farm name</label>
          <input
            id="name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Green Valley Farms"
            required
          />
          <label htmlFor="loc">Location (optional)</label>
          <input
            id="loc"
            value={location}
            onChange={(e) => setLocation(e.target.value)}
            placeholder="District, State"
          />
          <button className="primary" type="submit" disabled={busy}>
            {busy ? "Creating…" : "Create farm"}
          </button>
        </form>
        {error && <div className="msg error">{error}</div>}
      </div>
    </div>
  );
}
