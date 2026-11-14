"use client";

import type { ReactNode } from "react";
import { ChevronRight, Gauge, Route } from "lucide-react";

import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import { Badge } from "@/components/ui/badge";
import { formatCompactNumber, formatLatency, formatScore } from "@/lib/format";
import type { Message } from "@/lib/types";

function Row({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-3 border-b border-line/60 py-1.5 last:border-0">
      <dt className="text-xs text-faint">{label}</dt>
      <dd className="max-w-[60%] truncate text-right font-mono text-xs text-ink-soft">
        {value}
      </dd>
    </div>
  );
}

export function AdvancedDetails({ message }: { message: Message }) {
  const metadata = message.metadata;
  if (!metadata) return null;

  const timings = metadata.timings ?? {};
  const trace = metadata.reasoning_trace ?? [];
  const router = metadata.router;

  return (
    <Collapsible>
      <CollapsibleTrigger className="group inline-flex min-h-[44px] items-center gap-2 rounded-[var(--r-xs)] px-2.5 py-1 text-xs font-medium text-muted transition-colors hover:text-ink focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent">
        <ChevronRight
          className="size-4 transition-transform duration-[var(--duration-fast)] group-data-[state=open]:rotate-90"
          aria-hidden="true"
        />
        <Route className="size-4" aria-hidden="true" />
        Pipeline details
      </CollapsibleTrigger>
      <CollapsibleContent className="mt-2 data-[state=open]:animate-enter">
        <div className="rounded-[var(--r-md)] border border-line bg-[rgba(3,6,10,0.3)] p-3">
          <div className="mb-2 flex flex-wrap gap-1.5">
            <Badge tone="outline">{message.route_used ?? "unknown route"}</Badge>
            {metadata.intent_mode ? <Badge tone="neutral">intent: {metadata.intent_mode}</Badge> : null}
            {metadata.response_type ? (
              <Badge tone="neutral">type: {metadata.response_type}</Badge>
            ) : null}
            {metadata.grader_path ? (
              <Badge tone="neutral">grader: {metadata.grader_path}</Badge>
            ) : null}
          </div>

          <dl className="grid gap-x-6 sm:grid-cols-2">
            <div>
              <Row label="Latency" value={formatLatency(metadata.latency_ms)} />
              <Row label="LLM profile" value={metadata.llm_profile ?? "—"} />
              <Row label="Model" value={metadata.llm_model ?? "—"} />
              <Row label="Chunks cited" value={formatCompactNumber(metadata.chunk_ids?.length ?? 0)} />
            </div>
            <div>
              <Row label="Prompt tokens" value={formatCompactNumber(metadata.tokens_prompt ?? 0)} />
              <Row
                label="Completion tokens"
                value={formatCompactNumber(metadata.tokens_completion ?? 0)}
              />
              <Row label="Citations dropped" value={formatCompactNumber(metadata.citations_dropped ?? 0)} />
              <Row
                label="Router confidence"
                value={router?.confidence != null ? formatScore(router.confidence) : "—"}
              />
              <Row label="Cached" value={metadata.cached ? "yes" : "no"} />
            </div>
          </dl>

          {router ? (
            <div className="mt-3 border-t border-line pt-2.5">
              <div className="mb-2 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-[0.08em] text-faint">
                <Gauge className="size-3.5" aria-hidden="true" />
                Router
              </div>
              <dl>
                <Row label="Route" value={router.route} />
                <Row label="Fallback" value={router.fallback_used ? router.fallback_reason ?? "yes" : "no"} />
                <Row label="Sub-questions" value={formatCompactNumber(router.sub_questions?.length ?? 0)} />
                <Row label="Router tokens" value={formatCompactNumber(router.tokens_used ?? 0)} />
              </dl>
            </div>
          ) : null}

          {Object.keys(timings).length > 0 ? (
            <div className="mt-3 border-t border-line pt-2.5">
              <div className="mb-2 text-xs font-semibold uppercase tracking-[0.08em] text-faint">
                Stage timings (ms)
              </div>
              <div className="flex flex-wrap gap-2">
                {Object.entries(timings).map(([stage, value]) => (
                  <span
                    key={stage}
                    className="rounded-[var(--r-xs)] border border-line bg-surface-2/60 px-2 py-1 font-mono text-xs text-muted"
                  >
                    {stage}: {Math.round(value)}
                  </span>
                ))}
              </div>
            </div>
          ) : null}

          {trace.length > 0 ? (
            <div className="mt-3 border-t border-line pt-2.5">
              <div className="mb-2 text-xs font-semibold uppercase tracking-[0.08em] text-faint">
                Reasoning trace
              </div>
              <ol className="space-y-1.5">
                {trace.map((step, index) => (
                  <li key={`${index}-${step}`} className="flex gap-2 text-xs leading-relaxed text-muted">
                    <span className="tabular shrink-0 text-faint">{String(index + 1).padStart(2, "0")}</span>
                    <span className="min-w-0 break-words">{step}</span>
                  </li>
                ))}
              </ol>
            </div>
          ) : null}

          <p className="mt-3 border-t border-line pt-2.5 text-xs leading-relaxed text-faint">
            Retrieved passages were treated as untrusted data inside an explicit XML boundary.
            Instructions found inside documents are ignored.
          </p>
        </div>
      </CollapsibleContent>
    </Collapsible>
  );
}
