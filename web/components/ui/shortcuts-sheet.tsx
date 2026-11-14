"use client";

import * as React from "react";
import { Keyboard } from "lucide-react";

import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { SHORTCUT_REGISTRY } from "@/lib/shortcuts";

interface ShortcutsSheetProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function ShortcutsSheet({ open, onOpenChange }: ShortcutsSheetProps) {
  const categories = ["General", "Navigation", "Chat"] as const;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <div className="flex items-center gap-2">
            <Keyboard className="size-4 text-accent" aria-hidden="true" />
            <DialogTitle>Keyboard shortcuts</DialogTitle>
          </div>
          <DialogDescription>
            Quick navigation and command shortcuts across the compliance workspace.
          </DialogDescription>
        </DialogHeader>

        <DialogBody className="space-y-4 pt-2">
          {categories.map((cat) => {
            const items = SHORTCUT_REGISTRY.filter((s) => s.category === cat);
            if (items.length === 0) return null;

            return (
              <div key={cat} className="space-y-2">
                <h4 className="text-xs font-semibold uppercase tracking-[0.08em] text-faint">
                  {cat}
                </h4>
                <div className="space-y-1.5 rounded-[var(--r-md)] bg-canvas-raised p-2.5 shadow-[var(--inner-inset)]">
                  {items.map((shortcut) => (
                    <div
                      key={shortcut.id}
                      className="flex items-center justify-between px-2 py-1.5 text-xs"
                    >
                      <span className="text-muted">{shortcut.label}</span>
                      <div className="flex items-center gap-1.5">
                        {shortcut.displayKeys.map((k, i) => (
                          <kbd
                            key={i}
                            className="kbd"
                          >
                            {k}
                          </kbd>
                        ))}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            );
          })}
        </DialogBody>
      </DialogContent>
    </Dialog>
  );
}

