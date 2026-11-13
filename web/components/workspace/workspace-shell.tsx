"use client";

import * as React from "react";
import { Menu, Plus } from "lucide-react";

import { Logo } from "@/components/brand/logo";
import { SessionsProvider, useSessions } from "@/components/providers/sessions-provider";
import { Sidebar } from "@/components/workspace/sidebar";
import { Button } from "@/components/ui/button";
import type { AdminConfig, HealthResponse, SessionSummary, UserProfile } from "@/lib/types";

function MobileTopbar({ onOpenMenu }: { onOpenMenu: () => void }) {
  const { createSession, creating } = useSessions();
  return (
    <header className="glass-bar sticky top-0 z-20 flex h-14 items-center gap-2 border-b px-3 lg:hidden">
      <Button variant="ghost" size="icon" onClick={onOpenMenu} aria-label="Open navigation">
        <Menu />
      </Button>
      <Logo className="min-w-0 flex-1" />
      <Button
        variant="secondary"
        size="icon"
        onClick={() => void createSession()}
        disabled={creating}
        aria-label="New session"
      >
        <Plus />
      </Button>
    </header>
  );
}

export function WorkspaceShell({
  user,
  initialSessions,
  config,
  health,
  children,
}: {
  user: UserProfile;
  initialSessions: SessionSummary[];
  config: AdminConfig | null;
  health: HealthResponse | null;
  children: React.ReactNode;
}) {
  const [mobileOpen, setMobileOpen] = React.useState(false);

  return (
    <SessionsProvider initialSessions={initialSessions}>
      <div className="min-h-dvh">
        <div className="app-atmosphere" aria-hidden="true" />
        <a
          href="#main"
          className="sr-only focus:not-sr-only focus:fixed focus:left-4 focus:top-4 focus:z-50 focus:rounded-md focus:bg-accent focus:px-3 focus:py-2 focus:text-sm focus:text-accent-ink"
        >
          Skip to content
        </a>
        <Sidebar
          user={user}
          config={config}
          health={health}
          mobileOpen={mobileOpen}
          onMobileOpenChange={setMobileOpen}
        />
        <div className="lg:pl-[var(--sidebar-width)]">
          <MobileTopbar onOpenMenu={() => setMobileOpen(true)} />
          <main id="main" tabIndex={-1} className="min-h-[calc(100dvh-3.5rem)] lg:min-h-dvh">
            {children}
          </main>
        </div>
      </div>
    </SessionsProvider>
  );
}
