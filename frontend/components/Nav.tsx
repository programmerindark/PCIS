"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { supabase } from "@/lib/supabaseClient";

export default function Nav({ email }: { email: string | null }) {
  const router = useRouter();
  const pathname = usePathname();

  async function signOut() {
    await supabase.auth.signOut();
    router.replace("/login");
  }

  const links = [
    { href: "/dashboard", label: "Dashboard" },
    { href: "/houses", label: "Houses" },
    { href: "/validation", label: "Validation" },
  ];

  return (
    <div className="topbar">
      <div style={{ display: "flex", alignItems: "center", gap: 24 }}>
        <div className="brand">
          <span className="logo">P</span> PCIS
        </div>
        <nav style={{ display: "flex", gap: 6 }}>
          {links.map((l) => (
            <Link
              key={l.href}
              href={l.href}
              className="ghost-btn"
              style={
                pathname === l.href
                  ? { borderColor: "var(--accent)", color: "var(--ink)" }
                  : {}
              }
            >
              {l.label}
            </Link>
          ))}
        </nav>
      </div>
      <div className="user">
        {email && <span>{email}</span>}
        <button className="ghost-btn" onClick={signOut}>
          Sign out
        </button>
      </div>
    </div>
  );
}
