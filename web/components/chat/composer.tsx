"use client";

import * as React from "react";
import {
  ArrowUp,
  Check,
  LockKeyhole,
  Pencil,
  RefreshCw,
  Sparkles,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { SegmentedControl } from "@/components/ui/segmented-control";
import { Textarea } from "@/components/ui/input";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { INTENT_MODES, RESPONSE_MODES, intentModeMeta, responseModeMeta } from "@/lib/modes";
import type { IntentMode, ResponseMode } from "@/lib/types";
import { cn } from "@/lib/utils";

const MODE_OPTIONS = INTENT_MODES.map((mode) => ({
  value: mode.value,
  label: mode.shortLabel,
  hint: `${mode.description} ${mode.hint}`,
}));

const STYLE_OPTIONS = RESPONSE_MODES.map((mode) => ({
  value: mode.value,
  label: mode.label,
  hint: mode.description,
}));

export function Composer({
  draft,
  onDraftChange,
  onSend,
  sending,
  intentMode,
  onIntentModeChange,
  responseMode,
  onResponseModeChange,
  textareaRef,
  offline,
}: {
  draft: string;
  onDraftChange: (value: string) => void;
  onSend: () => void;
  sending: boolean;
  intentMode: IntentMode;
  onIntentModeChange: (mode: IntentMode) => void;
  responseMode: ResponseMode;
  onResponseModeChange: (mode: ResponseMode) => void;
  textareaRef: React.RefObject<HTMLTextAreaElement | null>;
  offline?: boolean;
}) {
  const [focused, setFocused] = React.useState(false);
  const maxLength = 2000;
  const canSend = draft.trim().length >= 2 && !sending && !offline;
  const modeMeta = intentModeMeta(intentMode);
  const styleMeta = responseModeMeta(responseMode);

  React.useEffect(() => {
    const element = textareaRef.current;
    if (!element) return;
    element.style.height = "auto";
    element.style.height = `${Math.min(168, element.scrollHeight)}px`;
  }, [draft, textareaRef]);

  function submit() {
    if (!canSend) return;
    onSend();
  }

  return (
    <div className="glass-bar border-t px-3 pb-3 pt-2.5 sm:px-5 lg:px-8">
      <div className="mx-auto w-full max-w-[var(--reading-width)]">
        <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
          <div className="flex flex-wrap items-center gap-2">
            <SegmentedControl
              ariaLabel="Retrieval scope"
              options={MODE_OPTIONS}
              value={intentMode}
              onValueChange={onIntentModeChange}
              size="sm"
            />
            <span className="hidden items-center gap-1 text-[0.625rem] text-faint sm:inline-flex">
              {intentMode === "rag" ? (
                <LockKeyhole className="size-2.5" aria-hidden="true" />
              ) : null}
              {modeMeta.description}
            </span>
          </div>
          <div className="flex items-center gap-2">
            <span className="hidden text-[0.625rem] text-faint sm:inline">Style</span>
            <SegmentedControl
              ariaLabel="Response style"
              options={STYLE_OPTIONS}
              value={responseMode}
              onValueChange={onResponseModeChange}
              size="sm"
            />
          </div>
        </div>

        <form
          onSubmit={(event) => {
            event.preventDefault();
            submit();
          }}
          className={cn(
            "rounded-[var(--r-lg)] border bg-[rgba(3,6,10,0.5)] p-1.5 transition-[border-color,box-shadow] duration-[var(--duration-fast)]",
            focused
              ? "border-line-accent shadow-[0_0_0_3px_rgba(120,169,255,0.1)]"
              : "border-line hover:border-line-strong",
          )}
        >
          <Textarea
            ref={textareaRef}
            value={draft}
            onChange={(event) => onDraftChange(event.target.value.slice(0, maxLength))}
            onFocus={() => setFocused(true)}
            onBlur={() => setFocused(false)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
                event.preventDefault();
                submit();
              }
            }}
            rows={1}
            maxLength={maxLength}
            placeholder="Ask a compliance question…"
            aria-label="Compliance question"
            disabled={offline}
            className="max-h-[168px] min-h-[44px] border-0 bg-transparent px-2.5 py-2.5 shadow-none focus:shadow-none"
          />
          <div className="flex items-center justify-between gap-2 px-1 pb-0.5 pt-1">
            <div className="flex min-w-0 items-center gap-2 text-[0.625rem] text-faint">
              <span className="hidden sm:inline">
                <kbd className="kbd">Enter</kbd> send · <kbd className="kbd">Shift</kbd>+
                <kbd className="kbd">Enter</kbd> newline
              </span>
              <span className="sm:hidden">{styleMeta.label} · {modeMeta.shortLabel}</span>
              {draft.length > maxLength - 300 ? (
                <span className="tabular text-warning">
                  {draft.length}/{maxLength}
                </span>
              ) : null}
            </div>
            <div className="flex items-center gap-1.5">
              <Tooltip>
                <TooltipTrigger asChild>
                  <span className="hidden items-center gap-1 rounded-full border border-line px-2 py-0.5 text-[0.625rem] text-faint sm:inline-flex">
                    <Sparkles className="size-2.5" aria-hidden="true" />
                    {modeMeta.shortLabel}
                  </span>
                </TooltipTrigger>
                <TooltipContent side="top">{modeMeta.hint}</TooltipContent>
              </Tooltip>
              <Button
                type="submit"
                size="icon"
                variant="primary"
                disabled={!canSend}
                aria-label={sending ? "Waiting for an answer" : "Send question"}
                className="rounded-full"
              >
                {sending ? (
                  <RefreshCw className="animate-spin" aria-hidden="true" />
                ) : (
                  <ArrowUp aria-hidden="true" />
                )}
              </Button>
            </div>
          </div>
        </form>

        <p className="mt-1.5 flex items-center justify-center gap-1 text-center text-[0.625rem] leading-relaxed text-faint">
          <LockKeyhole className="size-2.5 shrink-0" aria-hidden="true" />
          Role filtering runs server-side. Restricted passages never enter the model context.
          {offline ? (
            <span className="ml-1 inline-flex items-center gap-1 font-medium text-warning">
              <Check className="size-2.5" aria-hidden="true" /> Offline — reconnect to send.
            </span>
          ) : null}
        </p>
      </div>
    </div>
  );
}
