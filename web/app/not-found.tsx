"use client";

import * as React from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { FileText, MessageSquare, Search, ShieldCheck } from "lucide-react";

import { Logo } from "@/components/brand/logo";
import { Button, buttonVariants } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { NotFoundIllustration } from "@/components/visual/illustrations";
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
    <main className="relative flex min-h-dvh flex-col items-center justify-center px-4 py-12 text-center">
      <div className="app-atmosphere" aria-hidden="true" />

      <div className="relative z-10 w-full max-w-lg rounded-[var(--r-xl)] bg-surface p-6 shadow-[var(--elev-3)] sm:p-8">
        <Logo showWordmark className="justify-center" />

        <NotFoundIllustration className="mt-5" />

        <p className="mt-4 font-mono text-xs uppercase tracking-[0.16em] text-faint">
          404 · Resource Not Found
        </p>

        <h1 className="mt-2 font-display text-2xl font-semibold tracking-[-0.02em] text-ink">
          Page is outside your workspace.
        </h1>

        <p className="mt-2 text-sm leading-relaxed text-muted">
          The requested route or session does not exist, has been removed, or is not accessible.
        </p>

        {/* Search user's own sessions only */}
        {loaded && sessions.length > 0 ? (
          <div className="mt-6 text-left">
            <label htmlFor="notfound-search" className="mb-1.5 block text-xs font-medium text-faint">
              Looking for a past session?
            </label>
            <div className="relative">
              <Search
                className="pointer-events-none absolute left-3.5 top-1/2 size-4 -translate-y-1/2 text-faint"
                aria-hidden="true"
              />
              <Input
                id="notfound-search"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Search your session titles…"
                className="h-11 pl-10 text-sm"
              />
            </div>

            {query.trim() && (
              <div className="mt-2 space-y-1 rounded-[var(--r-md)] bg-surface-2 p-1.5 shadow-[var(--elev-2)]">
                {filteredSessions.length === 0 ? (
                  <p className="p-2 text-center text-xs text-muted">No matching sessions found.</p>
                ) : (
                  filteredSessions.map((s) => (
                    <button
                      key={s.id}
                      type="button"
                      onClick={() => router.push(`/chat/${s.id}`)}
                      className="flex min-h-[44px] w-full items-center gap-2.5 rounded px-3 py-2 text-left text-xs text-ink transition-colors hover:bg-surface-2"
                    >
                      <MessageSquare className="size-4 shrink-0 text-accent" />
                      <span className="flex-1 truncate">{s.title}</span>
                    </button>
                  ))
                )}
              </div>
            )}
          </div>
        ) : null}

        <div className="mt-6 flex flex-wrap items-center justify-center gap-2.5">
          <Link href="/chat" className={buttonVariants({ variant: "primary", size: "md" })}>
            <MessageSquare className="size-4" /> Return to chat
          </Link>
          <Link href="/documents" className={buttonVariants({ variant: "secondary", size: "md" })}>
            <FileText className="size-4" /> Document catalog
          </Link>
          <Link href="/audit" className={buttonVariants({ variant: "ghost", size: "md" })}>
            <ShieldCheck className="size-4" /> Audit log
          </Link>
        </div>
      </div>
    </main>
  );
}
