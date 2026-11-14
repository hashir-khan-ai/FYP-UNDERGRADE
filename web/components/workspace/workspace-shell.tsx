"use client";

import * as React from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { FileText, Menu, MessageSquare, Plus, ShieldCheck } from "lucide-react";

import { Logo } from "@/components/brand/logo";
import { SessionsProvider, useSessions } from "@/components/providers/sessions-provider";
import { Sidebar } from "@/components/workspace/sidebar";
import { CommandPalette } from "@/components/ui/command-palette";
import { ShortcutsSheet } from "@/components/ui/shortcuts-sheet";
import { Button } from "@/components/ui/button";
import { canViewAudit } from "@/lib/auth";
import { isEventFromEditable } from "@/lib/shortcuts";
import type { AdminConfig, HealthResponse, SessionSummary, UserProfile } from "@/lib/types";
import { cn } from "@/lib/utils";

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

function MobileBottomBar({
  role,
  onOpenMenu,
}: {
  role: string;
  onOpenMenu: () => void;
}) {
  const pathname = usePathname();
  const { createSession, creating } = useSessions();
  const auditAllowed = canViewAudit(role);

  return (
    <nav
      aria-label="Mobile quick navigation"
      className="fixed inset-x-0 bottom-0 z-30 flex h-14 items-center justify-around border-t border-line bg-canvas-raised/95 px-2 backdrop-blur-md md:hidden"
    >
      <Link
        href="/chat"
        aria-label="Compliance chat"
        className={cn(
          "flex min-h-[44px] min-w-[44px] flex-col items-center justify-center rounded-[var(--r-sm)] text-[10px] font-medium transition-colors",
          pathname?.startsWith("/chat") ? "text-accent" : "text-muted hover:text-ink",
        )}
      >
        <MessageSquare className="size-4" aria-hidden="true" />
        <span>Chat</span>
      </Link>

      <Link
        href="/documents"
        aria-label="Docs - Document catalog"
        className={cn(
          "flex min-h-[44px] min-w-[44px] flex-col items-center justify-center rounded-[var(--r-sm)] text-[10px] font-medium transition-colors",
          pathname === "/documents" ? "text-accent" : "text-muted hover:text-ink",
        )}
      >
        <FileText className="size-4" aria-hidden="true" />
        <span>Docs</span>
      </Link>

      {auditAllowed ? (
        <Link
          href="/audit"
          aria-label="Audit log"
          className={cn(
            "flex min-h-[44px] min-w-[44px] flex-col items-center justify-center rounded-[var(--r-sm)] text-[10px] font-medium transition-colors",
            pathname === "/audit" ? "text-accent" : "text-muted hover:text-ink",
          )}
        >
          <ShieldCheck className="size-4" aria-hidden="true" />
          <span>Audit</span>
        </Link>
      ) : null}

      <button
        type="button"
        onClick={() => void createSession()}
        disabled={creating}
        aria-label="New session"
        className="flex min-h-[44px] min-w-[44px] flex-col items-center justify-center rounded-[var(--r-sm)] text-[10px] font-medium text-accent"
      >
        <Plus className="size-4" aria-hidden="true" />
        <span>New</span>
      </button>

      <button
        type="button"
        onClick={onOpenMenu}
        aria-label="Workspace menu"
        className="flex min-h-[44px] min-w-[44px] flex-col items-center justify-center rounded-[var(--r-sm)] text-[10px] font-medium text-muted hover:text-ink"
      >
        <Menu className="size-4" aria-hidden="true" />
        <span>Menu</span>
      </button>
    </nav>
  );
}

function WorkspaceInner({
  user,
  config,
  health,
  children,
}: {
  user: UserProfile;
  config: AdminConfig | null;
  health: HealthResponse | null;
  children: React.ReactNode;
}) {
  const router = useRouter();
  const [mobileOpen, setMobileOpen] = React.useState(false);
  const [collapsed, setCollapsed] = React.useState(false);
  const [paletteOpen, setPaletteOpen] = React.useState(false);
  const [shortcutsOpen, setShortcutsOpen] = React.useState(false);
  const { createSession } = useSessions();

  const role = String(user.role ?? "").toLowerCase();

  // Global Keyboard Shortcuts Listener
  React.useEffect(() => {
    function handleKeyDown(event: KeyboardEvent) {
      const isEditable = isEventFromEditable(event);

      // Cmd+K / Ctrl+K: Command Palette (allowed anywhere)
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setPaletteOpen((prev) => !prev);
        return;
      }

      // Cmd+B / Ctrl+B: Toggle Sidebar (allowed anywhere)
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "b") {
        event.preventDefault();
        setCollapsed((prev) => !prev);
        return;
      }

      // Escape: close open overlays
      if (event.key === "Escape") {
        if (paletteOpen) {
          setPaletteOpen(false);
          return;
        }
        if (shortcutsOpen) {
          setShortcutsOpen(false);
          return;
        }
      }

      // The shortcuts below are suppressed if the user is typing in a text field
      if (isEditable) return;

      // ?: Open keyboard shortcuts sheet
      if (event.key === "?") {
        event.preventDefault();
        setShortcutsOpen(true);
        return;
      }

      // /: Focus composer input
      if (event.key === "/") {
        event.preventDefault();
        const composer = document.querySelector<HTMLTextAreaElement>(
          'textarea[aria-label="Ask a regulatory compliance question"]',
        );
        if (composer) {
          composer.focus();
        }
        return;
      }

      // Cmd+Shift+O or Cmd+N: New session
      if (
        (event.metaKey || event.ctrlKey) &&
        (event.key.toLowerCase() === "n" || (event.shiftKey && event.key.toLowerCase() === "o"))
      ) {
        event.preventDefault();
        void createSession();
        return;
      }

      // Cmd+1: Chat
      if ((event.metaKey || event.ctrlKey) && event.key === "1") {
        event.preventDefault();
        router.push("/chat");
        return;
      }

      // Cmd+2: Documents
      if ((event.metaKey || event.ctrlKey) && event.key === "2") {
        event.preventDefault();
        router.push("/documents");
        return;
      }

      // Cmd+3: Audit (if allowed)
      if ((event.metaKey || event.ctrlKey) && event.key === "3" && canViewAudit(role)) {
        event.preventDefault();
        router.push("/audit");
        return;
      }
    }

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [paletteOpen, shortcutsOpen, createSession, role, router]);

  return (
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
        collapsed={collapsed}
        onToggleCollapsed={() => setCollapsed((prev) => !prev)}
      />

      <div
        className={cn(
          "transition-[padding-left] duration-200",
          collapsed ? "lg:pl-16" : "lg:pl-[var(--sidebar-width)]",
        )}
      >
        <MobileTopbar onOpenMenu={() => setMobileOpen(true)} />
        <main
          id="main"
          tabIndex={-1}
          className="min-h-[calc(100dvh-3.5rem)] pb-16 md:pb-0 lg:min-h-dvh"
        >
          {children}
        </main>
      </div>

      <MobileBottomBar role={role} onOpenMenu={() => setMobileOpen(true)} />

      <CommandPalette
        open={paletteOpen}
        onOpenChange={setPaletteOpen}
        userRole={role}
      />

      <ShortcutsSheet
        open={shortcutsOpen}
        onOpenChange={setShortcutsOpen}
      />
    </div>
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
  return (
    <SessionsProvider initialSessions={initialSessions}>
      <WorkspaceInner user={user} config={config} health={health}>
        {children}
      </WorkspaceInner>
    </SessionsProvider>
  );
}
