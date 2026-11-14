"use client";

import * as React from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import {
  Check,
  FileText,
  Lock,
  LogOut,
  MessageSquare,
  MoreHorizontal,
  PanelLeftClose,
  PanelLeftOpen,
  Pencil,
  Plus,
  Search,
  ServerCog,
  ShieldCheck,
  Sparkles,
  Trash2,
  X,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { toast } from "sonner";

import { Logo } from "@/components/brand/logo";
import { SystemSheet } from "@/components/workspace/system-sheet";
import { Avatar } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { DestructiveDialog } from "@/components/ui/destructive-dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { useSessions } from "@/components/providers/sessions-provider";
import { canViewAudit, roleLabel, roleScope } from "@/lib/auth";
import { api } from "@/lib/api-client";
import { formatRelative } from "@/lib/format";
import { useDebouncedValue } from "@/lib/hooks/use-debounce";
import type { AdminConfig, HealthResponse, SessionSummary, UserProfile } from "@/lib/types";
import { cn } from "@/lib/utils";

interface SidebarProps {
  user: UserProfile;
  config: AdminConfig | null;
  health: HealthResponse | null;
  mobileOpen: boolean;
  onMobileOpenChange: (open: boolean) => void;
  collapsed?: boolean;
  onToggleCollapsed?: () => void;
}

function NavItem({
  href,
  label,
  icon: Icon,
  active,
  disabled,
  hint,
  collapsed,
  onNavigate,
}: {
  href: string;
  label: string;
  icon: LucideIcon;
  active: boolean;
  disabled?: boolean;
  hint?: string;
  collapsed?: boolean;
  onNavigate?: () => void;
}) {
  if (disabled) {
    if (collapsed) {
      return (
        <Tooltip>
          <TooltipTrigger asChild>
            <div
              aria-disabled="true"
              className="flex size-10 items-center justify-center rounded-[var(--r-sm)] text-faint/50 cursor-not-allowed"
            >
              <Icon className="size-5" aria-hidden="true" />
            </div>
          </TooltipTrigger>
          <TooltipContent side="right">
            <span>{label} (Restricted)</span>
          </TooltipContent>
        </Tooltip>
      );
    }
    return (
      <div
        aria-disabled="true"
        title={hint}
        className="flex min-h-[44px] items-center gap-3 rounded-[var(--r-sm)] px-3 text-xs font-medium text-faint/70"
      >
        <Icon className="size-4.5" aria-hidden="true" />
        <span className="flex-1">{label}</span>
        <Lock className="size-3.5" aria-hidden="true" />
      </div>
    );
  }

  if (collapsed) {
    return (
      <Tooltip>
        <TooltipTrigger asChild>
          <Link
            href={href}
            onClick={onNavigate}
            aria-current={active ? "page" : undefined}
            aria-label={label}
            className={cn(
              "flex size-10 items-center justify-center rounded-[var(--r-sm)] transition-colors duration-[var(--duration-fast)]",
              active
                ? "bg-surface-2 text-accent shadow-[inset_0_1px_0_rgba(255,255,255,0.035)]"
                : "text-muted hover:bg-surface-2/70 hover:text-ink",
            )}
          >
            <Icon className="size-5" aria-hidden="true" />
          </Link>
        </TooltipTrigger>
        <TooltipContent side="right">
          <span>{label}</span>
        </TooltipContent>
      </Tooltip>
    );
  }

  return (
    <Link
      href={href}
      onClick={onNavigate}
      aria-current={active ? "page" : undefined}
      className={cn(
        "flex min-h-[44px] items-center gap-3 rounded-[var(--r-sm)] px-3 text-xs font-medium transition-colors duration-[var(--duration-fast)]",
        active
          ? "bg-surface-2 text-ink shadow-[inset_0_1px_0_rgba(255,255,255,0.035)]"
          : "text-muted hover:bg-surface-2/70 hover:text-ink",
      )}
    >
      <Icon className={cn("size-4.5", active ? "text-accent" : "text-faint")} aria-hidden="true" />
      <span className="flex-1">{label}</span>
    </Link>
  );
}

function SessionRow({
  session,
  active,
  onNavigate,
}: {
  session: SessionSummary;
  active: boolean;
  onNavigate?: () => void;
}) {
  const { renameSession, deleteSession, sessions } = useSessions();
  const router = useRouter();
  const [renaming, setRenaming] = React.useState(false);
  const [value, setValue] = React.useState(session.title);
  const [saving, setSaving] = React.useState(false);
  const [deleteOpen, setDeleteOpen] = React.useState(false);
  const [deleting, setDeleting] = React.useState(false);
  const inputRef = React.useRef<HTMLInputElement>(null);

  React.useEffect(() => {
    if (renaming) {
      inputRef.current?.focus();
      inputRef.current?.select();
    }
  }, [renaming]);

  React.useEffect(() => {
    setValue(session.title);
  }, [session.title]);

  async function commitRename() {
    const trimmed = value.trim();
    if (!trimmed || trimmed === session.title) {
      setRenaming(false);
      setValue(session.title);
      return;
    }
    setSaving(true);
    const ok = await renameSession(session.id, trimmed);
    setSaving(false);
    if (ok) {
      setRenaming(false);
      toast.success("Session renamed");
    }
  }

  async function confirmDelete() {
    setDeleting(true);
    const ok = await deleteSession(session.id);
    setDeleting(false);
    if (ok) {
      setDeleteOpen(false);
      toast.success("Session deleted");
      if (active && sessions.length <= 1) router.push("/chat");
    }
  }

  if (renaming) {
    return (
      <div className="rounded-[var(--r-sm)] border border-line-accent bg-surface-2 p-2">
        <Input
          ref={inputRef}
          value={value}
          maxLength={120}
          onChange={(event) => setValue(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter") {
              event.preventDefault();
              void commitRename();
            }
            if (event.key === "Escape") {
              setRenaming(false);
              setValue(session.title);
            }
          }}
          className="h-10 text-xs"
          aria-label={`Rename ${session.title}`}
        />
        <div className="mt-2 flex justify-end gap-1.5">
          <Button
            size="icon-sm"
            variant="ghost"
            onClick={() => {
              setRenaming(false);
              setValue(session.title);
            }}
            aria-label="Cancel rename"
          >
            <X />
          </Button>
          <Button
            size="icon-sm"
            variant="soft"
            onClick={() => void commitRename()}
            disabled={saving}
            aria-label="Save session name"
          >
            <Check />
          </Button>
        </div>
      </div>
    );
  }

  return (
    <div
      className={cn(
        "group relative flex min-h-[44px] items-center rounded-[var(--r-sm)] transition-colors",
        active ? "bg-surface-2" : "hover:bg-surface-2/60",
      )}
    >
      <Link
        href={`/chat/${session.id}`}
        onClick={onNavigate}
        aria-current={active ? "page" : undefined}
        className="min-w-0 flex-1 py-1.5 pl-3 pr-1"
      >
        <span
          className={cn(
            "block truncate text-xs font-semibold leading-snug",
            active ? "text-ink" : "text-ink-soft group-hover:text-ink",
          )}
        >
          {session.title}
        </span>
        <span className="mt-0.5 block truncate text-[11px] text-faint">
          {formatRelative(session.updated_at ?? session.created_at)}
        </span>
      </Link>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button
            size="icon-sm"
            variant="ghost"
            aria-label={`Actions for ${session.title}`}
            className={cn(
              "mr-1 opacity-0 transition-opacity group-hover:opacity-100 focus-visible:opacity-100 data-[state=open]:opacity-100",
              active && "opacity-100",
            )}
          >
            <MoreHorizontal />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent>
          <DropdownMenuItem onSelect={() => setRenaming(true)}>
            <Pencil /> Rename
          </DropdownMenuItem>
          <DropdownMenuSeparator />
          <DropdownMenuItem
            onSelect={() => setDeleteOpen(true)}
            className="text-danger data-[highlighted]:bg-danger-soft data-[highlighted]:text-danger"
          >
            <Trash2 /> Delete
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>

      <DestructiveDialog
        open={deleteOpen}
        onOpenChange={setDeleteOpen}
        title="Delete this session?"
        description={`"${session.title}" and its conversation history will be permanently deleted. This action cannot be undone.`}
        confirmLabel="Delete session"
        onConfirm={confirmDelete}
        isLoading={deleting}
      />
    </div>
  );
}

