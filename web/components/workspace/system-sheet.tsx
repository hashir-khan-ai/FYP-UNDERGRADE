"use client";

import * as React from "react";
import { Activity, RefreshCw, RotateCcw, ServerCog } from "lucide-react";

import { useSessions } from "@/components/providers/sessions-provider";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { api } from "@/lib/api-client";
import { formatCompactNumber, formatLatency, formatNumber } from "@/lib/format";
import type { AdminConfig, HealthResponse } from "@/lib/types";

function Stat({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="rounded-[var(--r-md)] bg-inset px-3.5 py-2.5 shadow-[var(--inner-inset)]">
      <div className="text-xs font-semibold uppercase tracking-[0.06em] text-faint">
        {label}
      </div>
      <div className="mt-1 truncate text-xs font-medium tabular text-ink">{value}</div>
    </div>
  );
}

export function SystemSheet({
  health,
  config,
  trigger,
}: {
  health: HealthResponse | null;
  config: AdminConfig | null;
  trigger?: React.ReactNode;
}) {
  const { activeSessionId, createSession, creating } = useSessions();
  const [open, setOpen] = React.useState(false);
  const [currentHealth, setCurrentHealth] = React.useState(health);
  const [currentConfig, setCurrentConfig] = React.useState(config);
  const [loading, setLoading] = React.useState(false);
  const [resetting, setResetting] = React.useState(false);

  const refresh = React.useCallback(async () => {
    setLoading(true);
    try {
      const [nextHealth, nextConfig] = await Promise.all([
        api.getHealth().catch(() => null),
        api.getAdminConfig(activeSessionId ?? undefined).catch(() => null),
      ]);
      if (nextHealth) setCurrentHealth(nextHealth);
      if (nextConfig) setCurrentConfig(nextConfig);
    } finally {
      setLoading(false);
    }
  }, [activeSessionId]);

  React.useEffect(() => {
    if (open) {
      void refresh();
    }
  }, [open, refresh]);

  async function handleResetRun() {
    if (!activeSessionId || resetting) return;
    setResetting(true);
    try {
      await api.resetRunBudget(activeSessionId);
      await refresh();
    } finally {
      setResetting(false);
    }
  }

  const healthy = currentHealth?.status === "ok" || currentHealth?.status === "healthy";
  const layers = currentConfig?.layers ?? currentHealth?.layers ?? {};
  const runBudget = currentConfig?.run_budget ?? null;
  const profileName = runBudget?.profile ?? currentConfig?.profile ?? currentHealth?.llm.profile ?? "unknown";
  const scopeName = runBudget?.scope ?? (profileName === "mock" ? "offline" : "paid");
  const isPaid = runBudget?.is_paid ?? (currentConfig?.spend_caps?.is_paid === 1);
  const exhausted = Boolean(runBudget?.exhausted ?? (currentConfig?.spend_caps?.exhausted === 1));
  const profileBadgeLabel =
    scopeName === "offline"
      ? "offline-mock"
      : scopeName === "local"
        ? "local-dev"
        : `live-${profileName}`;
  const callsUsed = runBudget?.calls_used ?? currentConfig?.spend_caps?.calls_used ?? 0;
  const callsLimit = runBudget?.calls_limit ?? currentConfig?.spend_caps?.calls_limit ?? 0;
  const tokensUsed = runBudget?.tokens_used ?? currentConfig?.spend_caps?.tokens_used ?? 0;
  const tokensLimit = runBudget?.tokens_limit ?? currentConfig?.spend_caps?.tokens_limit ?? 0;

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        {trigger ?? (
          <Button variant="ghost" size="sm" className="w-full justify-start">
            <ServerCog /> System status
          </Button>
        )}
      </DialogTrigger>
      <DialogContent className="max-w-xl">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Activity className="size-4 text-accent" aria-hidden="true" />
            System status
          </DialogTitle>
          <DialogDescription>
            Live read-only diagnostics. No secrets, prompts or user text are exposed here.
          </DialogDescription>
        </DialogHeader>
        <DialogBody className="space-y-4 pb-2">
          <div className="flex flex-wrap items-center gap-2">
            <Badge tone={healthy ? "success" : "warning"}>
              <span
                className={`size-1.5 rounded-full ${healthy ? "bg-success" : "bg-warning"}`}
                aria-hidden="true"
              />
              {healthy ? "API online" : "API unavailable"}
            </Badge>
            <Badge tone={isPaid ? "warning" : "success"}>Profile: {profileBadgeLabel}</Badge>
            <Badge tone="neutral">Prompt {currentConfig?.prompt_version ?? "—"}</Badge>
            {exhausted ? (
              <Badge tone="danger">Run budget reached</Badge>
            ) : (
              <Badge tone={isPaid ? "neutral" : "success"}>
                {scopeName === "offline"
                  ? "Offline unmetered"
                  : scopeName === "local"
                    ? "Local safety ceiling"
                    : "Run budget ok"}
              </Badge>
            )}
            <Button
              variant="ghost"
              size="sm"
              onClick={() => void refresh()}
              disabled={loading}
              className="ml-auto"
            >
              <RefreshCw className={loading ? "animate-spin" : undefined} />
              Refresh
            </Button>
          </div>

          {exhausted ? (
            <div className="flex flex-wrap items-center justify-between gap-2 rounded-[var(--r-sm)] border border-danger/30 bg-danger-soft px-3 py-2 text-xs text-ink">
              <span>This session&apos;s run budget is exhausted. Reset the current run or start a new session.</span>
              <div className="flex items-center gap-1.5">
                {activeSessionId ? (
                  <Button size="sm" variant="secondary" onClick={() => void handleResetRun()} disabled={resetting}>
                    <RotateCcw className={resetting ? "animate-spin" : undefined} /> Reset run
                  </Button>
                ) : null}
                <Button
                  size="sm"
                  variant="primary"
                  onClick={() => {
                    setOpen(false);
                    void createSession();
                  }}
                  disabled={creating}
                >
                  New session
                </Button>
              </div>
            </div>
          ) : null}

          <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
            <Stat label="Model" value={currentConfig?.model ?? currentHealth?.llm.model ?? "—"} />
            <Stat
              label="Indexed vectors"
              value={formatNumber(currentHealth?.vector_store.total_vectors)}
            />
            <Stat label="Vector mode" value={currentHealth?.vector_store.mode ?? "—"} />
            <Stat
              label={isPaid ? "Run calls (used / cap)" : "Offline/local calls"}
              value={
                currentConfig
                  ? scopeName === "offline"
                    ? `${formatCompactNumber(callsUsed)} (unmetered)`
                    : `${formatCompactNumber(callsUsed)} / ${formatCompactNumber(callsLimit)}`
                  : "—"
              }
            />
            <Stat
              label={isPaid ? "Run tokens (used / cap)" : "Offline/local tokens"}
              value={
                currentConfig
                  ? scopeName === "offline"
                    ? `${formatCompactNumber(tokensUsed)} (unmetered)`
                    : `${formatCompactNumber(tokensUsed)} / ${formatCompactNumber(tokensLimit)}`
                  : "—"
              }
            />
            <Stat label="Session TTL" value={`${currentConfig?.token_ttl_minutes ?? 60} min`} />
          </div>

          <div>
            <div className="mb-2 text-xs font-semibold uppercase tracking-[0.08em] text-faint">
              Architecture layers
            </div>
            <div className="flex flex-wrap gap-1.5">
              {Object.entries(layers).map(([layer, enabled]) => (
                <Badge key={layer} tone={enabled ? "success" : "neutral"}>
                  {layer.replaceAll("_", " ")}
                </Badge>
              ))}
            </div>
          </div>

          <div className="grid grid-cols-2 gap-2">
            <Stat label="Database" value={currentHealth?.database.engine ?? "—"} />
            <Stat
              label="Embedding model"
              value={currentHealth?.models.embeddings ?? "—"}
            />
            <Stat label="Reranker" value={currentHealth?.models.reranker ?? "—"} />
            <Stat
              label="Backend latency"
              value={formatLatency(
                typeof currentConfig?.spend_caps?.last_latency_ms === "number"
                  ? currentConfig.spend_caps.last_latency_ms
                  : null,
              )}
            />
          </div>
        </DialogBody>
      </DialogContent>
    </Dialog>
  );
}
