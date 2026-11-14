"use client";

import * as React from "react";
import { Check, Copy, Pencil, RefreshCw, ShieldCheck, Sparkles } from "lucide-react";

import { AdvancedDetails } from "@/components/chat/advanced-details";
import { CitationsPanel } from "@/components/chat/citations-panel";
import { FollowUps } from "@/components/chat/follow-ups";
import { Markdown } from "@/components/chat/markdown";
import { ProgressiveAnswer } from "@/components/chat/progressive-answer";
import { RefusalCard } from "@/components/chat/refusal-card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { LedgerSealIcon } from "@/components/ui/icons";
import { citationClause, citationHeading, citationPage } from "@/lib/citations";
import { formatTime } from "@/lib/format";
import { turnFlags } from "@/lib/messages";
import { prefersReducedMotion } from "@/lib/motion";
import type { Message } from "@/lib/types";
import { cn } from "@/lib/utils";

function CopyButton({ text, label = "Copy" }: { text: string; label?: string }) {
  const [copied, setCopied] = React.useState(false);
  const timer = React.useRef<number | null>(null);

  React.useEffect(
    () => () => {
      if (timer.current) window.clearTimeout(timer.current);
    },
    [],
  );

  async function copy() {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      if (timer.current) window.clearTimeout(timer.current);
      timer.current = window.setTimeout(() => setCopied(false), 1600);
    } catch {
      setCopied(false);
    }
  }

  return (
    <Button
      variant="ghost"
      size="icon-sm"
      onClick={() => void copy()}
      aria-label={copied ? "Copied" : label}
      title={copied ? "Copied" : label}
      className="text-faint hover:text-ink"
    >
      {copied ? <Check className="text-success" /> : <Copy />}
    </Button>
  );
}

function UserTurn({
  message,
  onEdit,
}: {
  message: Message;
  onEdit?: (content: string) => void;
}) {
  return (
    <div className="flex justify-end">
      <div className="group max-w-[min(92%,46rem)]">
        <div className="rounded-[var(--r-lg)] rounded-br-[var(--r-xs)] bg-surface-2 px-4 py-3 shadow-[var(--elev-1)]">
          <p className="whitespace-pre-wrap break-words text-sm leading-relaxed text-ink sm:text-base">
            {message.content}
          </p>
        </div>
        <div className="mt-1.5 flex items-center justify-end gap-1.5 text-xs text-faint">
          <span>{formatTime(message.created_at)}</span>
          <span aria-hidden="true">·</span>
          <span className="capitalize">{message.user_role ?? "user"}</span>
          <span className="ml-1.5 flex items-center opacity-75 transition-opacity group-hover:opacity-100 focus-within:opacity-100">
            {onEdit ? (
              <Button
                variant="ghost"
                size="icon-sm"
                onClick={() => onEdit(message.content)}
                aria-label="Edit this question"
                title="Edit and resend"
                className="text-faint hover:text-ink"
              >
                <Pencil />
              </Button>
            ) : null}
            <CopyButton text={message.content} label="Copy question" />
          </span>
        </div>
      </div>
    </div>
  );
}

interface ConnectorGeom {
  w: number;
  h: number;
  x1: number;
  y1: number;
  x2: number;
  y2: number;
  d: string;
}

