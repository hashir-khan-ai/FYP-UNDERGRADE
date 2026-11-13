"use client";

import * as React from "react";
import {
  Activity,
  Archive,
  ChevronRight,
  FileCheck2,
  Landmark,
  Layers,
  ScanSearch,
  ShieldAlert,
  Sparkles,
  Scale,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import { DEMO_PRESETS, ROLE_STARTERS, type StarterIcon } from "@/lib/constants";
import { roleLabel, roleScope } from "@/lib/auth";
import type { IntentMode, Role } from "@/lib/types";

const STARTER_ICONS: Record<StarterIcon, LucideIcon> = {
  landmark: Landmark,
  "scan-search": ScanSearch,
  "shield-alert": ShieldAlert,
  scale: Scale,
  "file-check": FileCheck2,
  layers: Layers,
  archive: Archive,
  activity: Activity,
};

const TONE: Record<string, "success" | "warning" | "danger" | "info" | "neutral"> = {
  public: "success",
  restricted: "warning",
  confidential: "danger",
  decomposed: "info",
  refusal: "neutral",
  adversarial: "danger",
};

export function ChatEmptyState({
  role,
  name,
  onAsk,
  sending,
}: {
  role: string;
  name: string;
  onAsk: (query: string, intent?: IntentMode) => void;
  sending: boolean;
}) {
  const normalized = (role === "analyst" || role === "manager" || role === "auditor"
    ? role
    : "analyst") as Role;
  const starters = ROLE_STARTERS[normalized];
  const firstName = name.trim().split(/\s+/)[0] || "there";

  return (
    <div className="mx-auto w-full max-w-3xl px-4 py-8 sm:py-12">
      <div className="text-center">
        <Badge tone="accent" className="mb-4">
          <Sparkles /> {roleLabel(role)} workspace
        </Badge>
        <h2 className="text-xl font-semibold tracking-[-0.025em] text-ink sm:text-2xl">
          Good to see you, {firstName}.
        </h2>
        <p className="mx-auto mt-2 max-w-xl text-sm leading-relaxed text-muted">
          Ask a compliance question and the assistant will retrieve only the documents your role
          may read, verify every citation, and refuse when the corpus does not support an answer.
        </p>
        <p className="mt-2 text-[0.6875rem] text-faint">{roleScope(role)}</p>
      </div>

      <div className="mt-7 grid gap-2.5 sm:grid-cols-3">
        {starters.map((starter) => {
          const Icon = STARTER_ICONS[starter.icon];
          return (
            <button
              key={starter.title}
              type="button"
              onClick={() => onAsk(starter.query, "auto")}
              disabled={sending}
              className="group flex h-full flex-col items-start rounded-[var(--r-md)] border border-line bg-surface/60 p-3.5 text-left transition-[border-color,background-color,transform,box-shadow] duration-[var(--duration-base)] ease-[var(--ease-out)] hover:-translate-y-0.5 hover:border-line-accent hover:bg-surface-2 hover:shadow-[var(--elev-md)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:pointer-events-none disabled:opacity-60"
            >
              <span className="mb-2.5 inline-flex size-7 items-center justify-center rounded-[var(--r-sm)] border border-line bg-surface-2 text-accent">
                <Icon className="size-3.5" aria-hidden="true" />
              </span>
              <span className="text-xs font-semibold text-ink">{starter.title}</span>
              <span className="mt-1 line-clamp-3 text-[0.6875rem] leading-relaxed text-muted">
                {starter.query}
              </span>
              <span className="mt-3 inline-flex items-center gap-1 text-[0.625rem] font-medium text-faint group-hover:text-accent">
                Ask this <ChevronRight className="size-3" aria-hidden="true" />
              </span>
            </button>
          );
        })}
      </div>

      <Collapsible className="mt-5">
        <CollapsibleTrigger className="group mx-auto flex items-center gap-1.5 rounded-full border border-line bg-surface-2/60 px-3 py-1.5 text-[0.6875rem] font-medium text-muted transition-colors hover:border-line-strong hover:text-ink focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent">
          <ChevronRight
            className="size-3.5 transition-transform duration-[var(--duration-fast)] group-data-[state=open]:rotate-90"
            aria-hidden="true"
          />
          Demo scenarios for your viva
        </CollapsibleTrigger>
        <CollapsibleContent className="mt-3 data-[state=open]:animate-enter">
          <div className="grid gap-2 sm:grid-cols-2">
            {DEMO_PRESETS.map((preset) => (
              <button
                key={preset.id}
                type="button"
                onClick={() => onAsk(preset.question, "rag")}
                disabled={sending}
                className="flex flex-col items-start rounded-[var(--r-md)] border border-line bg-[rgba(3,6,10,0.3)] p-3 text-left transition-colors hover:border-line-strong hover:bg-surface-2/70 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:pointer-events-none disabled:opacity-60"
              >
                <span className="mb-1.5 flex w-full items-center justify-between gap-2">
                  <span className="text-[0.6875rem] font-semibold text-ink-soft">{preset.label}</span>
                  <Badge tone={TONE[preset.tone] ?? "neutral"}>{preset.tag}</Badge>
                </span>
                <span className="line-clamp-2 text-[0.625rem] leading-relaxed text-faint">
                  {preset.description}
                </span>
              </button>
            ))}
          </div>
          <p className="mt-2 px-1 text-[0.625rem] leading-relaxed text-faint">
            Each scenario runs through the same server-enforced RBAC pipeline. Restricted content is
            never returned for a lower role, including during the injection scenario.
          </p>
        </CollapsibleContent>
      </Collapsible>

      <div className="mt-7 flex flex-wrap items-center justify-center gap-x-4 gap-y-1.5 border-t border-line pt-4 text-[0.625rem] text-faint">
        <span className="inline-flex items-center gap-1">
          <ShieldAlert className="size-3" aria-hidden="true" /> 0% cross-role leakage
        </span>
        <span className="inline-flex items-center gap-1">
          <FileCheck2 className="size-3" aria-hidden="true" /> Citation verification
        </span>
        <span className="inline-flex items-center gap-1">
          <Layers className="size-3" aria-hidden="true" /> Local-first · no data leaves the machine
        </span>
      </div>
    </div>
  );
}
