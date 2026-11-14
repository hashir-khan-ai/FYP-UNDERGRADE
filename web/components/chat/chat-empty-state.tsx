"use client";

import { PipelineHeroSvg } from "@/components/visual/trust-map";

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
import { staggerDelayStyle } from "@/lib/motion";
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
    <div className="mx-auto w-full max-w-[var(--reading-width)] px-3 py-4 sm:px-4 sm:py-4">
      <div className="text-center">
        <Badge tone="accent" className="mb-2 sm:mb-2.5">
          <Sparkles /> {roleLabel(role)} workspace
        </Badge>
        <h2 className="font-display text-[clamp(1.375rem,2.5vw,1.875rem)] font-semibold tracking-[-0.02em] text-ink">
          Good to see you, {firstName}.
        </h2>
        <p className="mx-auto mt-1.5 max-w-xl text-sm leading-relaxed text-muted">
          Ask a compliance question and the assistant will retrieve only the documents your role
          may read, verify every citation, and refuse when the corpus does not support an answer.
        </p>
        <p className="mt-1 text-xs text-faint">{roleScope(role)}</p>
        <div className="mx-auto mt-3 hidden max-w-lg rounded-[var(--r-xl)] bg-canvas-raised/90 px-4 py-2 shadow-[var(--elev-1)] sm:block">
          <PipelineHeroSvg className="mx-auto max-h-[126px] w-full" />
        </div>
      </div>

      <div className="mt-4 grid gap-3 sm:mt-4 sm:grid-cols-3 sm:gap-4">
        {starters.map((starter, index) => {
          const Icon = STARTER_ICONS[starter.icon];
          return (
            <button
              key={starter.title}
              type="button"
              onClick={() => onAsk(starter.query, "auto")}
              disabled={sending}
              style={staggerDelayStyle(index, 50, 150)}
              className="starter-calm-card animate-enter group flex min-h-[82px] flex-col items-start rounded-[var(--r-lg)] bg-surface p-4 text-left shadow-[var(--elev-1)] hover:bg-surface-2/65 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:pointer-events-none disabled:opacity-60 sm:min-h-[148px] sm:p-5"
            >
              <div className="mb-1.5 flex items-center gap-2.5 sm:mb-3 sm:block">
                <span className="inline-flex size-9 items-center justify-center rounded-[var(--r-md)] bg-surface-2 text-accent-link shadow-[var(--inner-highlight)] sm:mb-3">
                  <Icon className="size-4" aria-hidden="true" />
                </span>
                <span className="text-sm font-semibold text-ink sm:block">{starter.title}</span>
              </div>
              <span className="line-clamp-2 text-xs leading-relaxed text-muted sm:mt-1.5 sm:line-clamp-3">
                {starter.query}
              </span>
              <span className="mt-2 inline-flex items-center gap-1.5 text-xs font-medium text-faint group-hover:text-accent-link sm:mt-auto sm:pt-3">
                Ask this <ChevronRight className="size-3.5" aria-hidden="true" />
              </span>
            </button>
          );
        })}
      </div>

      <Collapsible className="mt-5 sm:mt-6">
        <CollapsibleTrigger className="group mx-auto flex min-h-[40px] items-center gap-2 rounded-full bg-surface px-4 py-2 text-xs font-medium text-muted shadow-[var(--elev-1)] transition-colors hover:bg-surface-2 hover:text-ink focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent">
          <ChevronRight
            className="size-4 transition-transform duration-[var(--duration-fast)] group-data-[state=open]:rotate-90"
            aria-hidden="true"
          />
          Demo scenarios for your viva
        </CollapsibleTrigger>
        <CollapsibleContent className="mt-3.5 data-[state=open]:animate-enter">
          <div className="grid gap-3 sm:grid-cols-2">
            {DEMO_PRESETS.map((preset) => (
              <button
                key={preset.id}
                type="button"
                onClick={() => onAsk(preset.question, "rag")}
                disabled={sending}
                className="flex min-h-[56px] flex-col items-start rounded-[var(--r-lg)] bg-surface p-4 text-left shadow-[var(--elev-1)] transition-[background-color,box-shadow] duration-[var(--duration-fast)] hover:bg-surface-2/75 hover:shadow-[var(--elev-2)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:pointer-events-none disabled:opacity-60"
              >
                <span className="mb-1.5 flex w-full items-center justify-between gap-2">
                  <span className="text-xs font-semibold text-ink-soft">{preset.label}</span>
                  <Badge tone={TONE[preset.tone] ?? "neutral"}>{preset.tag}</Badge>
                </span>
                <span className="line-clamp-2 text-xs leading-relaxed text-faint">
                  {preset.description}
                </span>
              </button>
            ))}
          </div>
          <p className="mt-2.5 px-1 text-xs leading-relaxed text-faint">
            Each scenario runs through the same server-enforced RBAC pipeline. Restricted content is
            never returned for a lower role, including during the injection scenario.
          </p>
        </CollapsibleContent>
      </Collapsible>

      <div className="mt-6 flex flex-wrap items-center justify-center gap-x-5 gap-y-2 border-t border-line pt-4 text-xs text-faint sm:mt-8">
        <span className="inline-flex items-center gap-1.5">
          <ShieldAlert className="size-3.5" aria-hidden="true" /> 0% cross-role leakage
        </span>
        <span className="inline-flex items-center gap-1.5">
          <FileCheck2 className="size-3.5" aria-hidden="true" /> Citation verification
        </span>
        <span className="inline-flex items-center gap-1.5">
          <Layers className="size-3.5" aria-hidden="true" /> Local-first · no data leaves the machine
        </span>
      </div>
    </div>
  );
}
