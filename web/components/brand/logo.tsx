import { cn } from "@/lib/utils";

/** Compliance Ledger institutional monogram: three archival tiers behind a Safety Orange gate. */
export function Logo({
  className,
  showWordmark = false,
}: {
  className?: string;
  showWordmark?: boolean;
}) {
  return (
    <span className={cn("inline-flex items-center gap-3 shrink-0", className)}>
      <svg
        viewBox="0 0 32 32"
        width={32}
        height={32}
        role="img"
        aria-label="Compliance Desk workspace"
        className="size-8 shrink-0"
      >
        <rect
          x="1"
          y="1"
          width="30"
          height="30"
          rx="6"
          fill="var(--surface, #26292E)"
          stroke="var(--line-strong, #5A6068)"
          strokeWidth="1.5"
        />
        <path d="M9 11L16 7.5L23 11L16 14.5L9 11Z" fill="var(--ink, #F1F3F4)" />
        <path
          d="M9 16L16 19.5L23 16"
          stroke="var(--muted, #B6BCC4)"
          strokeWidth="1.75"
          strokeLinecap="round"
          strokeLinejoin="round"
          fill="none"
        />
        <path
          d="M9 21L16 24.5L23 21"
          stroke="var(--storm, #5A6068)"
          strokeWidth="1.75"
          strokeLinecap="round"
          strokeLinejoin="round"
          fill="none"
        />
        <circle
          cx="16"
          cy="16"
          r="2.25"
          fill="var(--canvas, #1C1D20)"
          stroke="var(--accent, #FF5F00)"
          strokeWidth="1.75"
        />
      </svg>
      {showWordmark ? (
        <span className="flex flex-col leading-tight min-w-0">
          <span className="font-editorial text-base font-semibold tracking-[-0.02em] text-ink whitespace-nowrap">
            Compliance Desk
          </span>
          <span className="text-xs font-medium text-faint whitespace-nowrap">
            Regulatory Ledger
          </span>
        </span>
      ) : null}
    </span>
  );
}
