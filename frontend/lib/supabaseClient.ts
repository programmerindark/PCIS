"use client";

import { createClient } from "@supabase/supabase-js";

// Browser Supabase client (client-side auth for v1). The URL and anon
// key are public-safe values read from .env.local. Never put the
// service_role key here.
const url = process.env.NEXT_PUBLIC_SUPABASE_URL as string;
const anonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY as string;

if (!url || !anonKey) {
  // Helpful error during dev if .env.local isn't set up yet.
  // eslint-disable-next-line no-console
  console.warn(
    "Supabase env vars missing. Copy .env.local.example to .env.local and fill in your Project URL + anon key."
  );
}

export const supabase = createClient(url ?? "", anonKey ?? "");
