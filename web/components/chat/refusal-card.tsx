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
    <div className="rounded-[var(--r-md)] border border-[rgba(240,195,106,0.26)] bg-warning-soft/45 p-4">
      <div className="flex items-start gap-2.5">
        <span className="mt-0.5 inline-flex size-7 shrink-0 items-center justify-center rounded-full border border-[rgba(240,195,106,0.32)] bg-warning-soft text-warning">
          <ShieldAlert className="size-4" aria-hidden="true" />
        </span>
        <div className="min-w-0 flex-1">
          <div className="mb-1.5 flex flex-wrap items-center gap-2">
            <h4 className="text-xs font-semibold text-ink">No permitted source supports this answer</h4>
            {category ? <Badge tone="warning">{category}</Badge> : null}
            {role ? <Badge tone="outline">{role} scope</Badge> : null}
          </div>
          <div className="answer-prose text-[0.8125rem]">
            <Markdown>{answer}</Markdown>
          </div>
          <p className="mt-2.5 border-t border-[rgba(240,195,106,0.2)] pt-2 text-[0.625rem] leading-relaxed text-muted">
            Retrieval was limited to documents your role may read. The assistant refuses rather than
            inventing a passage or revealing a restricted source.
          </p>
        </div>
      </div>
    </div>
  );
}
