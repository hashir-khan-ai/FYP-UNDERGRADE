"use client";

import type { ReactNode } from "react";
import { MotionConfig } from "framer-motion";
import { Toaster } from "sonner";

import { ThemeProvider, useTheme } from "@/components/providers/theme-provider";
import { TooltipProvider } from "@/components/ui/tooltip";

function ToasterBridge() {
  const { theme } = useTheme();
  return (
    <Toaster
      theme={theme}
      position="bottom-right"
      closeButton
      richColors
      duration={4000}
      toastOptions={{
        style: {
          background: "var(--surface)",
          border: "0",
          boxShadow: "var(--elev-3)",
          color: "var(--ink)",
          fontSize: "0.875rem",
          borderRadius: "var(--r-md)",
        },
      }}
    />
  );
}

export function AppProviders({ children }: { children: ReactNode }) {
  return (
    <MotionConfig reducedMotion="user">
      <ThemeProvider>
        <TooltipProvider delayDuration={200} skipDelayDuration={120}>
          {children}
          <ToasterBridge />
        </TooltipProvider>
      </ThemeProvider>
    </MotionConfig>
  );
}
