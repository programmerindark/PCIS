import type { Metadata } from "next";
import { IBM_Plex_Sans, IBM_Plex_Mono } from "next/font/google";
import "./globals.css";

/**
 * IBM Plex, self-hosted by next/font.
 *
 * The app previously rode the raw system stack, which resolves to SF Pro on
 * Apple hardware and silently to Segoe UI or Roboto everywhere else -- and
 * this farm reads it on an Android phone. So the typeface nobody chose was
 * also not the one anybody actually saw.
 *
 * Plex was drawn for an engineering company's instrumentation, which is
 * what this is: a measuring instrument, not a consumer app. It carries some
 * technical character without being fashionable enough to date.
 *
 * next/font downloads and self-hosts the files at build time -- no runtime
 * request to a font CDN, and no flash of unstyled text, which matters on a
 * shed connection.
 */
const plexSans = IBM_Plex_Sans({
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
  variable: "--font-sans",
  display: "swap",
});

/**
 * Plex Mono carries every number that changes.
 *
 * The monospace face is not decoration. This dashboard rewrites its figures
 * once a minute, and in a proportional face digits have different widths --
 * so "22.7" becoming "23.1" nudges everything after it sideways. On a wall
 * display that reads as flicker, and flicker reads as unreliable. Fixed
 * width digits hold the line still.
 */
const plexMono = IBM_Plex_Mono({
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
  variable: "--font-mono",
  display: "swap",
});

export const metadata: Metadata = {
  title: "PCIS — Poultry Climate Intelligence System",
  description: "Smarter climate. Healthier birds. Higher profit.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className={`${plexSans.variable} ${plexMono.variable}`}>
      <body>{children}</body>
    </html>
  );
}
