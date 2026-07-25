"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { supabase } from "@/lib/supabaseClient";

const NAV = [
  { href: "/dashboard", label: "Dashboard", icon: "▦" },
  { href: "/houses", label: "Houses", icon: "⌂" },
];

export default function AppShell({
  email,
  title,
  right,
  children,
}: {
  email: string | null;
  title: string;
  right?: React.ReactNode;
  children: React.ReactNode;
}) {
  const pathname = usePathname();
  const router = useRouter();

  async function signOut() {
    await supabase.auth.signOut();
    router.replace("/login");
  }

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">
          <span className="logo">P</span> <span className="brand-txt">PCIS</span>
        </div>
        <nav className="side-nav">
          {NAV.map((n) => {
            const active = pathname === n.href || pathname.startsWith(n.href + "/");
            return (
              <Link key={n.href} href={n.href} className={"side-link" + (active ? " active" : "")}>
                <span className="ico">{n.icon}</span>
                <span className="lbl">{n.label}</span>
              </Link>
            );
          })}
        </nav>
        <div className="side-foot muted">PCIS v1.0 · Phoenix</div>
      </aside>

      <div className="main">
        <header className="appbar">
          <div className="appbar-title">{title}</div>
          <div className="appbar-right">
            {right}
            {email && <span>{email}</span>}
            <button className="ghost-btn" onClick={signOut}>Sign out</button>
          </div>
        </header>
        <main className="page">{children}</main>
      </div>
    </div>
  );
}
