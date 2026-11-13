import type { Metadata, Viewport } from "next";
import type { ReactNode } from "react";

import { AppProviders } from "@/components/providers/app-providers";

import "./globals.css";

export const metadata: Metadata = {
  title: {
    default: "Compliance Desk — Regulatory RAG Workspace",
    template: "%s · Compliance Desk",
  },
  description:
    "Local-first enterprise banking regulatory compliance assistant with server-enforced role-based retrieval, verified citations and audit summaries.",
  applicationName: "Compliance Desk",
  robots: { index: false, follow: false },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  themeColor: "#070b11",
  colorScheme: "dark",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body>
        <AppProviders>{children}</AppProviders>
      </body>
    </html>
  );
}
