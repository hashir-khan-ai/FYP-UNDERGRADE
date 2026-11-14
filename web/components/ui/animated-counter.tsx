"use client";

import * as React from "react";

import { prefersReducedMotion } from "@/lib/motion";

/**
 * Smooth numeric count-up for audit KPIs and document metrics.
 * Snaps immediately when `prefers-reduced-motion: reduce` is active.
 */
export function AnimatedCounter({
  value,
  formatter,
  durationMs = 320,
  className,
}: {
  value: number;
  formatter?: (n: number) => string;
  durationMs?: number;
  className?: string;
}) {
  const [display, setDisplay] = React.useState(value);
  const prevRef = React.useRef(value);

  React.useEffect(() => {
    const startVal = prevRef.current;
    prevRef.current = value;

    if (startVal === value || prefersReducedMotion() || typeof window === "undefined") {
      setDisplay(value);
      return;
    }

    let raf = 0;
    const start = performance.now();

    const step = (now: number) => {
      const t = Math.min(1, (now - start) / durationMs);
      const eased = 1 - Math.pow(1 - t, 3);
      setDisplay(startVal + (value - startVal) * eased);
      if (t < 1) {
        raf = window.requestAnimationFrame(step);
      } else {
        setDisplay(value);
      }
    };

    raf = window.requestAnimationFrame(step);
    return () => window.cancelAnimationFrame(raf);
  }, [value, durationMs]);

  const formatted = formatter ? formatter(display) : Math.round(display).toLocaleString();

  return <span className={className ? `tabular ${className}` : "tabular"}>{formatted}</span>;
}