function groupSessionsByDate(sessions: SessionSummary[]) {
  const now = new Date();
  const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
  const sevenDaysAgo = startOfToday - 7 * 24 * 60 * 60 * 1000;

  const today: SessionSummary[] = [];
  const previous7Days: SessionSummary[] = [];
  const older: SessionSummary[] = [];

  for (const s of sessions) {
    const timeStr = s.updated_at ?? s.created_at;
    const time = timeStr ? new Date(timeStr).getTime() : 0;
    if (time >= startOfToday) {
      today.push(s);
    } else if (time >= sevenDaysAgo) {
      previous7Days.push(s);
    } else {
      older.push(s);
    }
  }

  return { today, previous7Days, older };
}

function SidebarBody({
  user,
  config,
  health,
  collapsed = false,
  onToggleCollapsed,
  onNavigate,
  onClose,
}: {
  user: UserProfile;
  config: AdminConfig | null;
  health: HealthResponse | null;
  collapsed?: boolean;
  onToggleCollapsed?: () => void;
  onNavigate?: () => void;
  onClose?: () => void;
}) {
  const pathname = usePathname();
  const router = useRouter();
  const { sessions, createSession, creating } = useSessions();
  const [query, setQuery] = React.useState("");
  const debouncedQuery = useDebouncedValue(query, 250);
  const [signingOut, setSigningOut] = React.useState(false);

  const role = String(user.role ?? "").toLowerCase();
  const auditAllowed = canViewAudit(role);

  const filtered = React.useMemo(() => {
    const needle = debouncedQuery.trim().toLowerCase();
    if (!needle) return sessions;
    return sessions.filter((session) => session.title.toLowerCase().includes(needle));
  }, [debouncedQuery, sessions]);

  const dateGroups = React.useMemo(() => {
    return groupSessionsByDate(sessions);
  }, [sessions]);

  async function handleSignOut() {
    setSigningOut(true);
    try {
      await api.logout();
    } catch {
      // BFF clears session cookie even if API is offline
    }
    router.replace("/login");
    router.refresh();
  }

  // Collapsed Sidebar View (64px icon bar)
  if (collapsed) {
    return (
      <TooltipProvider>
        <div className="flex h-full min-h-0 flex-col items-center justify-between bg-canvas-raised/80 py-3">
          <div className="flex flex-col items-center gap-3">
            <Logo showWordmark={false} />
            {onToggleCollapsed ? (
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button
                    variant="ghost"
                    size="icon-sm"
                    onClick={onToggleCollapsed}
                    aria-label="Expand sidebar"
                  >
                    <PanelLeftOpen className="size-4" />
                  </Button>
                </TooltipTrigger>
                <TooltipContent side="right">Expand sidebar (Ctrl+B)</TooltipContent>
              </Tooltip>
            ) : null}

            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  variant="primary"
                  size="icon-sm"
                  onClick={() => {
                    void createSession();
                    onNavigate?.();
                  }}
                  disabled={creating}
                  aria-label="New session"
                >
                  <Plus className="size-4" />
                </Button>
              </TooltipTrigger>
              <TooltipContent side="right">New session</TooltipContent>
            </Tooltip>

            <nav aria-label="Workspace mini navigation" className="mt-2 flex flex-col gap-1.5">
              <NavItem
                href="/chat"
                label="Compliance chat"
                icon={MessageSquare}
                active={Boolean(pathname?.startsWith("/chat"))}
                collapsed
                onNavigate={onNavigate}
              />
              <NavItem
                href="/documents"
                label="Document catalog"
                icon={FileText}
                active={pathname === "/documents"}
                collapsed
                onNavigate={onNavigate}
              />
              <NavItem
                href="/audit"
                label="Audit & RBAC"
                icon={ShieldCheck}
                active={pathname === "/audit"}
                disabled={!auditAllowed}
                hint="Auditor role required"
                collapsed
                onNavigate={onNavigate}
              />
            </nav>
          </div>

          <div className="flex flex-col items-center gap-3">
            <SystemSheet
              health={health}
              config={config}
              trigger={
                <Button variant="ghost" size="icon-sm" aria-label="System status">
                  <ServerCog className="size-4" />
                </Button>
              }
            />

            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <button
                  type="button"
                  className="rounded-full focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
                  aria-label="Account menu"
                >
                  <Avatar name={user.full_name} size="sm" />
                </button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end" className="w-56">
                <DropdownMenuLabel>
                  <span className="block font-medium">{user.full_name}</span>
                  <span className="block text-xs text-faint">@{user.username} · {roleLabel(role)}</span>
                </DropdownMenuLabel>
                <DropdownMenuSeparator />
                <DropdownMenuItem onSelect={() => router.push("/documents")}>
                  <FileText /> Document catalog
                </DropdownMenuItem>
                {auditAllowed ? (
                  <DropdownMenuItem onSelect={() => router.push("/audit")}>
                    <ShieldCheck /> Audit summaries
                  </DropdownMenuItem>
                ) : null}
                <DropdownMenuSeparator />
                <DropdownMenuItem
                  onSelect={() => void handleSignOut()}
                  disabled={signingOut}
                  className="text-danger data-[highlighted]:bg-danger-soft data-[highlighted]:text-danger"
                >
                  <LogOut /> {signingOut ? "Signing out…" : "Sign out"}
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        </div>
      </TooltipProvider>
    );
  }

  // Expanded Standard Sidebar View
  return (
    <div className="flex h-full min-h-0 flex-col bg-canvas-raised/60">
      <div className="flex items-center gap-2 px-4 pb-1 pt-4">
        <Logo showWordmark className="min-w-0 flex-1" />
        {onToggleCollapsed ? (
          <Button
            variant="ghost"
            size="icon-sm"
            onClick={onToggleCollapsed}
            aria-label="Collapse sidebar"
            title="Collapse sidebar (Ctrl+B)"
          >
            <PanelLeftClose className="size-4" />
          </Button>
        ) : null}
        <SystemSheet
          health={health}
          config={config}
          trigger={
            <Button variant="ghost" size="icon-sm" aria-label="System status">
              <ServerCog />
            </Button>
          }
        />
        {onClose ? (
          <Button variant="ghost" size="icon-sm" onClick={onClose} aria-label="Close navigation">
            <X />
          </Button>
        ) : null}
      </div>

      <div className="px-3 pt-3">
        <Button
          variant="primary"
          size="md"
          className="w-full justify-start"
          onClick={() => {
            void createSession();
            onNavigate?.();
          }}
          disabled={creating}
        >
          <Plus />
          {creating ? "Creating session…" : "New session"}
        </Button>
      </div>

      <nav aria-label="Workspace" className="mt-3 space-y-0.5 px-3">
        <NavItem
          href="/chat"
          label="Compliance chat"
          icon={MessageSquare}
          active={Boolean(pathname?.startsWith("/chat"))}
          onNavigate={onNavigate}
        />
        <NavItem
          href="/documents"
          label="Document catalog"
          icon={FileText}
          active={pathname === "/documents"}
          onNavigate={onNavigate}
        />
        <NavItem
          href="/audit"
          label="Audit & RBAC"
          icon={ShieldCheck}
          active={pathname === "/audit"}
          disabled={!auditAllowed}
          hint="Only the auditor role may read audit summaries."
          onNavigate={onNavigate}
        />
      </nav>

      <div className="mt-4 flex items-center justify-between px-4">
        <span className="text-xs font-semibold uppercase tracking-[0.08em] text-faint">
          Sessions
        </span>
        <span className="tabular text-xs text-faint">{sessions.length}</span>
      </div>

      <div className="px-3 pt-2">
        <div className="relative">
          <Search
            className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-faint"
            aria-hidden="true"
          />
          <Input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Search sessions"
            aria-label="Search sessions"
            className="h-9 pl-9 text-xs"
          />
        </div>
      </div>

      <div className="mt-2 min-h-0 flex-1 overflow-y-auto px-2 pb-3">
        {filtered.length === 0 ? (
          <div className="mx-2 mt-3 rounded-[var(--r-sm)] border border-dashed border-line px-3 py-4 text-center">
            <p className="text-xs font-medium text-ink-soft">
              {sessions.length === 0 ? "No sessions yet" : "No matching sessions"}
            </p>
            <p className="mt-1 text-xs leading-relaxed text-faint">
              {sessions.length === 0
                ? "Create one to start a compliance conversation."
                : "Try a shorter search term."}
            </p>
          </div>
        ) : debouncedQuery.trim() ? (
          // Search results
          <div className="space-y-1">
            {filtered.map((session) => (
              <SessionRow
                key={session.id}
                session={session}
                active={pathname === `/chat/${session.id}`}
                onNavigate={onNavigate}
              />
            ))}
          </div>
        ) : (
          // Date-grouped sessions
          <div className="space-y-2">
            {dateGroups.today.length > 0 ? (
              <div>
                <div className="px-2 pb-1 text-[11px] font-semibold uppercase tracking-[0.08em] text-faint">
                  Today
                </div>
                <div className="space-y-1">
                  {dateGroups.today.map((s) => (
                    <SessionRow
                      key={s.id}
                      session={s}
                      active={pathname === `/chat/${s.id}`}
                      onNavigate={onNavigate}
                    />
                  ))}
                </div>
              </div>
            ) : null}

            {dateGroups.previous7Days.length > 0 ? (
              <div>
                <div className="px-2 pt-2 pb-1 text-[11px] font-semibold uppercase tracking-[0.08em] text-faint">
                  Previous 7 days
                </div>
                <div className="space-y-1">
                  {dateGroups.previous7Days.map((s) => (
                    <SessionRow
                      key={s.id}
                      session={s}
                      active={pathname === `/chat/${s.id}`}
                      onNavigate={onNavigate}
                    />
                  ))}
                </div>
              </div>
            ) : null}

            {dateGroups.older.length > 0 ? (
              <div>
                <div className="px-2 pt-2 pb-1 text-[11px] font-semibold uppercase tracking-[0.08em] text-faint">
                  Older
                </div>
                <div className="space-y-1">
                  {dateGroups.older.map((s) => (
                    <SessionRow
                      key={s.id}
                      session={s}
                      active={pathname === `/chat/${s.id}`}
                      onNavigate={onNavigate}
                    />
                  ))}
                </div>
              </div>
            ) : null}
          </div>
        )}
      </div>

      <div className="border-t border-line px-3 py-3">
        <div className="mb-2 flex flex-wrap items-center gap-1.5">
          <Badge tone="accent">{roleLabel(role)}</Badge>
          <Badge tone={config?.profile === "mock" ? "neutral" : "warning"}>
            <Sparkles /> {config?.profile ?? "mock"}
          </Badge>
          <Badge tone={health ? "success" : "warning"}>
            <span
              className={cn("size-1.5 rounded-full", health ? "bg-success" : "bg-warning")}
              aria-hidden="true"
            />
            {health ? "Live" : "Offline"}
          </Badge>
        </div>
        <p className="mb-2 text-xs leading-relaxed text-faint">{roleScope(role)}</p>

        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <button
              type="button"
              className="flex min-h-[44px] w-full items-center gap-2.5 rounded-[var(--r-sm)] border border-line bg-surface-2/60 p-2 text-left transition-colors hover:border-line-strong hover:bg-surface-2 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
            >
              <Avatar name={user.full_name} size="sm" />
              <span className="min-w-0 flex-1">
                <span className="block truncate text-xs font-medium text-ink">
                  {user.full_name}
                </span>
                <span className="block truncate text-xs text-faint">
                  @{user.username} · {roleLabel(role)}
                </span>
              </span>
              <MoreHorizontal className="size-4 text-faint" aria-hidden="true" />
            </button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="start" className="w-56">
            <DropdownMenuLabel>Signed in as {user.username}</DropdownMenuLabel>
            <DropdownMenuSeparator />
            <DropdownMenuItem onSelect={() => router.push("/documents")}>
              <FileText /> Document catalog
            </DropdownMenuItem>
            <DropdownMenuItem
              disabled={!auditAllowed}
              onSelect={() => {
                if (auditAllowed) router.push("/audit");
              }}
            >
              <ShieldCheck /> Audit summaries
            </DropdownMenuItem>
            <DropdownMenuSeparator />
            <DropdownMenuItem
              onSelect={() => void handleSignOut()}
              disabled={signingOut}
              className="text-danger data-[highlighted]:bg-danger-soft data-[highlighted]:text-danger"
            >
              <LogOut /> {signingOut ? "Signing out…" : "Sign out"}
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    </div>
  );
}

