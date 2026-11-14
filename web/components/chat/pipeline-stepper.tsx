"use client";

import * as React from "react";
import { Check, CircleDot, Minus } from "lucide-react";

import { formatLatency } from "@/lib/format";
import { cn } from "@/lib/utils";

export interface PipelineStageInfo {
  id: "route" | "retrieve" | "rerank" | "grade" | "answer";
  label: string;
  detail: string;
  latencyMs?: number | null;
  status: "done" | "active" | "pending" | "skipped";
}

function resolveStageLatency(
  timings: Record<string, number> | undefined,
  keys: string[],
): number | null {
  if (!timings) return null;
  for (const key of keys) {
    const val = timings[key];
    if (typeof val === "number" && Number.isFinite(val) && val >= 0) {
      return val;
    }
  }
  return null;
}

export function buildPipelineStages({
  mode = "completed",
  activeIndex = 0,
  routeUsed,
  timings,
}: {
  mode?: "running" | "completed";
  activeIndex?: number;
  routeUsed?: string | null;
  timings?: Record<string, number>;
}): PipelineStageInfo[] {
  const isDirect =
    routeUsed === "DIRECT_REPLY" ||
    routeUsed === "NON_RAG" ||
    routeUsed === "CONVERSATIONAL";

  const definitions: Array<{
    id: PipelineStageInfo["id"];
    label: string;
    detail: string;
    timingKeys: string[];
    skippable: boolean;
  }> = [
    {
      id: "route",
      label: "Route",
      detail: "Intent & gate",
      timingKeys: ["route", "router", "route_ms", "router_ms"],
      skippable: false,
    },
    {
      id: "retrieve",
      label: "Retrieve",
      detail: "Qdrant + BM25",
      timingKeys: ["retrieve", "retrieval", "retrieve_ms", "retrieval_ms"],
      skippable: true,
    },
    {
      id: "rerank",
      label: "Re-rank",
      detail: "Cross-encoder",
      timingKeys: ["rerank", "reranking", "rerank_ms", "reranking_ms"],
      skippable: true,
    },
    {
      id: "grade",
      label: "Grade",
      detail: "Passage check",
      timingKeys: ["grade", "grader", "grade_ms", "grader_ms", "grading_ms"],
      skippable: true,
    },
    {
      id: "answer",
      label: "Answer",
      detail: "Verify & cite",
      timingKeys: ["answer", "synthesis", "generate", "generation", "llm", "answer_ms", "generation_ms"],
      skippable: false,
    },
  ];

  return definitions.map((def, idx) => {
    const latencyMs = resolveStageLatency(timings, def.timingKeys);
    if (mode === "running") {
      const status: PipelineStageInfo["status"] =
        idx < activeIndex ? "done" : idx === activeIndex ? "active" : "pending";
      return {
        id: def.id,
        label: def.label,
        detail: def.detail,
        latencyMs,
        status,
      };
    }

    const explicitlyZeroOnDirect = isDirect && def.skippable;
    const status: PipelineStageInfo["status"] = explicitlyZeroOnDirect ? "skipped" : "done";
    return {
      id: def.id,
      label: def.label,
      detail: def.detail,
      latencyMs: status === "skipped" ? null : latencyMs,
      status,
    };
  });
}

export function PipelineStepper({
  stages,
  compact = false,
  className,
}: {
  stages: PipelineStageInfo[];
  compact?: boolean;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "overflow-x-auto rounded-[var(--r-lg)] bg-canvas-raised p-3.5 shadow-[var(--inner-highlight)]",
        compact && "p-3",
        className,
      )}
      aria-label="Pipeline stage flow"
    >
      <ol className="flex min-w-0 flex-col gap-2 sm:flex-row sm:items-stretch sm:gap-0">
        {stages.map((stage, idx) => {
          const isLast = idx === stages.length - 1;
          const nextStage = stages[idx + 1];
          const connectorActive =
            stage.status === "active" ||
            (stage.status === "done" && nextStage?.status === "active");
          const connectorDone =
            stage.status === "done" &&
            (nextStage?.status === "done" || nextStage?.status === "skipped");

          return (
            <React.Fragment key={stage.id}>
              <li
                data-pipeline-stage={stage.id}
                data-stage-status={stage.status}
                className={cn(
                  "flex min-w-0 items-center justify-between gap-2.5 rounded-[var(--r-md)] px-3 py-2 transition-[background-color,opacity,box-shadow] duration-[var(--duration-base)] sm:min-w-[88px] sm:flex-1 sm:flex-col sm:items-start sm:justify-between sm:gap-1.5 sm:px-2.5 sm:py-2",
                  stage.status === "active" &&
                    "bg-surface shadow-[var(--elev-1)] ring-1 ring-inset ring-line-accent",
                  stage.status === "done" && "bg-surface shadow-[var(--elev-1)]",
                  stage.status === "pending" && "bg-surface-2/50 opacity-75",
                  stage.status === "skipped" && "bg-inset/60 opacity-45",
                )}
              >
                <div className="flex w-full min-w-0 items-center gap-1.5">
                  <span
                    className={cn(
                      "inline-flex size-4 shrink-0 items-center justify-center rounded-full",
                      stage.status === "active" && "bg-accent text-accent-ink",
                      stage.status === "done" && "bg-success-soft text-success",
                      stage.status === "pending" && "bg-surface-3 text-faint",
                      stage.status === "skipped" && "bg-surface-3 text-faint",
                    )}
                    aria-hidden="true"
                  >
                    {stage.status === "done" ? (
                      <Check className="size-2.5" />
                    ) : stage.status === "active" ? (
                      <CircleDot className="size-2.5 animate-soft-pulse" />
                    ) : (
                      <Minus className="size-2.5" />
                    )}
                  </span>
                  <span className="whitespace-nowrap text-xs font-semibold text-ink">{stage.label}</span>
                </div>

                <span
                  className={cn(
                    "tabular shrink-0 whitespace-nowrap rounded-full px-2 py-0.5 font-mono text-[11px] leading-tight",
                    stage.status === "active"
                      ? "bg-accent-soft text-accent-link"
                      : stage.status === "skipped"
                        ? "bg-surface-2 text-faint"
                        : "bg-surface-2 text-muted",
                  )}
                >
                  {stage.status === "skipped"
                    ? "skipped"
                    : stage.latencyMs != null
                      ? formatLatency(stage.latencyMs)
                      : stage.status === "active"
                        ? "active"
                        : stage.status === "done"
                          ? "ran"
                          : "queued"}
                </span>
              </li>

              {!isLast ? (
                <div
                  aria-hidden="true"
                  className="hidden h-5 w-3 shrink-0 items-center justify-center self-center sm:flex"
                >
                  <svg viewBox="0 0 12 8" width="12" height="8" className="overflow-visible">
                    <line
                      x1="0"
                      y1="4"
                      x2="12"
                      y2="4"
                      stroke={
                        connectorActive
                          ? "var(--accent)"
                          : connectorDone
                            ? "var(--storm)"
                            : "var(--line-strong)"
                      }
                      strokeOpacity={stage.status === "skipped" ? 0.35 : 0.85}
                      strokeWidth="1.75"
                      strokeDasharray="3 3"
                      strokeLinecap="round"
                      className={connectorActive ? "pipeline-dash-active" : undefined}
                    />
                  </svg>
                </div>
              ) : null}
            </React.Fragment>
          );
        })}
      </ol>
    </div>
  );
}

