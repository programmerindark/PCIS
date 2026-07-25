"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { supabase } from "@/lib/supabaseClient";

export default function DashboardPage() {
  const router = useRouter();
  const [email, setEmail] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let active = true;
    supabase.auth.getSession().then(({ data }) => {
      if (!active) return;
      if (!data.session) {
        router.replace("/login");
        return;
      }
      setEmail(data.session.user.email ?? null);
      setLoading(false);
    });

    // Keep in sync if the user signs out in another tab.
    const { data: sub } = supabase.auth.onAuthStateChange((_e, session) => {
      if (!session) router.replace("/login");
    });
    return () => {
      active = false;
      sub.subscription.unsubscribe();
    };
  }, [router]);

  async function signOut() {
    await supabase.auth.signOut();
    router.replace("/login");
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
      <div className="topbar">
        <div className="brand">
          <span className="logo">P</span> PCIS
        </div>
        <div className="user">
          <span>{email}</span>
          <button className="ghost-btn" onClick={signOut}>
            Sign out
          </button>
        </div>
      </div>

      <div className="page">
        <h2>Dashboard</h2>
        <p className="muted">
          You're signed in. Next we'll add your farm, houses and flock, then wire these
          tiles to the live climate engine.
        </p>

        <div className="grid">
          <div className="tile">
            <div className="cap">Bird comfort</div>
            <div className="val">—</div>
          </div>
          <div className="tile">
            <div className="cap">Feel temperature</div>
            <div className="val">—</div>
          </div>
          <div className="tile">
            <div className="cap">Heat-stress risk</div>
            <div className="val">—</div>
          </div>
          <div className="tile">
            <div className="cap">Fans running</div>
            <div className="val">—</div>
          </div>
        </div>

        <div style={{ marginTop: 20 }}>
          <div className="placeholder">
            Farm &amp; house setup and the live house view land in the next work packages.
          </div>
        </div>
      </div>
    </>
  );
}
