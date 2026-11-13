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
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { useSessions } from "@/components/providers/sessions-provider";
import { canViewAudit, roleLabel, roleScope } from "@/lib/auth";
import { api } from "@/lib/api-client";
import { formatRelative } from "@/lib/format";
import type { AdminConfig, HealthResponse, SessionSummary, UserProfile } from "@/lib/types";
import { cn } from "@/lib/utils";

interface SidebarProps {
  user: UserProfile;
  config: AdminConfig | null;
  health: HealthResponse | null;
  mobileOpen: boolean;
  onMobileOpenChange: (open: boolean) => void;
}

function NavItem({
  href,
  label,
  icon: Icon,
  active,
  disabled,
  hint,
  onNavigate,
}: {
  href: string;
  label: string;
  icon: LucideIcon;
  active: boolean;
  disabled?: boolean;
  hint?: string;
  onNavigate?: () => void;
}) {
  if (disabled) {
    return (
      <div
        aria-disabled="true"
        title={hint}
        className="flex h-9 items-center gap-2.5 rounded-[var(--r-sm)] px-2.5 text-xs font-medium text-faint/70"
      >
        <Icon className="size-4" aria-hidden="true" />
        <span className="flex-1">{label}</span>
        <Lock className="size-3" aria-hidden="true" />
      </div>
    );
  }

  return (
    <Link
      href={href}
      onClick={onNavigate}
      aria-current={active ? "page" : undefined}
      className={cn(
        "flex h-9 items-center gap-2.5 rounded-[var(--r-sm)] px-2.5 text-xs font-medium transition-colors duration-[var(--duration-fast)]",
        active
          ? "bg-surface-2 text-ink shadow-[inset_0_1px_0_rgba(255,255,255,0.035)]"
          : "text-muted hover:bg-surface-2/70 hover:text-ink",
      )}
    >
      <Icon className={cn("size-4", active ? "text-accent" : "text-faint")} aria-hidden="true" />
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
    const ok = await deleteSession(session.id);
    if (ok) {
      setDeleteOpen(false);
      toast.success("Session deleted");
      if (active && sessions.length <= 1) router.push("/chat");
    }
  }

  if (renaming) {
    return (
      <div className="rounded-[var(--r-sm)] border border-line-accent bg-surface-2 p-1.5">
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
          className="h-8 text-xs"
          aria-label={`Rename ${session.title}`}
        />
        <div className="mt-1.5 flex justify-end gap-1">
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
        "group relative flex items-center rounded-[var(--r-sm)] transition-colors",
        active ? "bg-surface-2" : "hover:bg-surface-2/60",
      )}
    >
      <Link
        href={`/chat/${session.id}`}
        onClick={onNavigate}
        aria-current={active ? "page" : undefined}
        className="min-w-0 flex-1 py-2 pl-2.5 pr-1"
      >
        <span
          className={cn(
            "block truncate text-xs font-medium",
            active ? "text-ink" : "text-ink-soft group-hover:text-ink",
          )}
        >
          {session.title}
        </span>
        <span className="mt-0.5 block truncate text-[0.625rem] text-faint">
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

      <Dialog open={deleteOpen} onOpenChange={setDeleteOpen}>
        <DialogContent className="max-w-sm">
          <DialogHeader>
            <DialogTitle>Delete this session?</DialogTitle>
            <DialogDescription>
              &ldquo;{session.title}&rdquo; and its conversation history will be removed. This
              cannot be undone.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setDeleteOpen(false)}>
              Cancel
            </Button>
            <Button variant="danger" onClick={() => void confirmDelete()}>
              <Trash2 /> Delete session
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

