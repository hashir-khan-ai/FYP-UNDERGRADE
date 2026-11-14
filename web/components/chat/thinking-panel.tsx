"use client";

import { Check, LoaderCircle, ShieldCheck } from "lucide-react";

import { CHAT_STAGES } from "@/lib/constants";
import { cn } from "@/lib/utils";

export function ThinkingPanel({ stage }: { stage: number }) {
  return (
    <div
      role="status"
      aria-live="polite"
      className="rounded-[var(--r-lg)] border border-line bg-surface/80 p-4 shadow-[var(--elev-sm)]"
    >
      <div className="mb-3.5 flex items-center justify-between gap-2 border-b border-line/60 pb-3">
        <div className="flex items-center gap-2">
          <span className="relative flex size-2.5">
            <span className="absolute inline-flex size-full animate-ping rounded-full bg-accent opacity-50" />
            <span className="relative inline-flex size-2.5 rounded-full bg-accent" />
          </span>
          <span className="text-xs font-semibold text-ink">
            Compliance Pipeline Stepper
          </span>
        </div>
        <span className="inline-flex items-center gap-1 rounded-full border border-[rgba(84,214,196,0.24)] bg-teal-soft px-2.5 py-0.5 text-xs font-medium text-teal">
          <ShieldCheck className="size-3.5" aria-hidden="true" />
          Server RBAC Active
        </span>
      </div>

      {/* Pipeline Stepper */}
      <ol className="space-y-2.5">
        {CHAT_STAGES.map((label, index) => {
          const complete = index < stage;
          const current = index === stage;
          return (
            <li
              key={label}
              className={cn(
                "flex items-center gap-3 text-xs transition-colors duration-[var(--duration-base)]",
                complete ? "text-faint" : current ? "font-medium text-ink" : "text-faint/60",
              )}
            >
              <span
                className={cn(
                  "inline-flex size-5 shrink-0 items-center justify-center rounded-full border transition-all duration-[var(--duration-base)]",
                  complete
                    ? "border-[rgba(86,217,155,0.3)] bg-success-soft text-success"
                    : current
                      ? "border-line-accent bg-accent-soft text-accent shadow-[0_0_0_2px_rgba(120,169,255,0.15)]"
                      : "border-line text-faint",
                )}
                aria-hidden="true"
              >
                {complete ? (
                  <Check className="size-3" />
                ) : current ? (
                  <LoaderCircle className="size-3 animate-spin" />
                ) : (
                  <span className="size-1.5 rounded-full bg-current" />
                )}
              </span>
              <span className="flex-1 truncate">{label}</span>
              {current ? (
                <span className="text-xs font-mono text-accent">processing…</span>
              ) : complete ? (
                <span className="text-xs text-faint">done</span>
              ) : null}
            </li>
          );
        })}
      </ol>

      {/* Skeleton loader previewing answer synthesis */}
      <div className="mt-4 space-y-2 border-t border-line/60 pt-3.5" aria-hidden="true">
        <div className="skeleton h-4 w-4/5 rounded-[var(--r-xs)]" />
        <div className="skeleton h-4 w-full rounded-[var(--r-xs)]" />
        <div className="skeleton h-4 w-3/5 rounded-[var(--r-xs)]" />
      </div>

      <p className="mt-3.5 border-t border-line/40 pt-2 text-xs leading-relaxed text-faint">
        Role filtering occurs strictly in retrieval prior to context assembly. Passages outside
        clearance never enter language model context.
      </p>
    </div>
  );
}
