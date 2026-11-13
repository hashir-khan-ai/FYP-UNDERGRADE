"use client";

import * as React from "react";

import { cn } from "@/lib/utils";

/**
 * Signature visual: the trust path from corpus to a verified answer.
 * Pure SVG + CSS; no canvas, no network, no layout shift.
 */
export function TrustMap({ className }: { className?: string }) {
  const frameRef = React.useRef<HTMLDivElement>(null);
  const [reducedMotion, setReducedMotion] = React.useState(false);
  const [tilt, setTilt] = React.useState({ x: 0, y: 0 });

  React.useEffect(() => {
    const query = window.matchMedia("(prefers-reduced-motion: reduce)");
    const update = () => setReducedMotion(query.matches);
    update();
    query.addEventListener("change", update);
    return () => query.removeEventListener("change", update);
  }, []);

  function handlePointerMove(event: React.PointerEvent<HTMLDivElement>) {
    if (reducedMotion) return;
    const frame = frameRef.current;
    if (!frame) return;
    const rect = frame.getBoundingClientRect();
    const x = (event.clientX - rect.left) / rect.width - 0.5;
    const y = (event.clientY - rect.top) / rect.height - 0.5;
    setTilt({ x: y * -4, y: x * 6 });
  }

  return (
    <div
      ref={frameRef}
      onPointerMove={handlePointerMove}
      onPointerLeave={() => setTilt({ x: 0, y: 0 })}
      className={cn("relative select-none", className)}
      aria-hidden="true"
    >
      <div
        className="transition-transform duration-[280ms] ease-[var(--ease-out)] will-change-transform"
        style={{
          transform: reducedMotion
            ? undefined
            : `perspective(900px) rotateX(${tilt.x}deg) rotateY(${tilt.y}deg)`,
        }}
      >
        <svg viewBox="0 0 520 268" className="h-auto w-full overflow-visible">
          <defs>
            <linearGradient id="trust-line" x1="70" y1="0" x2="450" y2="0" gradientUnits="userSpaceOnUse">
              <stop stopColor="rgba(120,169,255,0.1)" />
              <stop offset="0.4" stopColor="rgba(120,169,255,0.65)" />
              <stop offset="0.72" stopColor="rgba(84,214,196,0.6)" />
              <stop offset="1" stopColor="rgba(84,214,196,0.16)" />
            </linearGradient>
            <linearGradient id="trust-node" x1="0" y1="0" x2="1" y2="1">
              <stop stopColor="rgba(120,169,255,0.22)" />
              <stop offset="1" stopColor="rgba(84,214,196,0.08)" />
            </linearGradient>
            <filter id="trust-glow" x="-40%" y="-40%" width="180%" height="180%">
              <feGaussianBlur stdDeviation="5" result="blur" />
              <feMerge>
                <feMergeNode in="blur" />
                <feMergeNode in="SourceGraphic" />
              </feMerge>
            </filter>
          </defs>

          {/* Base path */}
          <path
            d="M92 136 C 150 136, 158 74, 228 74 S 316 136, 356 136 S 404 92, 446 92"
            fill="none"
            stroke="url(#trust-line)"
            strokeWidth="1.4"
            strokeLinecap="round"
            opacity="0.55"
          />
          <path
            d="M92 136 C 150 136, 158 198, 228 198 S 316 136, 356 136 S 404 182, 446 182"
            fill="none"
            stroke="url(#trust-line)"
            strokeWidth="1.4"
            strokeLinecap="round"
            opacity="0.35"
          />

          {/* Travelling verification pulse */}
          {!reducedMotion ? (
            <circle r="2.6" fill="#9cc0ff" filter="url(#trust-glow)">
              <animateMotion
                dur="5.2s"
                repeatCount="indefinite"
                path="M92 136 C 150 136, 158 74, 228 74 S 316 136, 356 136 S 404 92, 446 92"
              />
              <animate attributeName="opacity" values="0;1;1;0" dur="5.2s" repeatCount="indefinite" />
            </circle>
          ) : null}

          {/* Corpus node */}
          <g>
            <rect x="20" y="108" width="72" height="56" rx="14" fill="url(#trust-node)" stroke="rgba(120,169,255,0.3)" />
            <path d="M38 126h36M38 134h28M38 142h32" stroke="rgba(156,192,255,0.72)" strokeWidth="1.6" strokeLinecap="round" />
            <text x="56" y="180" textAnchor="middle" fill="#7f8b9d" fontSize="9.5" letterSpacing="0.08em">
              CORPUS
            </text>
          </g>

          {/* Role gate */}
          <g>
            <rect x="180" y="42" width="96" height="64" rx="16" fill="url(#trust-node)" stroke="rgba(120,169,255,0.4)" />
            <path d="M228 60l12 5v8c0 8-5 13-12 16-7-3-12-8-12-16v-8l12-5Z" fill="none" stroke="#9cc0ff" strokeWidth="1.5" strokeLinejoin="round" />
            <path d="M223 77l3.5 3.5 7-8" fill="none" stroke="#54d6c4" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
            <text x="228" y="98" textAnchor="middle" fill="#a4afbf" fontSize="8.5" letterSpacing="0.07em">
              ROLE GATE
            </text>
          </g>

          {/* Relevance grader */}
          <g>
            <rect x="180" y="166" width="96" height="64" rx="16" fill="url(#trust-node)" stroke="rgba(120,169,255,0.3)" />
            <path d="M212 190h32M212 198h22M212 206h27" stroke="rgba(156,192,255,0.65)" strokeWidth="1.5" strokeLinecap="round" />
            <circle cx="248" cy="204" r="6.5" fill="none" stroke="#54d6c4" strokeWidth="1.5" />
            <path d="m252.5 209 4.5 4.5" stroke="#54d6c4" strokeWidth="1.6" strokeLinecap="round" />
            <text x="228" y="222" textAnchor="middle" fill="#a4afbf" fontSize="8.5" letterSpacing="0.07em">
              GRADER
            </text>
          </g>

          {/* Answer node */}
          <g>
            <rect x="356" y="60" width="120" height="64" rx="16" fill="url(#trust-node)" stroke="rgba(84,214,196,0.36)" />
            <path d="M374 80h44M374 88h58M374 96h38M374 104h26" stroke="rgba(159,238,226,0.7)" strokeWidth="1.5" strokeLinecap="round" />
            <circle cx="458" cy="80" r="4" fill="#54d6c4" filter="url(#trust-glow)" />
            <text x="416" y="140" textAnchor="middle" fill="#7f8b9d" fontSize="9.5" letterSpacing="0.08em">
              VERIFIED ANSWER
            </text>
          </g>

          {/* Refusal node */}
          <g opacity="0.8">
            <rect x="356" y="150" width="120" height="64" rx="16" fill="rgba(255,255,255,0.025)" stroke="rgba(164,184,212,0.18)" strokeDasharray="3 4" />
            <path d="M378 170h44M378 178h58M378 186h34" stroke="rgba(164,184,212,0.4)" strokeWidth="1.5" strokeLinecap="round" />
            <text x="416" y="204" textAnchor="middle" fill="#7f8b9d" fontSize="8.5" letterSpacing="0.07em">
              SAFE REFUSAL
            </text>
          </g>
        </svg>
      </div>
    </div>
  );
}
