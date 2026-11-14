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
import { useThrottledCallback } from "@/lib/hooks/use-throttle";
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

  const throttledOnSend = useThrottledCallback(onSend, 1000);

  React.useEffect(() => {
    const element = textareaRef.current;
    if (!element) return;
    element.style.height = "auto";
    element.style.height = `${Math.min(168, element.scrollHeight)}px`;
  }, [draft, textareaRef]);

  function submit() {
    if (!canSend) return;
    throttledOnSend();
  }

  return (
    <div className="composer-fade sticky bottom-0 z-10 border-t border-line/70 px-3 pb-3 pt-2.5 sm:px-5 sm:pb-4 sm:pt-3.5 lg:px-8">
      <div className="mx-auto w-full max-w-[var(--reading-width)]">
        <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
          <div className="flex flex-wrap items-center gap-2.5">
            <SegmentedControl
              ariaLabel="Retrieval scope"
              options={MODE_OPTIONS}
              value={intentMode}
              onValueChange={onIntentModeChange}
              size="sm"
            />
            <span className="hidden items-center gap-1.5 text-xs text-faint sm:inline-flex">
              {intentMode === "rag" ? (
                <LockKeyhole className="size-3.5" aria-hidden="true" />
              ) : null}
              {modeMeta.description}
            </span>
          </div>
          <div className="flex items-center gap-2">
            <span className="hidden text-xs text-faint sm:inline">Style</span>
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
            "rounded-[var(--r-lg)] bg-surface p-2.5 shadow-[var(--elev-2)] transition-[box-shadow,background-color] duration-[var(--duration-base)] ease-[var(--ease-out)]",
            focused
              ? "ring-2 ring-accent/70 shadow-[var(--elev-3)]"
              : "ring-1 ring-inset ring-line hover:ring-line-strong",
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
            className="max-h-[192px] min-h-[48px] rounded-[var(--r-md)] border-0 bg-transparent px-3 py-2.5 text-base leading-relaxed shadow-none placeholder:text-faint hover:bg-transparent focus:shadow-none focus-visible:outline-none sm:min-h-[56px] sm:py-3"
          />
          <div className="flex items-center justify-between gap-2 px-1.5 pb-1 pt-1.5">
            <div className="flex min-w-0 items-center gap-2 text-xs text-faint">
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
            <div className="flex items-center gap-2">
              <Tooltip>
                <TooltipTrigger asChild>
                  <span className="hidden h-7 items-center gap-1.5 rounded-full bg-inset px-3 text-xs font-medium text-faint shadow-[var(--inner-inset)] sm:inline-flex">
                    <Sparkles className="size-3.5" aria-hidden="true" />
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

        <p className="mt-2 hidden items-center justify-center gap-1.5 text-center text-xs leading-relaxed text-faint sm:flex">
          <LockKeyhole className="size-3 shrink-0" aria-hidden="true" />
          Role filtering runs server-side. Restricted passages never enter the model context.
          {offline ? (
            <span className="ml-1 inline-flex items-center gap-1 font-medium text-warning">
              <Check className="size-3" aria-hidden="true" /> Offline — reconnect to send.
            </span>
          ) : null}
        </p>
      </div>
    </div>
  );
}
