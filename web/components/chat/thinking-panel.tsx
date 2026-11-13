"use client";

import { Check, LoaderCircle } from "lucide-react";

import { CHAT_STAGES } from "@/lib/constants";
import { cn } from "@/lib/utils";

export function ThinkingPanel({ stage }: { stage: number }) {
  return (
    <div
      role="status"
      aria-live="polite"
      className="rounded-[var(--r-md)] border border-line bg-surface/70 p-3.5"
    >
      <div className="mb-3 flex items-center gap-2">
        <span className="relative flex size-2">
          <span className="absolute inline-flex size-full animate-ping rounded-full bg-accent opacity-40" />
          <span className="relative inline-flex size-2 rounded-full bg-accent" />
        </span>
        <span className="text-xs font-medium text-ink-soft">Working through the compliance pipeline</span>
      </div>
      <ol className="space-y-2">
        {CHAT_STAGES.map((label, index) => {
          const complete = index < stage;
          const current = index === stage;
          return (
            <li
              key={label}
              className={cn(
                "flex items-center gap-2 text-[0.6875rem] transition-colors duration-[var(--duration-base)]",
                complete ? "text-faint" : current ? "text-ink-soft" : "text-faint/60",
              )}
            >
              <span
                className={cn(
                  "inline-flex size-4 items-center justify-center rounded-full border",
                  complete
                    ? "border-[rgba(86,217,155,0.3)] bg-success-soft text-success"
                    : current
                      ? "border-line-accent bg-accent-soft text-accent"
                      : "border-line text-faint",
                )}
                aria-hidden="true"
              >
                {complete ? (
                  <Check className="size-2.5" />
                ) : current ? (
                  <LoaderCircle className="size-2.5 animate-spin" />
                ) : (
                  <span className="size-1 rounded-full bg-current" />
                )}
              </span>
              {label}
              {current ? <span className="sr-only">in progress</span> : null}
            </li>
          );
        })}
      </ol>
      <p className="mt-3 border-t border-line pt-2.5 text-[0.625rem] leading-relaxed text-faint">
        Role filtering happens inside retrieval before any passage reaches the model.
      </p>
    </div>
  );
}
