"use client";

import * as React from "react";
import { ArrowRight, FileText, Plus, ShieldCheck } from "lucide-react";
import Link from "next/link";

import { TrustMap } from "@/components/visual/trust-map";
import { useSessions } from "@/components/providers/sessions-provider";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";

export function ChatLanding({ name }: { name: string }) {
  const { createSession, creating } = useSessions();
  const firstName = name.trim().split(/\s+/)[0] || "there";

  return (
    <div className="mx-auto flex min-h-[calc(100dvh-3.5rem)] w-full max-w-4xl flex-col items-center justify-center px-4 py-10 lg:min-h-dvh">
      <div className="w-full rounded-[var(--r-xl)] border border-line bg-surface/55 p-5 shadow-[var(--elev-md)] sm:p-8">
        <div className="grid items-center gap-6 lg:grid-cols-[1.05fr_0.95fr]">
          <div>
            <Badge tone="accent" className="mb-3">
              <ShieldCheck /> Server-enforced access control
            </Badge>
            <h1 className="text-xl font-semibold tracking-[-0.025em] text-ink sm:text-2xl">
              Welcome, {firstName}. Start a compliance session.
            </h1>
            <p className="mt-2 max-w-md text-sm leading-relaxed text-muted">
              Retrieval, grading and citation verification run locally against the FastAPI
              pipeline. Your role is resolved from a signed token on the server, never from this
              page.
            </p>
            <div className="mt-5 flex flex-wrap gap-2">
              <Button variant="primary" onClick={() => void createSession()} disabled={creating}>
                <Plus /> {creating ? "Creating…" : "New compliance session"}
              </Button>
              <Button variant="secondary" asChild>
                <Link href="/documents">
                  <FileText /> Browse catalog <ArrowRight />
                </Link>
              </Button>
            </div>
            <p className="mt-4 text-xs leading-relaxed text-faint">
              No session exists yet. The login flow normally creates one automatically; you can also
              create one here.
            </p>
          </div>
          <div className="rounded-[var(--r-lg)] border border-line bg-[rgba(3,6,10,0.3)] p-3">
            <TrustMap />
            <p className="mt-1 text-center text-xs text-faint">
              Corpus → role gate → relevance grader → verified answer
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