function SidebarBody({
  user,
  config,
  health,
  onNavigate,
  onClose,
}: {
  user: UserProfile;
  config: AdminConfig | null;
  health: HealthResponse | null;
  onNavigate?: () => void;
  onClose?: () => void;
}) {
  const pathname = usePathname();
  const router = useRouter();
  const { sessions, createSession, creating } = useSessions();
  const [query, setQuery] = React.useState("");
  const [signingOut, setSigningOut] = React.useState(false);

  const role = String(user.role ?? "").toLowerCase();
  const auditAllowed = canViewAudit(role);
  const filtered = React.useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return sessions;
    return sessions.filter((session) => session.title.toLowerCase().includes(needle));
  }, [query, sessions]);

  async function handleSignOut() {
    setSigningOut(true);
    try {
      await api.logout();
    } catch {
      // Clearing the local cookie happens in the BFF even if the API is offline.
    }
    router.replace("/login");
    router.refresh();
  }

  return (
    <div className="flex h-full min-h-0 flex-col bg-canvas-raised/60">
      <div className="flex items-center gap-2 px-4 pb-1 pt-4">
        <Logo showWordmark className="min-w-0 flex-1" />
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

      <div className="px-3 pt-4">
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

      <nav aria-label="Workspace" className="mt-4 space-y-0.5 px-3">
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

      <div className="mt-5 flex items-center justify-between px-4">
        <span className="text-[0.625rem] font-semibold uppercase tracking-[0.1em] text-faint">
          Sessions
        </span>
        <span className="tabular text-[0.625rem] text-faint">{sessions.length}</span>
      </div>

      <div className="px-3 pt-2">
        <div className="relative">
          <Search
            className="pointer-events-none absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-faint"
            aria-hidden="true"
          />
          <Input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Search sessions"
            aria-label="Search sessions"
            className="h-8 pl-8 text-xs"
          />
        </div>
      </div>

      <div className="mt-2 min-h-0 flex-1 overflow-y-auto px-2 pb-3">
        {filtered.length === 0 ? (
          <div className="mx-2 mt-3 rounded-[var(--r-sm)] border border-dashed border-line px-3 py-4 text-center">
            <p className="text-xs font-medium text-ink-soft">
              {sessions.length === 0 ? "No sessions yet" : "No matching sessions"}
            </p>
            <p className="mt-1 text-[0.6875rem] leading-relaxed text-faint">
              {sessions.length === 0
                ? "Create one to start a compliance conversation."
                : "Try a shorter search term."}
            </p>
          </div>
        ) : (
          <div className="space-y-0.5">
            {filtered.map((session) => (
              <SessionRow
                key={session.id}
                session={session}
                active={pathname === `/chat/${session.id}`}
                onNavigate={onNavigate}
              />
            ))}
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
        <p className="mb-2.5 text-[0.625rem] leading-relaxed text-faint">{roleScope(role)}</p>

        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <button
              type="button"
              className="flex w-full items-center gap-2.5 rounded-[var(--r-sm)] border border-line bg-surface-2/60 p-2 text-left transition-colors hover:border-line-strong hover:bg-surface-2 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
              aria-label="Account menu"
            >
              <Avatar name={user.full_name} size="sm" />
              <span className="min-w-0 flex-1">
                <span className="block truncate text-xs font-medium text-ink">
                  {user.full_name}
                </span>
                <span className="block truncate text-[0.625rem] text-faint">
                  @{user.username} · {roleLabel(role)}
                </span>
              </span>
              <MoreHorizontal className="size-3.5 text-faint" aria-hidden="true" />
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

export function Sidebar({ user, config, health, mobileOpen, onMobileOpenChange }: SidebarProps) {
  return (
    <>
      <aside className="fixed inset-y-0 left-0 z-30 hidden w-[var(--sidebar-width)] border-r border-line lg:block">
        <SidebarBody user={user} config={config} health={health} />
      </aside>

      <Dialog open={mobileOpen} onOpenChange={onMobileOpenChange}>
        <DialogContent
          showClose={false}
          className="fixed left-0 top-0 h-dvh max-h-none w-[min(88vw,340px)] max-w-none translate-x-0 translate-y-0 rounded-none border-y-0 border-l-0 bg-canvas-raised p-0"
          aria-label="Workspace navigation"
        >
          <DialogTitle className="sr-only">Workspace navigation</DialogTitle>
          <DialogDescription className="sr-only">
            Sessions, workspace views and account controls.
          </DialogDescription>
          <DialogBody className="h-full p-0">
            <SidebarBody
              user={user}
              config={config}
              health={health}
              onNavigate={() => onMobileOpenChange(false)}
              onClose={() => onMobileOpenChange(false)}
            />
          </DialogBody>
        </DialogContent>
      </Dialog>
    </>
  );
}
