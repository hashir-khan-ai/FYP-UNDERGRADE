"use client";

import * as React from "react";
import { ChevronRight, ExternalLink, LockKeyhole, Search, ShieldAlert, ShieldCheck } from "lucide-react";

import { ClausePinIcon } from "@/components/ui/icons";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import { roleLabel } from "@/lib/auth";
import {
  citationAllowedRoles,
  citationClause,
  citationHasAccess,
  citationHeading,
  citationIdentifier,
  citationLinks,
  citationPage,
  citationTitle,
} from "@/lib/citations";
import type { Citation } from "@/lib/types";
import { cn } from "@/lib/utils";

function CitationCard({
  citation,
  index,
  role,
  turnId,
  isActive,
  isPulsed,
  onHoverIndex,
}: {
  citation: Citation;
  index: number;
  role?: string | null;
  turnId?: number;
  isActive?: boolean;
  isPulsed?: boolean;
  onHoverIndex?: (index: number | null) => void;
}) {
  const links = citationLinks(citation);
  const page = citationPage(citation);
  const hasAccess = citationHasAccess(citation, role);
  const restrictedTo = citationAllowedRoles(citation).map(roleLabel).join(", ");
  const title = citationTitle(citation);
  const heading = citationHeading(citation);
  const clause = citationClause(citation);
  const quote = citation.snippet?.trim() || citation.quote_snippet?.trim();

  return (
    <article
      id={turnId !== undefined ? `cite-${turnId}-${index}` : undefined}
      data-cite-card={index + 1}
      onMouseEnter={() => onHoverIndex?.(index)}
      onMouseLeave={() => onHoverIndex?.(null)}
      onFocus={() => onHoverIndex?.(index)}
      onBlur={() => onHoverIndex?.(null)}
      className={cn(
        "rounded-[var(--r-xl)] bg-surface p-5 shadow-[var(--elev-1)] transition-[box-shadow,background-color] duration-200 sm:p-6",
        isActive
          ? "bg-surface-2 shadow-[var(--elev-2)] ring-2 ring-inset ring-line-accent"
          : "hover:shadow-[var(--elev-2)]",
        isPulsed && "animate-cite-pulse",
      )}
    >
      <div className="flex items-start gap-3.5">
        <span
          className={cn(
            "tabular mt-0.5 inline-flex size-8 shrink-0 items-center justify-center rounded-[var(--r-sm)] font-mono text-sm font-semibold transition-colors",
            isActive
              ? "bg-accent text-accent-ink shadow-[var(--elev-1)]"
              : "bg-inset text-ink-soft shadow-[var(--inner-inset)]",
          )}
        >
          {index + 1}
        </span>
        <div className="min-w-0 flex-1">
          {/* Big clause callout when available */}
          {clause ? (
            <div className="mb-1 flex flex-wrap items-baseline justify-between gap-2">
              <p className="font-mono text-lg font-semibold tracking-tight text-accent-link">
                {clause}
              </p>
            </div>
          ) : null}

          {/* Breadcrumb once */}
          <nav aria-label="Source breadcrumb" className="mb-2 flex flex-wrap items-center gap-x-1.5 gap-y-1 text-xs text-muted">
            <span className="font-semibold text-ink">{title}</span>
            {heading && heading !== title ? (
              <span className="inline-flex items-center gap-1.5 text-ink-soft">
                <ChevronRight className="size-3.5 shrink-0 text-faint" aria-hidden="true" />
                <span>{heading}</span>
              </span>
            ) : null}
          </nav>

          {/* Unified h-7 pill scale (Public or Internal + permitted roles) */}
          <div className="mb-2.5 flex flex-wrap items-center justify-between gap-2">
            {!hasAccess ? (
              <span className="inline-flex h-7 items-center gap-1.5 rounded-full bg-danger-soft px-3 text-xs font-semibold text-danger ring-1 ring-inset ring-danger/30">
                <ShieldAlert className="size-3.5" aria-hidden="true" />
                No access (RBAC-off comparison view)
              </span>
            ) : links.isInternal ? (
              <span className="inline-flex h-7 items-center gap-1.5 rounded-full bg-inset px-3 text-xs font-medium text-ink-soft shadow-[var(--inner-inset)]">
                <LockKeyhole className="size-3.5 text-faint" aria-hidden="true" />
                Internal ({restrictedTo ? `Permitted: ${restrictedTo}` : "Role restricted"})
              </span>
            ) : links.authority ? (
              <span className="inline-flex h-7 items-center gap-1.5 rounded-full bg-teal-soft px-3 text-xs font-medium text-teal ring-1 ring-inset ring-teal/30">
                <ShieldCheck className="size-3.5" aria-hidden="true" />
                Public ({links.authority})
              </span>
            ) : (
              <span className="inline-flex h-7 items-center gap-1.5 rounded-full bg-inset px-3 text-xs font-medium text-faint shadow-[var(--inner-inset)]">
                Public source
              </span>
            )}
          </div>

          {/* Verbatim quote styled as restrained serif inset */}
          {quote ? (
            <blockquote className="my-3 rounded-[var(--r-md)] border-l-2 border-accent/70 bg-inset py-3 pl-4 pr-4 font-display text-base italic leading-[1.6] text-ink-soft shadow-[var(--inner-inset)]">
              &ldquo;{quote}&rdquo;
            </blockquote>
          ) : null}

          {/* Provenance hairline disclosure (avoid nested card chrome) */}
          <details className="group/tech mt-3 border-t border-line/70 pt-2.5 text-xs">
            <summary className="cursor-pointer select-none font-medium text-faint transition-colors hover:text-ink">
              Technical details & provenance
            </summary>
            <dl className="mt-2.5 grid grid-cols-1 gap-x-4 gap-y-2 border-t border-line/40 pt-2.5 text-xs sm:grid-cols-2">
              <div>
                <dt className="text-faint">Heading</dt>
                <dd className="mt-0.5 text-ink-soft">{heading || "None"}</dd>
              </div>
              <div>
                <dt className="text-faint">Clause / section</dt>
                <dd className="mt-0.5 text-ink-soft">{clause || "None"}</dd>
              </div>
              {page ? (
                <div>
                  <dt className="text-faint">Page</dt>
                  <dd className="tabular mt-0.5 text-ink-soft">{page}</dd>
                </div>
              ) : null}
              <div>
                <dt className="text-faint">Source identifier</dt>
                <dd className="mt-0.5 truncate font-mono text-xs text-faint">
                  {citationIdentifier(citation)}
                </dd>
              </div>
            </dl>
          </details>

          <div className="mt-3 flex flex-wrap items-center gap-3">
            {!hasAccess ? (
              <div
                role="status"
                className="flex w-full items-start gap-2 rounded-[var(--r-sm)] bg-danger-soft px-3.5 py-2.5 text-xs leading-relaxed text-danger ring-1 ring-inset ring-danger/30"
              >
                <ShieldAlert className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
                <span>
                  <span className="font-semibold">Unauthorized access (RBAC-off comparison view).</span> This source is
                  restricted to {restrictedTo || "another role"}, outside your role&rsquo;s
                  clearance.
                </span>
              </div>
            ) : (
              <>
                {links.sourceUrl ? (
                  <a
                    href={links.sourceUrl}
                    target="_blank"
                    rel="noopener noreferrer nofollow"
                    className="inline-flex min-h-[44px] items-center gap-1.5 text-xs font-medium text-accent-link underline-offset-2 hover:underline"
                  >
                    <ExternalLink className="size-4" aria-hidden="true" />
                    Open source
                  </a>
                ) : null}
                {links.verificationUrl ? (
                  <a
                    href={links.verificationUrl}
                    target="_blank"
                    rel="noopener noreferrer nofollow"
                    className="inline-flex min-h-[44px] items-center gap-1.5 text-xs font-medium text-muted underline-offset-2 hover:text-ink hover:underline"
                  >
                    <Search className="size-4" aria-hidden="true" />
                    Verify on Google
                  </a>
                ) : null}
                {links.internalNote ? (
                  <span className="inline-flex items-center gap-1.5 text-xs text-faint">
                    <LockKeyhole className="size-3.5" aria-hidden="true" />
                    {links.internalNote}
                  </span>
                ) : null}
                {!links.sourceUrl && !links.verificationUrl && !links.internalNote ? (
                  <span className="text-xs text-faint">
                    No external link is available for this source.
                  </span>
                ) : null}
              </>
            )}
          </div>
        </div>
      </div>
    </article>
  );
}

