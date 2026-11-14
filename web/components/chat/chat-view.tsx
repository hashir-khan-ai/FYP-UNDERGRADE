"use client";

import * as React from "react";
import Link from "next/link";
import { AlertTriangle, ArrowUpRight, RefreshCw, X } from "lucide-react";

import { ChatEmptyState } from "@/components/chat/chat-empty-state";
import { Composer } from "@/components/chat/composer";
import { MessageList } from "@/components/chat/message-list";
import { ThinkingPanel } from "@/components/chat/thinking-panel";
import { useSessions } from "@/components/providers/sessions-provider";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useThrottledCallback } from "@/lib/hooks/use-throttle";
import { ApiError, api } from "@/lib/api-client";
import { roleLabel, roleScope } from "@/lib/auth";
import { lastUserPrompt, messageFromChatResponse, optimisticUserMessage } from "@/lib/messages";
import type { IntentMode, Message, ResponseMode, UserProfile } from "@/lib/types";
import { cn } from "@/lib/utils";

interface ChatError {
  message: string;
  code: string;
  retryText: string;
}

const MIN_THINKING_MS = 620;

export function ChatView({
  sessionId,
  user,
  initialMessages,
  profile,
}: {
  sessionId: string;
  user: UserProfile;
  initialMessages: Message[];
  profile: string;
}) {
  const { sessions, refreshSessions } = useSessions();
  const session = sessions.find((item) => item.id === sessionId);
  const title = session?.title ?? "Compliance session";

  const [messages, setMessages] = React.useState<Message[]>(initialMessages);
  const [draft, setDraft] = React.useState("");
  const [intentMode, setIntentMode] = React.useState<IntentMode>("auto");
  const [responseMode, setResponseMode] = React.useState<ResponseMode>("compliance");
  const [sending, setSending] = React.useState(false);
  const [stage, setStage] = React.useState(0);
  const [error, setError] = React.useState<ChatError | null>(null);
  const [streamingId, setStreamingId] = React.useState<number | null>(null);
  const [offline, setOffline] = React.useState(false);

  const scrollRef = React.useRef<HTMLDivElement>(null);
  const bottomRef = React.useRef<HTMLDivElement>(null);
  const textareaRef = React.useRef<HTMLTextAreaElement>(null);
  const stageTimer = React.useRef<number | null>(null);
  const sendingRef = React.useRef(false);

  React.useEffect(() => {
    setMessages(initialMessages);
  }, [initialMessages]);

  React.useEffect(
    () => () => {
      if (stageTimer.current) window.clearInterval(stageTimer.current);
    },
    [],
  );

  const rawScrollToBottom = React.useCallback((behavior: ScrollBehavior = "smooth") => {
    bottomRef.current?.scrollIntoView({ behavior, block: "end" });
  }, []);

  const scrollToBottom = useThrottledCallback(rawScrollToBottom, 150);

  React.useEffect(() => {
    scrollToBottom(messages.length > 0 ? "smooth" : "auto");
  }, [messages.length, sending, error, scrollToBottom]);

  function startStages() {
    if (stageTimer.current) window.clearInterval(stageTimer.current);
    setStage(0);
    stageTimer.current = window.setInterval(() => {
      setStage((current) =>
        current < 4 ? Math.min(4, current + 1) : current,
      );
    }, 1150);
  }

  function stopStages() {
    if (stageTimer.current) {
      window.clearInterval(stageTimer.current);
      stageTimer.current = null;
    }
  }

  async function runQuery(text: string, intentOverride?: IntentMode) {
    const query = text.trim();
    if (query.length < 2 || sendingRef.current) return;

    const effectiveIntent = intentOverride ?? intentMode;
    if (intentOverride && intentOverride !== intentMode) setIntentMode(intentOverride);

    sendingRef.current = true;
    setSending(true);
    setError(null);
    setDraft("");
    setOffline(false);
    setStreamingId(null);
    startStages();

    const optimistic = optimisticUserMessage(query);
    setMessages((current) => [...current, optimistic]);
    const startedAt = performance.now();

    try {
      const response = await api.chatQuery(sessionId, query, responseMode, effectiveIntent);
      const elapsed = performance.now() - startedAt;
      if (elapsed < MIN_THINKING_MS) {
        await new Promise((resolve) => setTimeout(resolve, MIN_THINKING_MS - elapsed));
      }
      stopStages();
      setStage(4);
      const assistant = messageFromChatResponse(response, responseMode, effectiveIntent);
      setMessages((current) => [...current, assistant]);
      setStreamingId(assistant.id);
      void refreshSessions();

      // Reconcile with canonical persisted messages once the reveal is underway.
      window.setTimeout(() => {
        void api
          .getMessages(sessionId)
          .then((fresh) => {
            if (fresh.length > 0) {
              setMessages(fresh);
              setStreamingId(null);
            }
          })
          .catch(() => {
            // Keep the locally rendered turn if the reload fails.
          });
      }, 1400);
    } catch (caught) {
      stopStages();
      setMessages((current) => current.filter((message) => message.id !== optimistic.id));
      setDraft(query);
      if (caught instanceof ApiError) {
        setError({ message: caught.message, code: caught.code, retryText: query });
        if (caught.code === "BACKEND_UNREACHABLE" || caught.status === 503) setOffline(true);
      } else {
        setError({
          message: "The answer could not be completed. Try again.",
          code: "UNKNOWN_ERROR",
          retryText: query,
        });
      }
    } finally {
      sendingRef.current = false;
      setSending(false);
    }
  }

  function regenerate() {
    const prompt = lastUserPrompt(messages);
    if (prompt) void runQuery(prompt);
  }

  function editQuestion(content: string) {
    setDraft(content);
    window.requestAnimationFrame(() => {
      textareaRef.current?.focus();
      const length = content.length;
      textareaRef.current?.setSelectionRange(length, length);
    });
  }

  const role = String(user.role ?? "").toLowerCase();

  return (
    <div className="flex h-[calc(100dvh-3.5rem)] flex-col lg:h-dvh">
      <header className="flex h-14 shrink-0 items-center gap-3 border-b border-line px-3 sm:px-5 lg:px-8">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <h1 className="truncate text-sm sm:text-base font-semibold tracking-[-0.01em] text-ink">
              {title}
            </h1>
            <Badge tone="success" className="hidden sm:inline-flex">
              RBAC enforced
            </Badge>
          </div>
          <p className="truncate text-xs text-faint">
            {roleLabel(role)} · {roleScope(role)} · profile {profile}
          </p>
        </div>
        <div className="hidden items-center gap-2 md:flex">
          <Badge tone="neutral">Sources collapsed by default</Badge>
          <Link
            href="/documents"
            className="inline-flex min-h-[44px] items-center gap-1 rounded-[var(--r-xs)] px-2 py-1 text-xs text-muted transition-colors hover:text-ink"
          >
            Catalog <ArrowUpRight className="size-3.5" aria-hidden="true" />
          </Link>
        </div>
      </header>

      <div ref={scrollRef} className="min-h-0 flex-1 overflow-y-auto">
        <div
          className={cn(
            "mx-auto w-full px-3 py-4 sm:px-6",
            messages.length === 0 ? "max-w-3xl" : "max-w-[var(--reading-width)]",
          )}
        >
          {messages.length === 0 ? (
            <ChatEmptyState
              role={role}
              name={user.full_name}
              onAsk={(query, intent) => void runQuery(query, intent)}
              sending={sending}
            />
          ) : (
            <MessageList
              messages={messages}
              streamingId={streamingId}
              onRegenerate={regenerate}
              onEdit={editQuestion}
              onFollowUp={(query) => void runQuery(query)}
              onStreamDone={() => setStreamingId(null)}
              sending={sending}
            />
          )}

          {sending ? (
            <div className="mt-5">
              <ThinkingPanel stage={stage} />
            </div>
          ) : null}

          {error ? (
            <div
              role="alert"
              className="mt-4 rounded-[var(--r-md)] border border-[rgba(255,133,133,0.28)] bg-danger-soft p-3.5"
            >
              <div className="flex items-start gap-2.5">
                <AlertTriangle className="mt-0.5 size-4 shrink-0 text-danger" aria-hidden="true" />
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-semibold text-ink">The answer could not be completed</p>
                  <p className="mt-1 text-xs leading-relaxed text-muted">{error.message}</p>
                  <p className="mt-1 font-mono text-xs text-faint">{error.code}</p>
                  <div className="mt-2.5 flex flex-wrap gap-2">
                    <Button
                      size="sm"
                      variant="secondary"
                      onClick={() => {
                        setError(null);
                        void runQuery(error.retryText);
                      }}
                    >
                      <RefreshCw /> Try again
                    </Button>
                    {error.code === "UNAUTHENTICATED" ? (
                      <Button size="sm" variant="primary" asChild>
                        <Link href="/login">Sign in again</Link>
                      </Button>
                    ) : null}
                    <Button size="sm" variant="ghost" onClick={() => setError(null)}>
                      <X /> Dismiss
                    </Button>
                  </div>
                </div>
              </div>
            </div>
          ) : null}

          <div ref={bottomRef} className="h-1" />
        </div>
      </div>

      <Composer
        draft={draft}
        onDraftChange={setDraft}
        onSend={() => void runQuery(draft)}
        sending={sending}
        intentMode={intentMode}
        onIntentModeChange={setIntentMode}
        responseMode={responseMode}
        onResponseModeChange={setResponseMode}
        textareaRef={textareaRef}
        offline={offline}
      />
    </div>
  );
}
