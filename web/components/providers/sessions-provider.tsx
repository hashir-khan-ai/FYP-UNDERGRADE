"use client";

import * as React from "react";
import { usePathname, useRouter } from "next/navigation";
import { toast } from "sonner";

import { ApiError, api } from "@/lib/api-client";
import type { SessionSummary } from "@/lib/types";

interface SessionsContextValue {
  sessions: SessionSummary[];
  activeSessionId: string | null;
  creating: boolean;
  createSession: (title?: string) => Promise<SessionSummary | null>;
  renameSession: (sessionId: string, title: string) => Promise<boolean>;
  deleteSession: (sessionId: string) => Promise<boolean>;
  refreshSessions: () => Promise<void>;
}

const SessionsContext = React.createContext<SessionsContextValue | null>(null);

function sortSessions(sessions: SessionSummary[]): SessionSummary[] {
  return [...sessions].sort((a, b) => {
    const left = a.updated_at ?? a.created_at ?? "";
    const right = b.updated_at ?? b.created_at ?? "";
    return right.localeCompare(left);
  });
}

function messageFor(error: unknown, fallback: string): string {
  if (error instanceof ApiError) return error.message;
  return fallback;
}

export function SessionsProvider({
  initialSessions,
  children,
}: {
  initialSessions: SessionSummary[];
  children: React.ReactNode;
}) {
  const router = useRouter();
  const pathname = usePathname();
  const [sessions, setSessions] = React.useState<SessionSummary[]>(() =>
    sortSessions(initialSessions),
  );
  const [creating, setCreating] = React.useState(false);

  const activeSessionId = React.useMemo(() => {
    const match = /^\/chat\/([0-9a-fA-F-]{36})$/.exec(pathname ?? "");
    return match?.[1] ?? null;
  }, [pathname]);

  const refreshSessions = React.useCallback(async () => {
    try {
      const next = await api.listSessions();
      setSessions(sortSessions(next));
    } catch {
      // A failed refresh must not replace a working local list.
    }
  }, []);

  const createSession = React.useCallback(
    async (title?: string) => {
      if (creating) return null;
      setCreating(true);
      try {
        const created = await api.createSession(title);
        setSessions((current) => sortSessions([created, ...current]));
        router.push(`/chat/${created.id}`);
        router.refresh();
        return created;
      } catch (error) {
        toast.error("Session could not be created", {
          description: messageFor(error, "The compliance API did not respond."),
        });
        return null;
      } finally {
        setCreating(false);
      }
    },
    [creating, router],
  );

  const renameSession = React.useCallback(
    async (sessionId: string, title: string) => {
      const trimmed = title.trim();
      if (!trimmed) return false;
      const previous = sessions;
      setSessions((current) =>
        current.map((session) =>
          session.id === sessionId ? { ...session, title: trimmed } : session,
        ),
      );
      try {
        const updated = await api.renameSession(sessionId, trimmed);
        setSessions((current) =>
          sortSessions(
            current.map((session) => (session.id === sessionId ? { ...session, ...updated } : session)),
          ),
        );
        return true;
      } catch (error) {
        setSessions(previous);
        toast.error("Session could not be renamed", {
          description: messageFor(error, "Try again in a moment."),
        });
        return false;
      }
    },
    [sessions],
  );

  const deleteSession = React.useCallback(
    async (sessionId: string) => {
      const previous = sessions;
      const remaining = sessions.filter((session) => session.id !== sessionId);
      setSessions(remaining);
      try {
        await api.deleteSession(sessionId);
        if (activeSessionId === sessionId) {
          router.push(remaining.length > 0 ? `/chat/${remaining[0].id}` : "/chat");
        }
        router.refresh();
        return true;
      } catch (error) {
        setSessions(previous);
        toast.error("Session could not be deleted", {
          description: messageFor(error, "Try again in a moment."),
        });
        return false;
      }
    },
    [activeSessionId, router, sessions],
  );

  React.useEffect(() => {
    const onVisible = () => {
      if (document.visibilityState === "visible") void refreshSessions();
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => document.removeEventListener("visibilitychange", onVisible);
  }, [refreshSessions]);

  const value = React.useMemo<SessionsContextValue>(
    () => ({
      sessions,
      activeSessionId,
      creating,
      createSession,
      renameSession,
      deleteSession,
      refreshSessions,
    }),
    [
      activeSessionId,
      createSession,
      creating,
      deleteSession,
      refreshSessions,
      renameSession,
      sessions,
    ],
  );

  return <SessionsContext.Provider value={value}>{children}</SessionsContext.Provider>;
}

export function useSessions(): SessionsContextValue {
  const context = React.useContext(SessionsContext);
  if (!context) throw new Error("useSessions must be used inside SessionsProvider");
  return context;
}
