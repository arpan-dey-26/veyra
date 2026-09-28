import type { Metadata, Viewport } from "next";
import type { ReactNode } from "react";
import { Instrument_Serif, Inter_Tight, JetBrains_Mono } from "next/font/google";

import { DemoRibbon } from "@/components/shell/demo-ribbon";

import "./globals.css";

const sans = Inter_Tight({ subsets: ["latin"], variable: "--font-inter-tight", display: "swap" });
const display = Instrument_Serif({
  subsets: ["latin"],
  weight: "400",
  style: ["normal", "italic"],
  variable: "--font-instrument-serif",
  display: "swap",
});
const mono = JetBrains_Mono({ subsets: ["latin"], variable: "--font-jetbrains-mono", display: "swap" });

export const metadata: Metadata = {
  title: { default: "VEYRA — Intelligent Blood Network", template: "%s · VEYRA" },
  description:
    "VEYRA is a prototype intelligent blood network connecting donors, blood banks and hospitals with traceable, verifiable blood supply.",
  applicationName: "VEYRA",
  robots: { index: false, follow: false }, // prototype: keep out of search indexes
};

export const viewport: Viewport = {
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#faf8f6" },
    { media: "(prefers-color-scheme: dark)", color: "#0f0c0b" },
  ],
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en" className={`${sans.variable} ${display.variable} ${mono.variable}`}>
      <body>
        <a
          href="#main"
          className="sr-only focus:not-sr-only focus:fixed focus:top-3 focus:left-3 focus:z-50 focus:rounded-md focus:bg-surface-raised focus:px-4 focus:py-2 focus:shadow-2"
        >
          Skip to content
        </a>
        <DemoRibbon />
        {children}
      </body>
    </html>
  );
}
