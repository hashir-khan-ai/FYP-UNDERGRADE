"use client";

import { ChevronRight, ExternalLink, FileText, LockKeyhole, Search, ShieldAlert, ShieldCheck } from "lucide-react";

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

function CitationCard({ citation, index, role }: { citation: Citation; index: number; role?: string | null }) {
  const links = citationLinks(citation);
  const page = citationPage(citation);
  const hasAccess = citationHasAccess(citation, role);
  const restrictedTo = citationAllowedRoles(citation).map(roleLabel).join(", ");
  const title = citationTitle(citation);
  const heading = citationHeading(citation);
  const clause = citationClause(citation);
  const quote = citation.snippet?.trim() || citation.quote_snippet?.trim();

  return (
    <article className="rounded-[var(--r-md)] border border-line bg-[rgba(3,6,10,0.34)] p-4">
      <div className="flex items-start gap-3">
        <span className="tabular mt-0.5 inline-flex size-6 shrink-0 items-center justify-center rounded-[var(--r-xs)] border border-line bg-surface-2 text-xs font-semibold text-muted">
          {index + 1}
        </span>
        <div className="min-w-0 flex-1">
          {/* Breadcrumb once */}
          <nav aria-label="Source breadcrumb" className="mb-1 flex flex-wrap items-center gap-1.5 text-xs text-muted">
            <span className="font-semibold text-ink">{title}</span>
            {heading && heading !== title ? (
              <>
                <ChevronRight className="size-3 shrink-0 text-faint" aria-hidden="true" />
                <span className="text-ink-soft">{heading}</span>
              </>
            ) : null}
            {clause ? (
              <>
                <ChevronRight className="size-3 shrink-0 text-faint" aria-hidden="true" />
                <span className="font-mono text-accent">{clause}</span>
              </>
            ) : null}
          </nav>

          {/* Source pill (Public or Internal + permitted roles) */}
          <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
            {!hasAccess ? (
              <span className="inline-flex items-center gap-1.5 rounded-full border border-[rgba(255,133,133,0.34)] bg-danger-soft px-3 py-1 text-xs font-semibold text-danger">
                <ShieldAlert className="size-3.5" aria-hidden="true" />
                No access (RBAC-off comparison view)
              </span>
            ) : links.isInternal ? (
              <span className="inline-flex items-center gap-1.5 rounded-full border border-line bg-surface-2 px-3 py-1 text-xs text-ink-soft">
                <LockKeyhole className="size-3 text-faint" aria-hidden="true" />
                Internal ({restrictedTo ? `Permitted: ${restrictedTo}` : "Role restricted"})
              </span>
            ) : links.authority ? (
              <span className="inline-flex items-center gap-1.5 rounded-full border border-[rgba(84,214,196,0.24)] bg-teal-soft px-3 py-1 text-xs text-teal">
                <ShieldCheck className="size-3.5" aria-hidden="true" />
                Public ({links.authority})
              </span>
            ) : (
              <span className="inline-flex items-center gap-1.5 rounded-full border border-line bg-surface-2 px-3 py-1 text-xs text-faint">
                Public source
              </span>
            )}
          </div>

          {/* Clean quote with comfortable 1.55-1.65 line-height */}
          {quote ? (
            <blockquote className="my-3 rounded-[var(--r-sm)] border-l-3 border-accent/60 bg-[rgba(120,169,255,0.06)] px-3.5 py-2.5 text-sm leading-[1.6] text-ink-soft">
              &ldquo;{quote}&rdquo;
            </blockquote>
          ) : null}

          {/* Technical details collapsed */}
          <details className="group/tech mt-2 rounded-[var(--r-xs)] border border-line/60 bg-[rgba(3,6,10,0.25)] px-3 py-2 text-xs">
            <summary className="cursor-pointer select-none font-medium text-faint transition-colors hover:text-ink">
              Technical details & provenance
            </summary>
            <dl className="mt-2.5 grid grid-cols-1 gap-x-4 gap-y-1.5 border-t border-line/40 pt-2 text-xs sm:grid-cols-2">
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
                className="flex w-full items-start gap-2 rounded-[var(--r-xs)] border border-[rgba(255,133,133,0.28)] bg-danger-soft px-3 py-2 text-xs leading-relaxed text-danger"
              >
                <ShieldAlert className="mt-0.5 size-3.5 shrink-0" aria-hidden="true" />
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
                    className="inline-flex min-h-[44px] items-center gap-1.5 text-xs font-medium text-accent underline-offset-2 hover:underline"
                  >
                    <ExternalLink className="size-3.5" aria-hidden="true" />
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
                    <Search className="size-3.5" aria-hidden="true" />
                    Verify on Google
                  </a>
                ) : null}
                {links.internalNote ? (
                  <span className="inline-flex items-center gap-1.5 text-xs text-faint">
                    <LockKeyhole className="size-3" aria-hidden="true" />
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
}: {
  citations: Citation[];
  role?: string | null;
}) {
  if (citations.length === 0) return null;

  return (
    <Collapsible>
      <CollapsibleTrigger className="group inline-flex min-h-[44px] items-center gap-2 rounded-[var(--r-sm)] px-2.5 py-1.5 text-xs font-medium text-muted transition-colors hover:text-ink focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent">
        <ChevronRight
          className="size-4 transition-transform duration-[var(--duration-fast)] group-data-[state=open]:rotate-90"
          aria-hidden="true"
        />
        <FileText className="size-4" aria-hidden="true" />
        Sources ({citations.length})
      </CollapsibleTrigger>
      <CollapsibleContent className="mt-2 space-y-3 data-[state=open]:animate-enter">
        {citations.map((citation, index) => (
          <CitationCard
            key={`${citation.chunk_id ?? citation.doc_id}-${index}`}
            citation={citation}
            index={index}
            role={role}
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
