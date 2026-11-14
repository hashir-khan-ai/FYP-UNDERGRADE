"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { AnimatePresence, motion } from "framer-motion";
import {
  FileText,
  Layers,
  MessageSquare,
  Plus,
  Search,
  ShieldCheck,
  Sparkles,
} from "lucide-react";

import { useSessions } from "@/components/providers/sessions-provider";
import { canViewAudit } from "@/lib/auth";
import { MOTION_DURATION, MOTION_EASING, MOTION_SPRING } from "@/lib/motion";
import type { SessionSummary } from "@/lib/types";
import { cn } from "@/lib/utils";

export interface CommandPaletteProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  userRole: string;
  onSelectKnowledgeScope?: (scope: string) => void;
  onSelectResponseStyle?: (style: string) => void;
  onSelectAction?: (actionId: string) => void;
}

interface PaletteAction {
  id: string;
  category: "Navigation" | "Actions" | "Sessions" | "Settings";
  title: string;
  subtitle?: string;
  icon: React.ComponentType<{ className?: string }>;
  perform: () => void;
}

export function CommandPalette({
  open,
  onOpenChange,
  userRole,
  onSelectKnowledgeScope,
  onSelectResponseStyle,
  onSelectAction,
}: CommandPaletteProps) {
  const router = useRouter();
  const { sessions, createSession } = useSessions();
  const [search, setSearch] = React.useState("");
  const [selectedIndex, setSelectedIndex] = React.useState(0);
  const inputRef = React.useRef<HTMLInputElement>(null);
  const listRef = React.useRef<HTMLDivElement>(null);

  const role = userRole.toLowerCase();
  const auditAllowed = canViewAudit(role);

  // Build the list of actions. Notice: STRICTLY covers user's own sessions, pages, starter queries, and scopes.
  // NEVER includes any document catalog contents or restricted document metadata!
  const allActions: PaletteAction[] = React.useMemo(() => {
    const list: PaletteAction[] = [];

    // General Actions
    list.push({
      id: "action-new-session",
      category: "Actions",
      title: "New compliance session",
      subtitle: "Start a fresh regulated inquiry",
      icon: Plus,
      perform: () => {
        void createSession();
      },
    });

    // Navigation Pages
    list.push({
      id: "nav-chat",
      category: "Navigation",
      title: "Compliance Chat",
      subtitle: "Regulatory Q&A and policy interpretation",
      icon: MessageSquare,
      perform: () => router.push("/chat"),
    });

    list.push({
      id: "nav-documents",
      category: "Navigation",
      title: "Document Catalog",
      subtitle: "Permitted regulatory sources for your role",
      icon: FileText,
      perform: () => router.push("/documents"),
    });

    if (auditAllowed) {
      list.push({
        id: "nav-audit",
        category: "Navigation",
        title: "Audit & RBAC",
        subtitle: "Audit log and security verification",
        icon: ShieldCheck,
        perform: () => router.push("/audit"),
      });
    }

    // Knowledge Scopes
    if (onSelectKnowledgeScope) {
      const scopes = [
        "All Permitted Regulations",
        "UK FCA / PRA Rules",
        "EU Regulatory Directives",
        "Basel Capital Framework",
      ];
      for (const scope of scopes) {
        list.push({
          id: `scope-${scope}`,
          category: "Settings",
          title: `Set Scope: ${scope}`,
          subtitle: "Target retrieval boundary",
          icon: Layers,
          perform: () => onSelectKnowledgeScope(scope),
        });
      }
    }

    // Response Styles
    if (onSelectResponseStyle) {
      const styles = ["Concise", "Comprehensive", "Bullet Points"];
      for (const style of styles) {
        list.push({
          id: `style-${style}`,
          category: "Settings",
          title: `Set Response Style: ${style}`,
          subtitle: "Adjust generation verbosity",
          icon: Sparkles,
          perform: () => onSelectResponseStyle(style),
        });
      }
    }

    // Sessions (User's own sessions only)
    for (const s of sessions) {
      list.push({
        id: `session-${s.id}`,
        category: "Sessions",
        title: s.title,
        subtitle: `Jump to session (ID: ${s.id.slice(0, 8)})`,
        icon: MessageSquare,
        perform: () => router.push(`/chat/${s.id}`),
      });
    }

    return list;
  }, [sessions, auditAllowed, createSession, router, onSelectKnowledgeScope, onSelectResponseStyle]);

  const filteredActions = React.useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return allActions;
    return allActions.filter(
      (a) =>
        a.title.toLowerCase().includes(q) ||
        (a.subtitle && a.subtitle.toLowerCase().includes(q)),
    );
  }, [allActions, search]);

  React.useEffect(() => {
    if (open) {
      setSearch("");
      setSelectedIndex(0);
      setTimeout(() => inputRef.current?.focus(), 50);
    }
  }, [open]);

  React.useEffect(() => {
    setSelectedIndex(0);
  }, [search]);

  // Keep selected index in view
  React.useEffect(() => {
    if (!listRef.current) return;
    const selectedElement = listRef.current.querySelector(
      `[data-palette-index="${selectedIndex}"]`,
    ) as HTMLElement | null;
    if (selectedElement && typeof selectedElement.scrollIntoView === "function") {
      selectedElement.scrollIntoView({ block: "nearest" });
    }
  }, [selectedIndex]);

  function handleKeyDown(e: React.KeyboardEvent) {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setSelectedIndex((prev) =>
        prev < filteredActions.length - 1 ? prev + 1 : 0,
      );
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setSelectedIndex((prev) =>
        prev > 0 ? prev - 1 : filteredActions.length - 1,
      );
    } else if (e.key === "Enter") {
      e.preventDefault();
      if (filteredActions[selectedIndex]) {
        const chosen = filteredActions[selectedIndex];
        onSelectAction?.(chosen.id);
        chosen.perform();
        onOpenChange(false);
      }
    } else if (e.key === "Escape") {
      e.preventDefault();
      onOpenChange(false);
    }
  }

  return (
    <AnimatePresence>
      {open ? (
        <div
          role="dialog"
          aria-modal="true"
          aria-label="Command palette"
          className="fixed inset-0 z-50 flex items-start justify-center p-4 pt-[10vh] sm:pt-[14vh]"
        >
          {/* Backdrop */}
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: MOTION_DURATION.fast, ease: MOTION_EASING.standard }}
            className="fixed inset-0 bg-black/65 backdrop-blur-sm"
            onClick={() => onOpenChange(false)}
            aria-hidden="true"
          />

          {/* Modal Dialog */}
          <motion.div
            initial={{ opacity: 0, scale: 0.96, y: -8 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.97, y: -4 }}
            transition={MOTION_SPRING.overlay}
            className="relative flex w-full max-w-xl flex-col overflow-hidden rounded-[var(--r-xl)] bg-surface shadow-[var(--elev-3)] focus:outline-none"
            onKeyDown={handleKeyDown}
          >
            {/* Search Input bar */}
            <div className="flex items-center gap-3 border-b border-line px-4 py-3">
              <Search className="size-4 shrink-0 text-faint" aria-hidden="true" />
              <input
                ref={inputRef}
                type="text"
                role="combobox"
                aria-expanded={true}
                aria-controls="palette-results"
                aria-activedescendant={
                  filteredActions[selectedIndex]
                    ? `action-${filteredActions[selectedIndex].id}`
                    : undefined
                }
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Type a command or search sessions…"
                className="min-h-[36px] w-full bg-transparent text-sm text-ink placeholder-faint outline-none"
              />
              <button
                type="button"
                onClick={() => onOpenChange(false)}
                aria-label="Close command palette"
                className="inline-flex min-h-[44px] min-w-[44px] shrink-0 items-center justify-center rounded-[var(--r-xs)] border border-line bg-surface-2 px-2.5 font-mono text-xs font-semibold text-faint transition-colors hover:border-line-strong hover:text-ink"
              >
                ESC
              </button>
            </div>

        {/* Results List */}
        <div
          id="palette-results"
          ref={listRef}
          role="listbox"
          aria-label="Commands and sessions"
          className="max-h-[360px] overflow-y-auto p-2"
        >
          {filteredActions.length === 0 ? (
            <div className="p-6 text-center text-xs text-muted">
              No matching commands or sessions found.
            </div>
          ) : (
            filteredActions.map((action, idx) => {
              const isSelected = idx === selectedIndex;
              const Icon = action.icon;
              return (
                <div
                  key={action.id}
                  id={`action-${action.id}`}
                  role="option"
                  aria-selected={isSelected}
                  data-palette-index={idx}
                  onClick={() => {
                    onSelectAction?.(action.id);
                    action.perform();
                    onOpenChange(false);
                  }}
                  onMouseEnter={() => setSelectedIndex(idx)}
                  className={cn(
                    "flex min-h-[44px] cursor-pointer items-center gap-3 rounded-[var(--r-sm)] px-3.5 py-2.5 text-xs transition-colors",
                    isSelected
                      ? "bg-accent-soft text-ink font-medium ring-1 ring-inset ring-line-accent"
                      : "text-muted hover:bg-surface-2 hover:text-ink",
                  )}
                >
                  <Icon
                    className={cn(
                      "size-4 shrink-0",
                      isSelected ? "text-accent-link" : "text-faint",
                    )}
                  />
                  <div className="min-w-0 flex-1">
                    <div className="truncate font-medium text-ink">{action.title}</div>
                    {action.subtitle ? (
                      <div className="truncate text-xs text-faint">
                        {action.subtitle}
                      </div>
                    ) : null}
                  </div>
                  <span className="shrink-0 font-mono text-xs uppercase tracking-wider text-faint">
                    {action.category}
                  </span>
                </div>
              );
            })
          )}
        </div>

        {/* Footer tip */}
        <div className="flex flex-wrap items-center justify-between gap-2 border-t border-line px-4 py-2.5 text-xs text-faint">
          <span>Use ↑↓ to navigate, Enter to select</span>
          <span>Security: Document content never indexed in palette</span>
        </div>
          </motion.div>
        </div>
      ) : null}
    </AnimatePresence>
  );
}
