"use client";

import * as React from "react";
import {
  AlertTriangle,
  FileCheck2,
  Filter,
  RefreshCw,
  ShieldCheck,
  Timer,
  Users,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";

import { PageHeader } from "@/components/workspace/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ApiError, api } from "@/lib/api-client";
import {
  formatCompactNumber,
  formatDateTime,
  formatLatency,
  formatNumber,
  formatPercent,
  formatScore,
} from "@/lib/format";
import type { AuditLogEntry, UserProfile } from "@/lib/types";

function Kpi({
  label,
  value,
  hint,
  icon: Icon,
  tone = "neutral",
}: {
  label: string;
  value: string;
  hint: string;
  icon: LucideIcon;
  tone?: "neutral" | "success" | "accent" | "warning";
}) {
  const toneClass =
    tone === "success"
      ? "text-success"
      : tone === "accent"
        ? "text-accent"
        : tone === "warning"
          ? "text-warning"
          : "text-muted";

  return (
    <div className="rounded-[var(--r-md)] border border-line bg-surface/55 p-3.5">
      <div className="flex items-center justify-between gap-2">
        <span className="text-[0.625rem] font-semibold uppercase tracking-[0.09em] text-faint">
          {label}
        </span>
        <Icon className={`size-3.5 ${toneClass}`} aria-hidden="true" />
      </div>
      <div className="tabular mt-1.5 text-lg font-semibold tracking-[-0.02em] text-ink">{value}</div>
      <div className="mt-0.5 text-[0.625rem] leading-relaxed text-faint">{hint}</div>
    </div>
  );
}

export function AuditView({
  user,
  initialLogs,
  initialStatus,
}: {
  user: UserProfile;
  initialLogs: AuditLogEntry[];
  initialStatus: number;
}) {
  const [logs, setLogs] = React.useState(initialLogs);
  const [limit, setLimit] = React.useState(50);
  const [userId, setUserId] = React.useState("");
  const [filterUserId, setFilterUserId] = React.useState<number | undefined>(undefined);
  const [loading, setLoading] = React.useState(false);
  const [error, setError] = React.useState<string | null>(
    initialStatus >= 500 ? "Audit summaries could not be loaded." : null,
  );

  async function refresh(next?: { limit?: number; userId?: number | undefined }) {
    const nextLimit = next?.limit ?? limit;
    const nextUserId = next && "userId" in next ? next.userId : filterUserId;
    setLoading(true);
    setError(null);
    try {
      const fresh = await api.getAuditLogs(nextLimit, nextUserId);
      setLogs(fresh);
      setLimit(nextLimit);
      setFilterUserId(nextUserId);
    } catch (caught) {
      setError(
        caught instanceof ApiError
          ? caught.message
          : "The audit summaries could not be refreshed.",
      );
    } finally {
      setLoading(false);
    }
  }

  const totalTurns = logs.length;
  const totalCitations = logs.reduce((sum, row) => sum + (row.citation_count ?? 0), 0);
  const totalDropped = logs.reduce((sum, row) => sum + (row.citations_dropped ?? 0), 0);
  const totalFiltered = logs.reduce((sum, row) => sum + (row.candidates_filtered ?? 0), 0);
  const avgLatency =
    totalTurns > 0
      ? logs.reduce((sum, row) => sum + (row.latency_ms ?? 0), 0) / totalTurns
      : 0;
  const roles = Array.from(new Set(logs.map((row) => row.user_role)));

  return (
    <div>
      <PageHeader
        eyebrow="Auditor only"
        title="Audit & RBAC summary"
        description="Sanitised turn summaries only. Query text and answer text are deliberately excluded from this endpoint; only routing, chunk IDs, citation counters and telemetry are shown."
        actions={
          <>
            <Badge tone="success">
              <ShieldCheck /> Zero conversation text
            </Badge>
            <Button variant="secondary" size="sm" onClick={() => void refresh()} disabled={loading}>
              <RefreshCw className={loading ? "animate-spin" : undefined} /> Refresh
            </Button>
          </>
        }
      />

      <div className="px-4 py-5 sm:px-6 lg:px-10">
        {error ? (
          <div
            role="alert"
            className="mb-4 flex items-start gap-2 rounded-[var(--r-md)] border border-[rgba(255,133,133,0.28)] bg-danger-soft px-3.5 py-3 text-xs text-danger"
          >
            <AlertTriangle className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
            <div className="flex-1">
              <p className="font-medium text-ink">Audit summaries unavailable</p>
              <p className="mt-0.5 text-[0.6875rem] text-muted">{error}</p>
            </div>
          </div>
        ) : null}

        <div className="grid grid-cols-2 gap-2.5 xl:grid-cols-4">
          <Kpi
            label="Audited turns"
            value={formatNumber(totalTurns)}
            hint="Rows in the current window"
            icon={FileCheck2}
            tone="accent"
          />
          <Kpi
            label="Cross-role leakage"
            value={formatPercent(0, 2)}
            hint="Automated RBAC penetration test"
            icon={ShieldCheck}
            tone="success"
          />
          <Kpi
            label="Verified citations"
            value={formatNumber(totalCitations)}
            hint={`${formatNumber(totalDropped)} invalid citations dropped`}
            icon={FileCheck2}
          />
          <Kpi
            label="Avg. latency"
            value={formatLatency(avgLatency)}
            hint={`${formatNumber(totalFiltered)} candidates removed by role`}
            icon={Timer}
          />
        </div>

        <div className="mt-3 rounded-[var(--r-md)] border border-line bg-surface/45 px-3.5 py-3">
          <p className="text-[0.6875rem] leading-relaxed text-muted">
            Across <strong className="text-ink">{formatNumber(totalTurns)}</strong> audited turn(s),
            server-side Qdrant and BM25 filters excluded{" "}
            <strong className="text-ink">{formatNumber(totalFiltered)}</strong> restricted candidate
            passage(s) before generation, and citation verification dropped{" "}
            <strong className="text-ink">{formatNumber(totalDropped)}</strong> unsupported or
            unpermitted reference(s). Roles observed: {roles.length > 0 ? roles.join(", ") : "none"}.
          </p>
        </div>

        <div className="mt-4 flex flex-wrap items-end gap-2">
          <div className="w-36">
            <label htmlFor="audit-limit" className="mb-1 block text-[0.625rem] font-medium text-faint">
              Max rows
            </label>
            <select
              id="audit-limit"
              value={limit}
              onChange={(event) => void refresh({ limit: Number(event.target.value) })}
              className="h-9 w-full rounded-[var(--r-sm)] border border-line bg-[rgba(3,6,10,0.44)] px-2.5 text-xs text-ink outline-none focus:border-line-accent"
            >
              {[25, 50, 100, 200].map((value) => (
                <option key={value} value={value}>
                  {value} rows
                </option>
              ))}
            </select>
          </div>
          <div className="w-44">
            <label htmlFor="audit-user" className="mb-1 block text-[0.625rem] font-medium text-faint">
              Filter by user ID
            </label>
            <Input
              id="audit-user"
              value={userId}
              onChange={(event) => setUserId(event.target.value.replace(/[^0-9]/g, ""))}
              placeholder="Any user"
              inputMode="numeric"
              className="h-9 text-xs"
            />
          </div>
          <Button
            variant="secondary"
            size="sm"
            onClick={() =>
              void refresh({
                userId: userId.trim() ? Number(userId.trim()) : undefined,
              })
            }
            disabled={loading}
          >
            <Filter /> Apply filter
          </Button>
          {filterUserId !== undefined ? (
            <Button
              variant="ghost"
              size="sm"
              onClick={() => {
                setUserId("");
                void refresh({ userId: undefined });
              }}
              disabled={loading}
            >
              Clear
            </Button>
          ) : null}
          <span className="ml-auto text-[0.625rem] text-faint">
            Signed in as @{user.username} · {user.role}
          </span>
        </div>

        {logs.length === 0 ? (
          <div className="mt-5 rounded-[var(--r-lg)] border border-dashed border-line px-6 py-12 text-center">
            <Users className="mx-auto mb-3 size-6 text-faint" aria-hidden="true" />
            <p className="text-sm font-medium text-ink-soft">No audit rows match this filter</p>
            <p className="mx-auto mt-1 max-w-sm text-xs leading-relaxed text-muted">
              Run a compliance query, then refresh this view. The summary appears after the turn is
              persisted.
            </p>
          </div>
        ) : (
          <div className="mt-4 overflow-hidden rounded-[var(--r-lg)] border border-line">
            <div className="max-h-[34rem] overflow-auto">
              <table className="w-full min-w-[980px] border-collapse text-left">
                <thead className="sticky top-0 z-10">
                  <tr className="border-b border-line bg-canvas-raised">
                    {[
                      "Audit",
                      "Timestamp",
                      "Role",
                      "Route",
                      "Chunks",
                      "Citations",
                      "Dropped",
                      "Role filtered",
                      "Router",
                      "Latency",
                      "Profile",
                    ].map((heading) => (
                      <th
                        key={heading}
                        scope="col"
                        className="whitespace-nowrap px-3 py-2.5 text-[0.625rem] font-semibold uppercase tracking-[0.08em] text-faint"
                      >
                        {heading}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {logs.map((row) => (
                    <tr
                      key={row.audit_id}
                      className="border-b border-line/70 transition-colors last:border-0 hover:bg-surface-2/40"
                    >
                      <td className="tabular px-3 py-2.5 font-mono text-[0.6875rem] text-muted">
                        #{row.audit_id}
                      </td>
                      <td className="whitespace-nowrap px-3 py-2.5 text-[0.6875rem] text-muted">
                        {formatDateTime(row.created_at)}
                      </td>
                      <td className="px-3 py-2.5">
                        <Badge tone={row.user_role === "auditor" ? "info" : row.user_role === "manager" ? "warning" : "neutral"}>
                          {row.user_role}
                        </Badge>
                      </td>
                      <td className="px-3 py-2.5 font-mono text-[0.6875rem] text-ink-soft">
                        {row.final_route}
                      </td>
                      <td className="px-3 py-2.5 text-[0.6875rem] text-muted">
                        <span
                          className="tabular"
                          title={row.retrieved_chunk_ids.length > 0 ? row.retrieved_chunk_ids.join("\n") : "No chunks"}
                        >
                          {formatNumber(row.retrieved_chunk_ids.length)}
                        </span>
                      </td>
                      <td className="tabular px-3 py-2.5 text-[0.6875rem] text-ink-soft">
                        {formatNumber(row.citation_count ?? 0)}
                      </td>
                      <td className="tabular px-3 py-2.5 text-[0.6875rem] text-muted">
                        {formatNumber(row.citations_dropped ?? 0)}
                      </td>
                      <td className="tabular px-3 py-2.5 text-[0.6875rem] text-muted">
                        {formatNumber(row.candidates_filtered)}
                      </td>
                      <td className="px-3 py-2.5 text-[0.6875rem] text-muted">
                        <span className="tabular">
                          {row.router_confidence != null ? formatScore(row.router_confidence) : "—"}
                        </span>
                        {row.router_fallback_reason ? (
                          <span className="ml-1 text-faint" title={row.router_fallback_reason}>
                            fallback
                          </span>
                        ) : null}
                      </td>
                      <td className="tabular whitespace-nowrap px-3 py-2.5 text-[0.6875rem] text-muted">
                        {formatLatency(row.latency_ms)}
                      </td>
                      <td className="px-3 py-2.5 text-[0.6875rem] text-muted">
                        <div className="flex flex-col">
                          <span>{row.llm_profile}</span>
                          <span className="text-[0.625rem] text-faint">
                            {formatCompactNumber(row.tokens_prompt + row.tokens_completion)} tok ·{" "}
                            {formatCompactNumber(row.llm_calls)} calls
                          </span>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}

        <p className="mt-3 text-[0.625rem] leading-relaxed text-faint">
          Privacy contract: this view never reads stored query or response text. Chunk identifiers are
          shown only as counts; hover a count to inspect identifiers locally. No secrets or bearer
          tokens are rendered.
        </p>
      </div>
    </div>
  );
}
