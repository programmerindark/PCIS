"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { supabase } from "@/lib/supabaseClient";

const NAV = [
  { href: "/dashboard", label: "Dashboard", icon: "⌂" },
  { href: "/houses", label: "Houses", icon: "▤" },
];

export default function AppShell({
  email,
  selectors,
  weather,
  alertCount = 0,
  children,
}: {
  email: string | null;
  selectors?: React.ReactNode;
  weather?: { t: number; rh: number } | null;
  alertCount?: number;
  children: React.ReactNode;
}) {
  const pathname = usePathname();
  const router = useRouter();
  const initials = (email ?? "U").slice(0, 2).toUpperCase();
  const now = new Date();

  async function signOut() {
    await supabase.auth.signOut();
    router.replace("/login");
  }

  return (
    <div className="shell">
      <aside className="sidebar">
        <span className="logo" title="PCIS">🐔</span>

        <nav className="side-nav">
          {NAV.map((n) => {
            const active = pathname === n.href || pathname.startsWith(n.href + "/");
            return (
              <Link key={n.href} href={n.href} className={"side-link" + (active ? " active" : "")} title={n.label}>
                <span className="ico">{n.icon}</span>
                {n.href === "/dashboard" && alertCount > 0 && (
                  <span className="badge-count">{alertCount}</span>
                )}
              </Link>
            );
          })}
        </nav>

        <div className="side-foot">
          <div className="status-dot-lg" title="Engine online">✓</div>
        </div>
      </aside>

      <div className="main">
        <header className="appbar">
          <div className="selector-row">{selectors}</div>

          <div className="topbar-right">
            {weather && (
              <>
                <div className="wx">
                  <span style={{ fontSize: 19 }}>⛅</span>
                  <div>
                    <div className="t">{weather.t}°C</div>
                    <div className="muted" style={{ fontSize: 10.5 }}>Humidity {weather.rh}%</div>
                  </div>
                </div>
                <div className="divider-v" />
              </>
            )}
            <div style={{ textAlign: "right" }}>
              <div style={{ fontSize: 13, fontWeight: 700 }}>
                {now.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
              </div>
              <div className="muted" style={{ fontSize: 10.5 }}>
                {now.toLocaleDateString([], { month: "short", day: "numeric", year: "numeric" })}
              </div>
            </div>
            <div className="divider-v" />
            <div style={{ display: "flex", alignItems: "center", gap: 9 }}>
              <div className="avatar">{initials}</div>
              <div style={{ maxWidth: 130, overflow: "hidden" }}>
                <div style={{ fontSize: 12, fontWeight: 700, whiteSpace: "nowrap", textOverflow: "ellipsis", overflow: "hidden" }}>
                  {email ?? "Account"}
                </div>
                <button className="link-btn" style={{ fontSize: 11 }} onClick={signOut}>Sign out</button>
              </div>
            </div>
          </div>
        </header>

        <main className="page">{children}</main>
      </div>
    </div>
  );
}
