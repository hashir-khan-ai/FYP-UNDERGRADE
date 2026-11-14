"use client";

import * as React from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { FileText, MessageSquare, Search, ShieldCheck } from "lucide-react";

import { Logo } from "@/components/brand/logo";
import { Button, buttonVariants } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { api } from "@/lib/api-client";
import type { SessionSummary } from "@/lib/types";

export default function NotFound() {
  const router = useRouter();
  const [sessions, setSessions] = React.useState<SessionSummary[]>([]);
  const [query, setQuery] = React.useState("");
  const [loaded, setLoaded] = React.useState(false);

  React.useEffect(() => {
    let active = true;
    api
      .listSessions()
      .then((data) => {
        if (active) {
          setSessions(data);
          setLoaded(true);
        }
      })
      .catch(() => {
        if (active) setLoaded(true);
      });
    return () => {
      active = false;
    };
  }, []);

  const filteredSessions = React.useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return [];
    return sessions.filter((s) => s.title.toLowerCase().includes(q)).slice(0, 5);
  }, [sessions, query]);

  return (
    <div className="relative flex min-h-dvh flex-col items-center justify-center px-4 py-12 text-center">
      <div className="app-atmosphere" aria-hidden="true" />

      <div className="relative z-10 w-full max-w-lg rounded-[var(--r-lg)] border border-line bg-canvas-raised/80 p-8 shadow-2xl backdrop-blur-md">
        <Logo showWordmark className="justify-center" />

        <p className="mt-6 font-mono text-[11px] uppercase tracking-[0.16em] text-faint">
          404 · Resource Not Found
        </p>

        <h1 className="mt-2 text-2xl font-semibold tracking-[-0.03em] text-ink">
          Page is outside your workspace.
        </h1>

        <p className="mt-2 text-xs leading-relaxed text-muted">
          The requested route or session does not exist, has been removed, or is not accessible.
        </p>

        {/* Search user's own sessions only */}
        {loaded && sessions.length > 0 ? (
          <div className="mt-6 text-left">
            <label htmlFor="notfound-search" className="block text-xs font-medium text-faint mb-1.5">
              Looking for a past session?
            </label>
            <div className="relative">
              <Search
                className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-faint"
                aria-hidden="true"
              />
              <Input
                id="notfound-search"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Search your session titles..."
                className="h-9 pl-9 text-xs"
              />
            </div>

            {query.trim() && (
              <div className="mt-2 rounded-[var(--r-sm)] border border-line bg-surface p-1.5 space-y-1">
                {filteredSessions.length === 0 ? (
                  <p className="p-2 text-xs text-muted text-center">No matching sessions found.</p>
                ) : (
                  filteredSessions.map((s) => (
                    <button
                      key={s.id}
                      type="button"
                      onClick={() => router.push(`/chat/${s.id}`)}
                      className="flex w-full items-center gap-2 rounded px-2.5 py-1.5 text-xs text-ink hover:bg-surface-2 transition-colors text-left"
                    >
                      <MessageSquare className="size-3.5 text-accent shrink-0" />
                      <span className="truncate flex-1">{s.title}</span>
                    </button>
                  ))
                )}
              </div>
            )}
          </div>
        ) : null}

        <div className="mt-6 flex flex-wrap items-center justify-center gap-2">
          <Link href="/chat" className={buttonVariants({ variant: "primary", size: "sm" })}>
            <MessageSquare className="size-3.5" /> Return to chat
          </Link>
          <Link href="/documents" className={buttonVariants({ variant: "secondary", size: "sm" })}>
            <FileText className="size-3.5" /> Document catalog
          </Link>
          <Link href="/audit" className={buttonVariants({ variant: "ghost", size: "sm" })}>
            <ShieldCheck className="size-3.5" /> Audit log
          </Link>
        </div>
      </div>
    </div>
  );
}