export function CitationsPanel({
  citations,
  role,
  turnId,
  open,
  onOpenChange,
  activeIndex,
  pulsedIndex,
  onHoverIndex,
}: {
  citations: Citation[];
  role?: string | null;
  turnId?: number;
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
  activeIndex?: number | null;
  pulsedIndex?: number | null;
  onHoverIndex?: (index: number | null) => void;
}) {
  const [internalOpen, setInternalOpen] = React.useState(false);
  const resolvedOpen = open ?? internalOpen;
  const setResolvedOpen = onOpenChange ?? setInternalOpen;

  if (citations.length === 0) return null;

  return (
    <Collapsible open={resolvedOpen} onOpenChange={setResolvedOpen}>
      <CollapsibleTrigger className="group inline-flex min-h-[44px] items-center gap-2 rounded-[var(--r-md)] bg-surface px-3.5 py-2 text-xs font-medium text-muted shadow-[var(--elev-1)] transition-[background-color,color,box-shadow] duration-[var(--duration-fast)] hover:bg-surface-2 hover:text-ink focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent">
        <ChevronRight
          className="size-4 transition-transform duration-[var(--duration-fast)] group-data-[state=open]:rotate-90"
          aria-hidden="true"
        />
        <ClausePinIcon className="size-4 text-accent-link" aria-hidden="true" />
        Sources ({citations.length})
      </CollapsibleTrigger>
      <CollapsibleContent className="mt-3 space-y-3.5 rounded-[var(--r-xl)] bg-canvas-raised p-4 shadow-[var(--elev-2)] data-[state=open]:animate-enter">
        {citations.map((citation, index) => (
          <CitationCard
            key={`${citation.chunk_id ?? citation.doc_id}-${index}`}
            citation={citation}
            index={index}
            role={role}
            turnId={turnId}
            isActive={activeIndex === index}
            isPulsed={pulsedIndex === index}
            onHoverIndex={onHoverIndex}
          />
        ))}
        <p className="px-1 text-xs leading-relaxed text-faint">
          Only sources returned for your role are listed. Internal documents never receive an
          external verification link.
        </p>
      </CollapsibleContent>
    </Collapsible>
  );
}
