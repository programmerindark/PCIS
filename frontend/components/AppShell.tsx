"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { supabase } from "@/lib/supabaseClient";
import { useUnits } from "@/lib/units";

// The app's only navigation. Icons rather than words because the sidebar
// is narrow; `label` is the hover tooltip and the accessible name.
const NAV = [
  { href: "/dashboard", label: "Dashboard", icon: "⌂" },
  { href: "/houses", label: "Houses", icon: "▤" },
  { href: "/history", label: "Log — minute-by-minute readings", icon: "≡" },
  { href: "/validation", label: "Validation — predicted vs measured", icon: "◎" },
];

export default function AppShell({
  email,
  selectors,
  weather,
  alertCount = 0,
  live = null,
  children,
}: {
  email: string | null;
  selectors?: React.ReactNode;
  /** Outdoor conditions for the top bar.
   *
   * `source` matters as much as the numbers. Once a two-module sensor is
   * installed these figures may be MEASURED at the farm rather than pulled
   * from a forecast for the nearest grid square, and the two can disagree
   * by several degrees. Showing a temperature without saying where it came
   * from invites the reader to trust a forecast as though someone had gone
   * outside and looked. */
  weather?: {
    t: number;
    rh: number;
    source: "sensor" | "forecast" | "manual";
    /** Minutes since the reading; drives the live indicator. */
    ageMin?: number | null;
  } | null;
  alertCount?: number;
  /** true = data arriving, false = gone quiet, null = no sensor set up. */
  live?: boolean | null;
  children: React.ReactNode;
}) {
  const pathname = usePathname();
  const router = useRouter();
  const [units, setUnits] = useUnits();
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
          {/* Reflects whether DATA IS ARRIVING, not merely that the page
              loaded. The previous always-green tick claimed "engine online"
              even when the sensor had been silent for hours, which is the
              one moment a status light must not be reassuring. */}
          <div
            className="status-dot-lg"
            title={
              live == null ? "No sensor configured"
                : live ? "Live — updating every minute"
                : "Not updating — sensor has gone quiet"
            }
            style={{
              color: live == null ? "var(--ink-muted)" : live ? "var(--ok)" : "var(--danger)",
              animation: live ? "pcis-pulse 2s ease-in-out infinite" : undefined,
            }}
          >
            {live == null ? "○" : live ? "●" : "⚠"}
          </div>
        </div>
      </aside>

      <div className="main">
        <header className="appbar">
          <div className="selector-row">{selectors}</div>

          <div className="topbar-right">
            {weather && (
              <>
                <div className="wx">
                  <span style={{ fontSize: 19 }}>
                    {weather.source === "sensor" ? "📡" : weather.source === "manual" ? "✎" : "⛅"}
                  </span>
                  <div>
                    <div className="t">{weather.t}°C</div>
                    <div className="muted" style={{ fontSize: 10.5 }}>
                      Humidity {weather.rh}% ·{" "}
                      <span style={{
                        color: weather.source === "sensor" ? "var(--ok)" : "var(--ink-muted)",
                        fontWeight: weather.source === "sensor" ? 700 : 400,
                      }}>
                        {weather.source === "sensor" ? "measured outside"
                          : weather.source === "manual" ? "entered by hand"
                          : "forecast"}
                      </span>
                    </div>
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
            <button
              className="ghost-btn"
              title="Switch display units (data is always stored in SI)"
              onClick={() => setUnits(units === "metric" ? "imperial" : "metric")}
            >
              {units === "metric" ? "m · °C" : "ft · °F"}
            </button>
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
