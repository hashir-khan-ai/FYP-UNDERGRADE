"use client";

import { CornerDownRight } from "lucide-react";

import { cn } from "@/lib/utils";

export function FollowUps({
  items,
  onSelect,
  disabled,
}: {
  items: string[];
  onSelect: (query: string) => void;
  disabled?: boolean;
}) {
  if (items.length === 0) return null;

  return (
    <div>
      <div className="mb-2 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-[0.08em] text-faint">
        <CornerDownRight className="size-3.5" aria-hidden="true" />
        Suggested follow-ups
      </div>
      <div className="flex flex-wrap gap-2">
        {items.map((item) => (
          <button
            key={item}
            type="button"
            onClick={() => onSelect(item)}
            disabled={disabled}
            className={cn(
              "flex min-h-[44px] items-center rounded-full bg-surface px-4 py-2 text-left text-xs leading-relaxed text-ink-soft shadow-[var(--elev-1)] transition-[background-color,color,box-shadow,transform] duration-[var(--duration-fast)] ease-[var(--ease-out)]",
              "hover:bg-surface-2 hover:text-ink hover:shadow-[var(--elev-2)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent",
              "disabled:pointer-events-none disabled:opacity-50",
            )}
          >
            {item}
          </button>
        ))}
      </div>
    </div>
  );
}
