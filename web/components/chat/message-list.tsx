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
import { formatTime } from "@/lib/format";
import { turnFlags } from "@/lib/messages";
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
      <div className="group max-w-[min(88%,44rem)]">
        <div className="rounded-[var(--r-lg)] rounded-br-[var(--r-xs)] border border-[rgba(120,169,255,0.22)] bg-accent-soft px-3.5 py-2.5">
          <p className="whitespace-pre-wrap break-words text-[0.8125rem] leading-relaxed text-ink">
            {message.content}
          </p>
        </div>
        <div className="mt-1 flex items-center justify-end gap-1 text-[0.625rem] text-faint">
          <span>{formatTime(message.created_at)}</span>
          <span aria-hidden="true">·</span>
          <span>{message.user_role ?? "user"}</span>
          <span className="ml-1 flex items-center opacity-0 transition-opacity group-hover:opacity-100 focus-within:opacity-100">
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

  return (
    <div className="flex gap-2.5 sm:gap-3">
      <span
        className="mt-0.5 inline-flex size-7 shrink-0 items-center justify-center rounded-full border border-line bg-surface-2 text-accent"
        aria-hidden="true"
      >
        <ShieldCheck className="size-3.5" />
      </span>
      <div className="min-w-0 flex-1">
        <div className="mb-1.5 flex flex-wrap items-center gap-x-2 gap-y-1">
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
          <span className="font-mono text-[0.625rem] text-faint">{message.route_used ?? "unknown"}</span>
          <span className="text-[0.625rem] text-faint">{formatTime(message.created_at)}</span>
          <span className="ml-auto flex items-center gap-0.5 opacity-70 transition-opacity focus-within:opacity-100 hover:opacity-100">
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

        {flags.isRefusal ? (
          <RefusalCard
            answer={message.content}
            category={message.metadata?.refusal_category}
            role={message.user_role}
          />
        ) : (
          <div className="answer-prose">
            {streaming ? (
              <ProgressiveAnswer text={message.content} animate onDone={onStreamDone} />
            ) : (
              <Markdown>{message.content}</Markdown>
            )}
          </div>
        )}

        <div className="mt-3 space-y-2.5">
          {!flags.isRefusal ? <CitationsPanel citations={citations} role={message.user_role} /> : null}
          <FollowUps items={followUps} onSelect={onFollowUp} disabled={sending} />
          <AdvancedDetails message={message} />
        </div>
      </div>
    </div>
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
              <div className="max-w-lg rounded-full border border-line bg-surface-2/60 px-3 py-1 text-center text-[0.6875rem] text-faint">
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