function CitationConnectorOverlay({
  containerRef,
  activeCiteIndex,
}: {
  containerRef: React.RefObject<HTMLDivElement | null>;
  activeCiteIndex: number | null;
}) {
  const [geom, setGeom] = React.useState<ConnectorGeom | null>(null);

  React.useLayoutEffect(() => {
    if (activeCiteIndex === null) {
      setGeom(null);
      return;
    }

    const compute = () => {
      const container = containerRef.current;
      if (!container) {
        setGeom(null);
        return;
      }
      const n = activeCiteIndex + 1;
      const pins = Array.from(container.querySelectorAll<HTMLElement>(`[data-cite-pin="${n}"]`));
      const pin =
        pins.find((el) => el === document.activeElement || el.matches(":hover")) ??
        pins[0] ??
        null;
      const marginalia = container.querySelector<HTMLElement>(`[data-cite-marginalia="${n}"]`);
      const card = container.querySelector<HTMLElement>(`[data-cite-card="${n}"]`);
      const target =
        (marginalia && marginalia.getBoundingClientRect().height > 0 ? marginalia : null) ??
        (card && card.getBoundingClientRect().height > 0 ? card : null);

      if (!pin || !target) {
        setGeom(null);
        return;
      }

      const cRect = container.getBoundingClientRect();
      const pRect = pin.getBoundingClientRect();
      const tRect = target.getBoundingClientRect();
      if (cRect.width <= 0 || cRect.height <= 0 || pRect.width <= 0 || tRect.height <= 0) {
        setGeom(null);
        return;
      }

      const isSideMarginalia = target === marginalia;
      const x1 = isSideMarginalia
        ? pRect.right - cRect.left + 4
        : pRect.left + pRect.width / 2 - cRect.left;
      const y1 = isSideMarginalia
        ? pRect.top + pRect.height / 2 - cRect.top
        : pRect.bottom - cRect.top + 3;
      const x2 = isSideMarginalia ? tRect.left - cRect.left - 4 : tRect.left + 16 - cRect.left;
      const y2 = isSideMarginalia
        ? tRect.top + Math.min(26, tRect.height / 2) - cRect.top
        : tRect.top - cRect.top - 3;

      const d = isSideMarginalia
        ? (() => {
            const dx = Math.max(36, Math.abs(x2 - x1) * 0.45);
            return `M ${x1.toFixed(1)} ${y1.toFixed(1)} C ${(x1 + dx).toFixed(1)} ${y1.toFixed(1)}, ${(x2 - dx).toFixed(1)} ${y2.toFixed(1)}, ${x2.toFixed(1)} ${y2.toFixed(1)}`;
          })()
        : (() => {
            const midY = (y1 + y2) / 2;
            return `M ${x1.toFixed(1)} ${y1.toFixed(1)} C ${x1.toFixed(1)} ${midY.toFixed(1)}, ${x2.toFixed(1)} ${midY.toFixed(1)}, ${x2.toFixed(1)} ${y2.toFixed(1)}`;
          })();

      setGeom({
        w: Math.max(1, Math.round(cRect.width)),
        h: Math.max(1, Math.round(cRect.height)),
        x1,
        y1,
        x2,
        y2,
        d,
      });
    };

    compute();
    window.addEventListener("resize", compute);
    window.addEventListener("scroll", compute, true);
    return () => {
      window.removeEventListener("resize", compute);
      window.removeEventListener("scroll", compute, true);
    };
  }, [activeCiteIndex, containerRef]);

  if (!geom || activeCiteIndex === null) return null;

  return (
    <svg
      aria-hidden="true"
      data-testid="citation-connector"
      width={geom.w}
      height={geom.h}
      viewBox={`0 0 ${geom.w} ${geom.h}`}
      className="pointer-events-none absolute inset-0 z-10 hidden overflow-visible xl:block"
    >
      <path
        d={geom.d}
        fill="none"
        stroke="var(--accent)"
        strokeWidth="1.75"
        strokeDasharray="4 4"
        strokeLinecap="round"
        className="pipeline-dash-active"
        opacity="0.88"
      />
      <circle cx={geom.x1} cy={geom.y1} r="3" fill="var(--accent)" />
      <circle
        cx={geom.x2}
        cy={geom.y2}
        r="3.5"
        fill="var(--surface)"
        stroke="var(--accent)"
        strokeWidth="1.75"
      />
    </svg>
  );
}