export function Sidebar({
  user,
  config,
  health,
  mobileOpen,
  onMobileOpenChange,
  collapsed = false,
  onToggleCollapsed,
}: SidebarProps) {
  return (
    <>
      <aside
        className={cn(
          "fixed inset-y-0 left-0 z-30 hidden border-r border-line lg:block transition-[width] duration-200",
          collapsed ? "w-16" : "w-[var(--sidebar-width)]",
        )}
      >
        <SidebarBody
          user={user}
          config={config}
          health={health}
          collapsed={collapsed}
          onToggleCollapsed={onToggleCollapsed}
        />
      </aside>

      <div
        role="dialog"
        aria-modal="true"
        aria-label="Workspace navigation"
        className={cn(
          "fixed inset-0 z-50 lg:hidden transition-opacity duration-200",
          mobileOpen ? "opacity-100 pointer-events-auto" : "opacity-0 pointer-events-none",
        )}
      >
        <div
          className="fixed inset-0 bg-black/60 backdrop-blur-sm"
          onClick={() => onMobileOpenChange(false)}
          aria-hidden="true"
        />
        <div
          className={cn(
            "fixed inset-y-0 left-0 w-[min(88vw,340px)] bg-canvas-raised shadow-2xl transition-transform duration-200",
            mobileOpen ? "translate-x-0" : "-translate-x-full",
          )}
        >
          <SidebarBody
            user={user}
            config={config}
            health={health}
            collapsed={false}
            onNavigate={() => onMobileOpenChange(false)}
            onClose={() => onMobileOpenChange(false)}
          />
        </div>
      </div>
    </>
  );
}
