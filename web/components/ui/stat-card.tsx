"use client";

import * as React from "react";

import { AnimatedCounter } from "@/components/ui/animated-counter";
import { cn } from "@/lib/utils";

export interface StatCardRing {
  value: number;
  max: number;
  label?: string;
  tone?: "accent" | "success" | "info";
}

export interface StatCardProps {
  label: string;
  value: number | string;
  /** Optional unit or suffix rendered next to numeric counters (e.g. "%" or " s"). */
  suffix?: string;
  decimals?: number;
  caption: string;
  icon: React.ReactNode;
  delta?: string | null;
  deltaTone?: "neutral" | "accent" | "success" | "warning";
  ring?: StatCardRing | null;
  sparkline?: number[] | null;
  sparkVariant?: "bars" | "line";
  sparkLabel?: string;
  /** Shown honestly when sparkline/ring lacks real baseline samples. */
  emptyVisualText?: string;
  accentValue?: boolean;
  className?: string;
}

const DELTA_STYLES: Record<NonNullable<StatCardProps["deltaTone"]>, string> = {
  neutral: "bg-surface-2 text-muted ring-line",
  accent: "bg-accent-soft text-accent-link ring-line-accent",
  success: "bg-success-soft text-success ring-success/25",
  warning: "bg-warning-soft text-warning ring-warning/25",
};

function MiniProgressRing({ ring }: { ring: StatCardRing }) {
  const ratio = ring.max > 0 ? Math.max(0, Math.min(1, ring.value / ring.max)) : 0;
  const pct = Math.round(ratio * 100);
  const r = 13;
  const circumference = 2 * Math.PI * r;
  const dashOffset = circumference * (1 - ratio);
  const strokeColor =
    ring.tone === "success"
      ? "var(--success)"
      : ring.tone === "info"
        ? "var(--info)"
        : "var(--accent)";

  return (
    <div className="flex items-center gap-2" title={ring.label ? `${ring.label}: ${pct}%` : `${pct}%`}>
      <svg viewBox="0 0 34 34" width={34} height={34} className="shrink-0 -rotate-90" aria-hidden="true">
        <circle cx="17" cy="17" r={r} fill="none" stroke="var(--surface-3)" strokeWidth="3.2" />
        <circle
          cx="17"
          cy="17"
          r={r}
          fill="none"
          stroke={strokeColor}
          strokeWidth="3.2"
          strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={ring.max > 0 ? dashOffset : circumference}
        />
      </svg>
      <span className="tabular text-xs font-medium text-muted">
        {ring.max > 0 ? `${pct}%` : "No data"}
      </span>
    </div>
  );
}

function MiniSparkline({
  values,
  variant = "line",
  label,
}: {
  values: number[];
  variant: "bars" | "line";
  label?: string;
}) {
  const w = 92;
  const h = 28;
  const pad = 3;
  const maxVal = Math.max(...values);
  const minVal = Math.min(...values);
  const span = maxVal - minVal || 1;

  if (variant === "bars") {
    const slice = values.slice(-12);
    const barGap = 2;
    const barW = Math.max(3, (w - pad * 2 - barGap * (slice.length - 1)) / slice.length);
    return (
      <svg
        viewBox={`0 0 ${w} ${h}`}
        width={w}
        height={h}
        role="img"
        aria-label={label ?? "Trend bars"}
        className="shrink-0 overflow-visible"
      >
        {slice.map((val, i) => {
          const norm = maxVal > 0 ? Math.max(0.14, val / maxVal) : 0.14;
          const bh = Math.round(norm * (h - pad * 2));
          const x = pad + i * (barW + barGap);
          const y = h - pad - bh;
          const isLast = i === slice.length - 1;
          return (
            <rect
              key={i}
              x={x}
              y={y}
              width={barW}
              height={bh}
              rx={2}
              fill={isLast ? "var(--accent)" : "var(--storm)"}
              fillOpacity={isLast ? 1 : 0.45}
            />
          );
        })}
      </svg>
    );
  }

  const pts = values.slice(-16).map((v, i, arr) => {
    const x = pad + (arr.length <= 1 ? 0 : (i / (arr.length - 1)) * (w - pad * 2));
    const y = h - pad - ((v - minVal) / span) * (h - pad * 2);
    return { x, y };
  });
  const d = pts.map((p, i) => `${i === 0 ? "M" : "L"}${p.x.toFixed(1)} ${p.y.toFixed(1)}`).join(" ");
  const last = pts[pts.length - 1];

  return (
    <svg
      viewBox={`0 0 ${w} ${h}`}
      width={w}
      height={h}
      role="img"
      aria-label={label ?? "Trend sparkline"}
      className="shrink-0 overflow-visible"
    >
      <path
        d={d}
        fill="none"
        stroke="var(--accent)"
        strokeWidth="1.75"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      {last ? <circle cx={last.x} cy={last.y} r="2.75" fill="var(--accent)" /> : null}
    </svg>
  );
}

export function StatCard({
  label,
  value,
  suffix,
  decimals = 0,
  caption,
  icon,
  delta,
  deltaTone = "neutral",
  ring,
  sparkline,
  sparkVariant = "line",
  sparkLabel,
  emptyVisualText = "No data yet",
  accentValue = false,
  className,
}: StatCardProps) {
  const hasSpark = Array.isArray(sparkline) && sparkline.length >= 2;
  const hasRing = ring != null && ring.max > 0;

  return (
    <div
      className={cn(
        "flex flex-col justify-between gap-3 rounded-[var(--r-lg)] bg-surface p-4.5 shadow-[var(--elev-1)] transition-shadow duration-[var(--duration-base)] hover:shadow-[var(--elev-2)]",
        className,
      )}
    >
      <div className="flex items-start justify-between gap-2">
        <span className="font-mono text-xs font-semibold uppercase tracking-[0.06em] text-faint">
          {label}
        </span>
        <span className="inline-flex size-9 shrink-0 items-center justify-center rounded-[var(--r-md)] bg-surface-2 text-accent-link shadow-[var(--inner-highlight)]">
          {icon}
        </span>
      </div>

      <div className="flex items-center justify-between gap-3">
        <div className="flex flex-wrap items-baseline gap-2 min-w-0">
          <p
            className={cn(
              "tabular text-2xl font-semibold tracking-[-0.03em] sm:text-[1.75rem]",
              accentValue ? "text-accent-link" : "text-ink",
            )}
          >
            {typeof value === "number" ? (
              <AnimatedCounter
                value={value}
                formatter={(n) =>
                  `${decimals > 0 ? n.toFixed(decimals) : Math.round(n).toLocaleString("en-US")}${suffix ?? ""}`
                }
              />
            ) : (
              value
            )}
          </p>

          {delta ? (
            <span
              className={cn(
                "inline-flex h-6 items-center rounded-full px-2.5 text-xs font-medium tabular ring-1 ring-inset",
                DELTA_STYLES[deltaTone],
              )}
            >
              {delta}
            </span>
          ) : null}
        </div>

        <div className="shrink-0">
          {hasRing ? (
            <MiniProgressRing ring={ring} />
          ) : hasSpark ? (
            <MiniSparkline values={sparkline} variant={sparkVariant} label={sparkLabel} />
          ) : (ring !== undefined || sparkline !== undefined) ? (
            <span className="font-mono text-xs text-faint">{emptyVisualText}</span>
          ) : null}
        </div>
      </div>

      <div className="border-t border-line pt-2.5">
        <p className="text-xs leading-snug text-muted">{caption}</p>
      </div>
    </div>
  );
}
