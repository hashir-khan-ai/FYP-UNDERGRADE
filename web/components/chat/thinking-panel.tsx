"use client";

import * as React from "react";

import { PipelineStepper, buildPipelineStages } from "@/components/chat/pipeline-stepper";
import { Badge } from "@/components/ui/badge";
import { LedgerSealIcon } from "@/components/ui/icons";
import { CHAT_STAGES } from "@/lib/constants";

export function ThinkingPanel({ stage }: { stage: number }) {
  const safeStage = Math.max(0, Math.min(4, stage));
  const stageKeys = ["route", "retrieve", "rerank", "grade", "answer"] as const;
  const stageStartRef = React.useRef<number>(typeof performance !== "undefined" ? performance.now() : Date.now());
  const [measuredTimings, setMeasuredTimings] = React.useState<Record<string, number>>({});
  const prevStageRef = React.useRef<number>(safeStage);

  React.useEffect(() => {
    const now = typeof performance !== "undefined" ? performance.now() : Date.now();
    if (safeStage > prevStageRef.current) {
      const elapsed = Math.max(1, Math.round(now - stageStartRef.current));
      const completedKey = stageKeys[prevStageRef.current];
      setMeasuredTimings((prev) => (completedKey ? { ...prev, [completedKey]: elapsed } : prev));
      stageStartRef.current = now;
      prevStageRef.current = safeStage;
    } else if (safeStage < prevStageRef.current) {
      stageStartRef.current = now;
      prevStageRef.current = safeStage;
      setMeasuredTimings({});
    }
  }, [safeStage]);

  const stages = buildPipelineStages({
    mode: "running",
    activeIndex: safeStage,
    timings: measuredTimings,
  });

  return (
    <div
      role="status"
      aria-live="polite"
      className="animate-enter rounded-[var(--r-xl)] bg-surface p-5 shadow-[var(--elev-2)] sm:p-6"
    >
      <div className="mb-4 flex flex-wrap items-center justify-between gap-2 border-b border-line pb-3.5">
        <div className="flex items-center gap-2.5">
          <span className="inline-flex size-2.5 rounded-full bg-accent animate-soft-pulse" aria-hidden="true" />
          <span className="text-sm font-semibold text-ink">
            {CHAT_STAGES[safeStage] ?? "Processing compliance query"}
          </span>
        </div>
        <Badge tone="accent">
          <LedgerSealIcon className="size-3.5" />
          Server RBAC Active
        </Badge>
      </div>

      <PipelineStepper stages={stages} />

      <div className="mt-4 space-y-2.5 border-t border-line pt-4" aria-hidden="true">
        <div className="skeleton h-4 w-4/5" />
        <div className="skeleton h-4 w-full" />
        <div className="skeleton h-4 w-3/5" />
      </div>

      <p className="mt-3 text-xs leading-relaxed text-faint">
        Role filtering executes inside Qdrant and BM25 indexes prior to context assembly.
      </p>
    </div>
  );
}
