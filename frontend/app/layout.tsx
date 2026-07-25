import type { Metadata } from "next";
import "./globals.css";

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
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