function AssistantTurn({
  message,
  streaming,
  canRegenerate,
  onRegenerate,
  onFollowUp,
  sending,
  onStreamDone,
}: {
  message: Message;
  streaming: boolean;
  canRegenerate: boolean;
  onRegenerate: () => void;
  onFollowUp: (query: string) => void;
  sending: boolean;
  onStreamDone: () => void;
}) {
  const flags = turnFlags(message);
  const citations = message.metadata?.citations ?? [];
  const followUps = message.metadata?.suggested_follow_ups ?? [];
  const [citationsOpen, setCitationsOpen] = React.useState(false);
  const [activeCiteIndex, setActiveCiteIndex] = React.useState<number | null>(null);
  const [pulsedCiteIndex, setPulsedCiteIndex] = React.useState<number | null>(null);
  const pulseTimer = React.useRef<number | null>(null);
  const connectorHostRef = React.useRef<HTMLDivElement>(null);

  React.useEffect(
    () => () => {
      if (pulseTimer.current) window.clearTimeout(pulseTimer.current);
    },
    [],
  );

  const handleJumpCite = React.useCallback(
    (index: number) => {
      setCitationsOpen(true);
      setActiveCiteIndex(index);
      setPulsedCiteIndex(index);
      if (pulseTimer.current) window.clearTimeout(pulseTimer.current);
      pulseTimer.current = window.setTimeout(() => setPulsedCiteIndex(null), 1300);

      window.requestAnimationFrame(() => {
        window.setTimeout(() => {
          const el = document.getElementById(`cite-${message.id}-${index}`);
          if (el && typeof el.scrollIntoView === "function") {
            el.scrollIntoView({
              behavior: prefersReducedMotion() ? "auto" : "smooth",
              block: "nearest",
            });
          }
        }, 70);
      });
    },
    [message.id],
  );

  const showMarginalia = !flags.isRefusal && citations.length > 0;

  return (
    <article className="flex gap-3 sm:gap-4">
      <span
        className="mt-0.5 inline-flex size-8 shrink-0 items-center justify-center rounded-full bg-surface text-accent-link shadow-[var(--elev-1)]"
        aria-hidden="true"
      >
        <LedgerSealIcon className="size-4" />
      </span>
      <div className="min-w-0 flex-1 border-b border-line/65 pb-6">
        <div className="mb-3 flex flex-wrap items-center gap-x-3 gap-y-2 border-b border-line/50 pb-2.5">
          {flags.isRefusal ? (
            <Badge tone="warning">Refusal</Badge>
          ) : flags.grounded ? (
            <Badge tone="success">
              <ShieldCheck /> Grounded in permitted documents
            </Badge>
          ) : (
            <Badge tone="nonGrounded">
              <Sparkles /> Open knowledge · not grounded
            </Badge>
          )}
          <span className="font-mono text-xs text-faint">Route: {message.route_used ?? "unknown"}</span>
          <span className="text-xs text-faint">{formatTime(message.created_at)}</span>
          <span className="ml-auto flex items-center gap-1 opacity-80 transition-opacity focus-within:opacity-100 hover:opacity-100">
            <CopyButton text={message.content} label="Copy answer" />
            {canRegenerate ? (
              <Button
                variant="ghost"
                size="icon-sm"
                onClick={onRegenerate}
                disabled={sending}
                aria-label="Regenerate answer"
                title="Regenerate"
                className="text-faint hover:text-ink"
              >
                <RefreshCw />
              </Button>
            ) : null}
          </span>
        </div>

        <div
          ref={connectorHostRef}
          className={cn(
            "relative",
            showMarginalia &&
              "grid grid-cols-1 gap-6 xl:grid-cols-[minmax(0,68ch)_230px] xl:items-start",
          )}
        >
          <CitationConnectorOverlay
            containerRef={connectorHostRef}
            activeCiteIndex={activeCiteIndex}
          />
          <div className="min-w-0 max-w-[70ch]">
            {flags.isRefusal ? (
              <RefusalCard
                answer={message.content}
                category={message.metadata?.refusal_category}
                role={message.user_role}
              />
            ) : (
              <div className="answer-prose">
                {streaming ? (
                  <ProgressiveAnswer
                    text={message.content}
                    animate
                    onDone={onStreamDone}
                    citationCount={citations.length}
                    activeCiteIndex={activeCiteIndex}
                    onHoverCite={setActiveCiteIndex}
                    onJumpCite={handleJumpCite}
                  />
                ) : (
                  <Markdown
                    citationCount={citations.length}
                    activeCiteIndex={activeCiteIndex}
                    onHoverCite={setActiveCiteIndex}
                    onJumpCite={handleJumpCite}
                  >
                    {message.content}
                  </Markdown>
                )}
              </div>
            )}

            <div className="mt-4 space-y-3">
              {!flags.isRefusal ? (
                <CitationsPanel
                  citations={citations}
                  role={message.user_role}
                  turnId={message.id}
                  open={citationsOpen}
                  onOpenChange={setCitationsOpen}
                  activeIndex={activeCiteIndex}
                  pulsedIndex={pulsedCiteIndex}
                  onHoverIndex={setActiveCiteIndex}
                />
              ) : null}
              <FollowUps items={followUps} onSelect={onFollowUp} disabled={sending} />
              <AdvancedDetails message={message} />
            </div>
          </div>

          {showMarginalia ? (
            <aside
              aria-label="Clause marginalia notes"
              className="hidden space-y-3 rounded-[var(--r-xl)] bg-surface p-4 shadow-[var(--elev-2)] xl:sticky xl:top-6 xl:block"
            >
              <p className="font-mono text-xs font-semibold uppercase tracking-[0.1em] text-faint">
                Clause index
              </p>
              <ul className="space-y-2.5">
                {citations.map((citation, idx) => {
                  const clause = citationClause(citation) || citationHeading(citation) || "Cited passage";
                  const page = citationPage(citation);
                  const snippet = (citation.snippet?.trim() || citation.quote_snippet?.trim() || "").slice(0, 96);
                  const isActive = activeCiteIndex === idx;
                  return (
                    <li key={`${citation.chunk_id ?? citation.doc_id}-margin-${idx}`}>
                      <button
                        type="button"
                        data-cite-marginalia={idx + 1}
                        onMouseEnter={() => setActiveCiteIndex(idx)}
                        onMouseLeave={() => setActiveCiteIndex(null)}
                        onFocus={() => setActiveCiteIndex(idx)}
                        onBlur={() => setActiveCiteIndex(null)}
                        onClick={() => handleJumpCite(idx)}
                        className={cn(
                          "w-full rounded-[var(--r-lg)] px-3.5 py-3 text-left transition-[background-color,box-shadow] duration-[var(--duration-fast)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent",
                          isActive
                            ? "bg-accent-soft shadow-[var(--elev-1)] ring-1 ring-inset ring-line-accent"
                            : "bg-inset shadow-[var(--inner-inset)] hover:bg-surface-2",
                        )}
                      >
                        <div className="flex items-center justify-between gap-2 font-mono">
                          <span className={cn("text-sm font-semibold tracking-tight", isActive ? "text-accent-link" : "text-ink")}>
                            [{idx + 1}] {clause}
                          </span>
                          {page ? <span className="tabular shrink-0 text-xs text-faint">p.{page}</span> : null}
                        </div>
                        {snippet ? (
                          <p className="mt-1.5 line-clamp-2 text-xs leading-relaxed text-muted">
                            {snippet}
                          </p>
                        ) : null}
                      </button>
                    </li>
                  );
                })}
              </ul>
            </aside>
          ) : null}
        </div>
      </div>
    </article>
  );
}

