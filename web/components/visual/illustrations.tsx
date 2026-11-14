import { cn } from "@/lib/utils";

export function NotFoundIllustration({ className }: { className?: string }) {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 220 140"
      width="220"
      height="140"
      fill="none"
      aria-hidden="true"
      focusable="false"
      className={cn("mx-auto h-auto w-[180px] sm:w-[220px]", className)}
    >
      <rect
        x="24"
        y="20"
        width="124"
        height="100"
        rx="6"
        fill="var(--surface, #26292E)"
        stroke="var(--storm, #5A6068)"
        strokeWidth="1.5"
      />
      <line x1="40" y1="20" x2="40" y2="120" stroke="var(--storm, #5A6068)" strokeWidth="1.5" />
      <line x1="56" y1="44" x2="128" y2="44" stroke="var(--storm, #5A6068)" strokeWidth="2" strokeLinecap="round" />
      <line x1="56" y1="64" x2="116" y2="64" stroke="var(--storm, #5A6068)" strokeWidth="2" strokeLinecap="round" />
      <line x1="56" y1="84" x2="96" y2="84" stroke="var(--storm, #5A6068)" strokeWidth="2" strokeLinecap="round" />
      <rect
        x="156"
        y="36"
        width="44"
        height="68"
        rx="4"
        fill="var(--surface-2, #2E3238)"
        stroke="var(--accent, #FF5F00)"
        strokeWidth="1.75"
        strokeDasharray="5 4"
      />
      <circle cx="176" cy="68" r="9" stroke="var(--accent, #FF5F00)" strokeWidth="1.75" />
      <line x1="183" y1="75" x2="190" y2="82" stroke="var(--accent, #FF5F00)" strokeWidth="2" strokeLinecap="round" />
    </svg>
  );
}

export function QuotaErrorIllustration({ className }: { className?: string }) {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 220 140"
      width="220"
      height="140"
      fill="none"
      aria-hidden="true"
      focusable="false"
      className={cn("mx-auto h-auto w-[160px] sm:w-[200px]", className)}
    >
      <rect
        x="24"
        y="96"
        width="28"
        height="24"
        rx="3"
        fill="var(--surface-2, #2E3238)"
        stroke="var(--storm, #5A6068)"
        strokeWidth="1.5"
      />
      <rect
        x="64"
        y="76"
        width="28"
        height="44"
        rx="3"
        fill="var(--surface-2, #2E3238)"
        stroke="var(--storm, #5A6068)"
        strokeWidth="1.5"
      />
      <rect
        x="104"
        y="56"
        width="28"
        height="64"
        rx="3"
        fill="var(--surface-2, #2E3238)"
        stroke="var(--storm, #5A6068)"
        strokeWidth="1.5"
      />
      <rect
        x="144"
        y="40"
        width="28"
        height="80"
        rx="3"
        fill="var(--surface, #26292E)"
        stroke="var(--accent, #FF5F00)"
        strokeWidth="1.75"
      />
      <line
        x1="16"
        y1="40"
        x2="180"
        y2="40"
        stroke="var(--accent, #FF5F00)"
        strokeWidth="2"
        strokeDasharray="6 4"
        strokeLinecap="round"
      />
      <circle
        cx="194"
        cy="40"
        r="10"
        fill="var(--surface, #26292E)"
        stroke="var(--accent, #FF5F00)"
        strokeWidth="1.75"
      />
      <line x1="194" y1="35" x2="194" y2="41" stroke="var(--accent, #FF5F00)" strokeWidth="1.75" strokeLinecap="round" />
      <circle cx="194" cy="45" r="1.25" fill="var(--accent, #FF5F00)" />
    </svg>
  );
}

export function EmptyDeskIllustration({ className }: { className?: string }) {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 220 140"
      width="220"
      height="140"
      fill="none"
      aria-hidden="true"
      focusable="false"
      className={cn("mx-auto h-auto w-[160px] sm:w-[200px]", className)}
    >
      <rect
        x="36"
        y="28"
        width="148"
        height="92"
        rx="6"
        fill="var(--surface, #26292E)"
        stroke="var(--storm, #5A6068)"
        strokeWidth="1.5"
      />
      <line x1="110" y1="28" x2="110" y2="120" stroke="var(--storm, #5A6068)" strokeWidth="1.5" />
      <line x1="52" y1="52" x2="96" y2="52" stroke="var(--storm, #5A6068)" strokeWidth="2" strokeLinecap="round" />
      <line x1="52" y1="72" x2="92" y2="72" stroke="var(--storm, #5A6068)" strokeWidth="2" strokeLinecap="round" />
      <line x1="124" y1="52" x2="168" y2="52" stroke="var(--storm, #5A6068)" strokeWidth="2" strokeLinecap="round" />
      <line x1="124" y1="72" x2="160" y2="72" stroke="var(--storm, #5A6068)" strokeWidth="2" strokeLinecap="round" />
      <path
        d="M144 20h16v32l-8-6-8 6V20z"
        fill="var(--surface-2, #2E3238)"
        stroke="var(--accent, #FF5F00)"
        strokeWidth="1.75"
        strokeLinejoin="round"
      />
    </svg>
  );
}

