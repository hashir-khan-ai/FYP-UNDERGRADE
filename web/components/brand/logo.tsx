import { cn } from "@/lib/utils";

/** Compact institutional mark: three stacked corpus layers behind a role gate. */
export function Logo({
  className,
  showWordmark = false,
}: {
  className?: string;
  showWordmark?: boolean;
}) {
  return (
    <span className={cn("inline-flex items-center gap-2.5", className)}>
      <svg
        viewBox="0 0 32 32"
        role="img"
        aria-label="Regulatory Compliance workspace"
        className="size-8 shrink-0"
      >
        <defs>
          <linearGradient id="logo-gate" x1="6" y1="5" x2="26" y2="27" gradientUnits="userSpaceOnUse">
            <stop stopColor="#9cc0ff" />
            <stop offset="0.55" stopColor="#78a9ff" />
            <stop offset="1" stopColor="#54d6c4" />
          </linearGradient>
        </defs>
        <rect x="1" y="1" width="30" height="30" rx="9" fill="rgba(120,169,255,0.08)" stroke="rgba(120,169,255,0.28)" />
        <path d="M9 11.2 16 7.8l7 3.4-7 3.4-7-3.4Z" fill="url(#logo-gate)" opacity="0.9" />
        <path d="M9 15.8 16 19.2l7-3.4" stroke="url(#logo-gate)" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" opacity="0.72" />
        <path d="M9 20.2 16 23.6l7-3.4" stroke="url(#logo-gate)" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" opacity="0.45" />
        <circle cx="16" cy="16" r="2.15" fill="#070b11" stroke="url(#logo-gate)" strokeWidth="1.5" />
      </svg>
      {showWordmark ? (
        <span className="flex flex-col leading-none">
          <span className="text-sm font-semibold tracking-[-0.01em] text-ink">
            Compliance Desk
          </span>
          <span className="mt-0.5 text-xs font-medium uppercase tracking-[0.08em] text-faint">
            Regulatory intelligence
          </span>
        </span>
      ) : null}
    </span>
  );
}