export function MessageList({
  messages,
  streamingId,
  onRegenerate,
  onEdit,
  onFollowUp,
  onStreamDone,
  sending,
}: {
  messages: Message[];
  streamingId: number | null;
  onRegenerate: () => void;
  onEdit: (content: string) => void;
  onFollowUp: (query: string) => void;
  onStreamDone: () => void;
  sending: boolean;
}) {
  const lastAssistantIndex = React.useMemo(() => {
    for (let index = messages.length - 1; index >= 0; index -= 1) {
      if (messages[index].sender === "assistant") return index;
    }
    return -1;
  }, [messages]);

  return (
    <div role="log" aria-label="Conversation" className="space-y-5">
      {messages.map((message, index) => {
        if (message.sender === "user") {
          return <UserTurn key={message.id} message={message} onEdit={onEdit} />;
        }
        if (message.sender === "system") {
          return (
            <div key={message.id} className="flex justify-center">
              <div className="max-w-lg rounded-full bg-surface px-4 py-1.5 text-center text-xs text-faint shadow-[var(--elev-1)]">
                {message.content}
              </div>
            </div>
          );
        }
        return (
          <div
            key={message.id}
            className={cn(message.id > 0 && "animate-enter")}
          >
            <AssistantTurn
              message={message}
              streaming={streamingId === message.id}
              canRegenerate={index === lastAssistantIndex}
              onRegenerate={onRegenerate}
              onFollowUp={onFollowUp}
              sending={sending}
              onStreamDone={onStreamDone}
            />
          </div>
        );
      })}
    </div>
  );
}
