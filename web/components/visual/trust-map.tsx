"use client";

import * as React from "react";

import { cn } from "@/lib/utils";

/**
 * Composed Enterprise RAG Architecture SVG (floating rounded tonal cards joined by dotted connectors).
 * Subtle 2.5px vertical idle float is disabled cleanly under prefers-reduced-motion.
 */
export function PipelineHeroSvg({ className }: { className?: string }) {
  const uid = React.useId().replaceAll(":", "");

  return (
    <svg
      viewBox="0 0 560 220"
      width="560"
      height="220"
      role="img"
      aria-label="Compliance retrieval architecture connecting query, role gate, re-ranking, and cited answer"
      className={cn("h-auto w-full select-none", className)}
      fill="none"
    >
      <defs>
        <filter id={`card-shadow-${uid}`} x="-12%" y="-14%" width="124%" height="136%">
          <feDropShadow dx="0" dy="6" stdDeviation="7" floodColor="#181410" floodOpacity="0.14" />
        </filter>
      </defs>

      {/* Subtle architectural dotted connectors */}
      <path
        d="M126 68 C 160 68, 166 130, 198 130"
        stroke="var(--storm)"
        strokeOpacity="0.55"
        strokeWidth="1.75"
        strokeDasharray="4 4"
        strokeLinecap="round"
        className="pipeline-dash-active"
      />
      <path
        d="M312 130 C 344 130, 344 66, 374 66"
        stroke="var(--accent)"
        strokeWidth="1.85"
        strokeDasharray="4 4"
        strokeLinecap="round"
        className="pipeline-dash-active"
      />
      <path
        d="M428 106 C 428 124, 412 134, 434 134"
        stroke="var(--storm)"
        strokeOpacity="0.55"
        strokeWidth="1.6"
        strokeDasharray="3 4"
        strokeLinecap="round"
      />

      {/* Connector endpoint pins */}
      <circle cx="126" cy="68" r="3.5" fill="var(--surface)" stroke="var(--storm)" strokeWidth="1.5" />
      <circle cx="198" cy="130" r="4" fill="var(--accent)" />
      <circle cx="312" cy="130" r="3.5" fill="var(--accent)" />
      <circle cx="374" cy="66" r="3.5" fill="var(--surface)" stroke="var(--accent)" strokeWidth="1.75" />

      {/* Card 1: Query & Scope */}
      <g className="animate-idle-float" filter={`url(#card-shadow-${uid})`}>
        <rect
          x="14"
          y="26"
          width="116"
          height="82"
          rx="16"
          fill="var(--surface)"
          stroke="var(--line-strong)"
          strokeWidth="1"
        />
        <rect x="26" y="40" width="42" height="16" rx="8" fill="var(--surface-2)" />
        <circle cx="36" cy="48" r="3" fill="var(--storm)" />
        <text x="44" y="51.5" fill="var(--muted)" fontSize="8.5" fontWeight="600" fontFamily="var(--type-mono)">
          QUERY
        </text>
        <text x="26" y="74" fill="var(--ink)" fontSize="11.5" fontWeight="600" fontFamily="var(--type-ui)">
          User Turn
        </text>
        <rect x="26" y="84" width="76" height="5" rx="2.5" fill="var(--surface-3)" />
        <rect x="26" y="94" width="52" height="5" rx="2.5" fill="var(--surface-2)" />
      </g>

      {/* Card 2: Server Role Gate */}
      <g className="animate-idle-float-delayed" filter={`url(#card-shadow-${uid})`}>
        <rect
          x="194"
          y="88"
          width="124"
          height="92"
          rx="16"
          fill="var(--surface)"
          stroke="var(--line-accent)"
          strokeWidth="1.25"
        />
        <rect x="208" y="102" width="16" height="16" rx="6" fill="var(--accent-soft)" />
        <circle cx="216" cy="110" r="3.5" fill="var(--accent)" />
        <text x="231" y="114" fill="var(--accent-link)" fontSize="8.5" fontWeight="600" fontFamily="var(--type-mono)">
          RBAC GATE
        </text>
        <text x="208" y="138" fill="var(--ink)" fontSize="11.5" fontWeight="600" fontFamily="var(--type-ui)">
          Server Filter
        </text>
        <text x="208" y="154" fill="var(--muted)" fontSize="9.5" fontFamily="var(--type-mono)">
          Qdrant + BM25
        </text>
        <rect x="208" y="164" width="92" height="4" rx="2" fill="var(--accent)" fillOpacity="0.3" />
      </g>

      {/* Card 3: Retrieval & Grader */}
      <g className="animate-idle-float" filter={`url(#card-shadow-${uid})`}>
        <rect
          x="370"
          y="22"
          width="116"
          height="86"
          rx="16"
          fill="var(--surface)"
          stroke="var(--line-strong)"
          strokeWidth="1"
        />
        <text x="384" y="43" fill="var(--faint)" fontSize="8.5" fontWeight="600" fontFamily="var(--type-mono)">
          RE-RANK
        </text>
        <text x="384" y="61" fill="var(--ink)" fontSize="11.5" fontWeight="600" fontFamily="var(--type-ui)">
          Clause Grader
        </text>
        {/* Micro telemetry bars */}
        <rect x="384" y="72" width="14" height="22" rx="4" fill="var(--surface-3)" />
        <rect x="403" y="78" width="14" height="16" rx="4" fill="var(--surface-3)" />
        <rect x="422" y="68" width="14" height="26" rx="4" fill="var(--accent)" />
        <rect x="441" y="75" width="14" height="19" rx="4" fill="var(--surface-2)" />
      </g>

      {/* Card 4: Cited Answer */}
      <g className="animate-idle-float-delayed" filter={`url(#card-shadow-${uid})`}>
        <rect
          x="426"
          y="124"
          width="120"
          height="78"
          rx="16"
          fill="var(--surface)"
          stroke="var(--line-strong)"
          strokeWidth="1"
        />
        <rect x="438" y="137" width="22" height="16" rx="6" fill="var(--accent)" />
        <text x="449" y="148.5" textAnchor="middle" fill="var(--accent-ink)" fontSize="9.5" fontWeight="700" fontFamily="var(--type-mono)">
          [1]
        </text>
        <text x="466" y="149" fill="var(--ink)" fontSize="10.5" fontWeight="600" fontFamily="var(--type-ui)">
          Cited Memo
        </text>
        <rect x="438" y="164" width="94" height="5" rx="2.5" fill="var(--surface-3)" />
        <rect x="438" y="175" width="70" height="5" rx="2.5" fill="var(--surface-2)" />
        <rect x="438" y="186" width="84" height="5" rx="2.5" fill="var(--surface-2)" />
      </g>
    </svg>
  );
}

/**
 * Editorial Compliance Pipeline Hero Card shown on sign-in and onboarding surfaces.
 */
export function TrustMap({ className }: { className?: string }) {
  return (
    <div
      className={cn(
        "rounded-[var(--r-xl)] bg-canvas-raised p-4 shadow-[var(--elev-1)] sm:p-5",
        className,
      )}
    >
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2 text-xs font-mono text-faint">
        <span>EXECUTION TOPOLOGY</span>
        <span className="tabular text-accent-link">0.00% cross-role leakage</span>
      </div>

      <PipelineHeroSvg />

      <p className="mt-2 border-t border-line pt-3 text-xs leading-relaxed text-muted">
        Role clearance filtering executes inside Qdrant and BM25 before retrieved clauses reach
        prompt synthesis or verification.
      </p>
    </div>
  );
}
