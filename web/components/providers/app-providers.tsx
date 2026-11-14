"use client";

import type { ReactNode } from "react";
import { Toaster } from "sonner";

import { TooltipProvider } from "@/components/ui/tooltip";

export function AppProviders({ children }: { children: ReactNode }) {
  return (
    <TooltipProvider delayDuration={220} skipDelayDuration={120}>
      {children}
      <Toaster
        theme="dark"
        position="bottom-right"
        closeButton
        richColors
        duration={4000}
        toastOptions={{
          style: {
            background: "var(--surface-primary, #0d131c)",
            border: "1px solid var(--border-subtle, rgba(164,184,212,0.18))",
            color: "var(--text-primary, #f3f6fa)",
            fontSize: "0.875rem",
            borderRadius: "0.75rem",
          },
        }}
      />
    </TooltipProvider>
  );
}
