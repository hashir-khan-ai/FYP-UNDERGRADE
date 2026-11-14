"use client";

import { ShieldAlert } from "lucide-react";

import { Markdown } from "@/components/chat/markdown";
import { Badge } from "@/components/ui/badge";

export function RefusalCard({
  answer,
  category,
  role,
}: {
  answer: string;
  category?: string | null;
  role?: string | null;
}) {
  return (
    <div className="rounded-[var(--r-lg)] bg-warning-soft/55 p-5 shadow-[var(--elev-1)] ring-1 ring-inset ring-warning/25">
      <div className="flex items-start gap-3">
        <span className="mt-0.5 inline-flex size-9 shrink-0 items-center justify-center rounded-[var(--r-md)] bg-warning-soft text-warning ring-1 ring-inset ring-warning/25">
          <ShieldAlert className="size-4.5" aria-hidden="true" />
        </span>
        <div className="min-w-0 flex-1">
          <div className="mb-2 flex flex-wrap items-center gap-2">
            <h4 className="text-sm font-semibold text-ink">No permitted source supports this answer</h4>
            {category ? <Badge tone="warning">{category}</Badge> : null}
            {role ? <Badge tone="outline">{role} scope</Badge> : null}
          </div>
          <div className="answer-prose text-sm">
            <Markdown>{answer}</Markdown>
          </div>
          <p className="mt-3 border-t border-warning/20 pt-2.5 text-xs leading-relaxed text-muted">
            Retrieval was limited to documents your role may read. The assistant refuses rather than
            inventing a passage or revealing a restricted source.
          </p>
        </div>
      </div>
    </div>
  );
}
