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

  return (
    <article className="rounded-[var(--r-md)] border border-line bg-[rgba(3,6,10,0.34)] p-3.5">
      <div className="flex items-start gap-2.5">
        <span className="tabular mt-0.5 inline-flex size-5 shrink-0 items-center justify-center rounded-[var(--r-xs)] border border-line bg-surface-2 text-[0.625rem] font-semibold text-muted">
          {index + 1}
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-start justify-between gap-2">
            <h4 className="min-w-0 text-xs font-semibold leading-relaxed text-ink">
              {citationTitle(citation)}
            </h4>
            {!hasAccess ? (
              <span className="inline-flex items-center gap-1 rounded-full border border-[rgba(255,133,133,0.34)] bg-danger-soft px-2 py-0.5 text-[0.625rem] font-semibold text-danger">
                <ShieldAlert className="size-2.5" aria-hidden="true" />
                No access
              </span>
            ) : links.isInternal ? (
              <span className="inline-flex items-center gap-1 rounded-full border border-line bg-surface-2 px-2 py-0.5 text-[0.625rem] text-faint">
                <LockKeyhole className="size-2.5" aria-hidden="true" />
                Internal
              </span>
            ) : links.authority ? (
              <span className="inline-flex items-center gap-1 rounded-full border border-[rgba(84,214,196,0.24)] bg-teal-soft px-2 py-0.5 text-[0.625rem] text-teal">
                <ShieldCheck className="size-2.5" aria-hidden="true" />
                {links.authority}
              </span>
            ) : null}
          </div>

          <dl className="mt-2 grid grid-cols-1 gap-x-4 gap-y-1 text-[0.6875rem] sm:grid-cols-2">
            <div>
              <dt className="text-faint">Heading</dt>
              <dd className="mt-0.5 text-ink-soft">{citationHeading(citation)}</dd>
            </div>
            <div>
              <dt className="text-faint">Clause / section</dt>
              <dd className="mt-0.5 text-ink-soft">{citationClause(citation)}</dd>
            </div>
            {page ? (
              <div>
                <dt className="text-faint">Page</dt>
                <dd className="tabular mt-0.5 text-ink-soft">{page}</dd>
              </div>
            ) : null}
            <div>
              <dt className="text-faint">Source identifier</dt>
              <dd className="mt-0.5 truncate font-mono text-[0.625rem] text-faint">
                {citationIdentifier(citation)}
              </dd>
            </div>
          </dl>

          {citation.snippet?.trim() || citation.quote_snippet?.trim() ? (
            <blockquote className="mt-2.5 border-l-2 border-line-strong pl-2.5 text-[0.6875rem] leading-relaxed text-muted">
              &ldquo;{citation.snippet?.trim() || citation.quote_snippet?.trim()}&rdquo;
            </blockquote>
          ) : null}

          <div className="mt-2.5 flex flex-wrap items-center gap-3">
            {!hasAccess ? (
              <div
                role="status"
                className="flex w-full items-start gap-2 rounded-[var(--r-xs)] border border-[rgba(255,133,133,0.28)] bg-danger-soft px-2.5 py-1.5 text-[0.625rem] leading-relaxed text-danger"
              >
                <ShieldAlert className="mt-px size-3 shrink-0" aria-hidden="true" />
                <span>
                  <span className="font-semibold">Unauthorized access.</span> This source is
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
                    className="inline-flex items-center gap-1 text-[0.6875rem] font-medium text-accent underline-offset-2 hover:underline"
                  >
                    <ExternalLink className="size-3" aria-hidden="true" />
                    Open source
                  </a>
                ) : null}
                {links.verificationUrl ? (
                  <a
                    href={links.verificationUrl}
                    target="_blank"
                    rel="noopener noreferrer nofollow"
                    className="inline-flex items-center gap-1 text-[0.6875rem] font-medium text-muted underline-offset-2 hover:text-ink hover:underline"
                  >
                    <Search className="size-3" aria-hidden="true" />
                    Verify on Google
                  </a>
                ) : null}
                {links.internalNote ? (
                  <span className="inline-flex items-center gap-1 text-[0.625rem] text-faint">
                    <LockKeyhole className="size-2.5" aria-hidden="true" />
                    {links.internalNote}
                  </span>
                ) : null}
                {!links.sourceUrl && !links.verificationUrl && !links.internalNote ? (
                  <span className="text-[0.625rem] text-faint">
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
      <CollapsibleTrigger className="group inline-flex items-center gap-1.5 rounded-[var(--r-xs)] py-1 text-[0.6875rem] font-medium text-muted transition-colors hover:text-ink focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent">
        <ChevronRight
          className="size-3.5 transition-transform duration-[var(--duration-fast)] group-data-[state=open]:rotate-90"
          aria-hidden="true"
        />
        <FileText className="size-3" aria-hidden="true" />
        Sources ({citations.length})
      </CollapsibleTrigger>
      <CollapsibleContent className="mt-2 space-y-2 data-[state=open]:animate-enter">
        {citations.map((citation, index) => (
          <CitationCard
            key={`${citation.chunk_id ?? citation.doc_id}-${index}`}
            citation={citation}
            index={index}
            role={role}
          />
        ))}
        <p className="px-0.5 text-[0.625rem] leading-relaxed text-faint">
          Only sources returned for your role are listed. Internal documents never receive an
          external verification link.
        </p>
      </CollapsibleContent>
    </Collapsible>
  );
}
