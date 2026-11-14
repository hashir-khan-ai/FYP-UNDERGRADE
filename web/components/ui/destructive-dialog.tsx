"use client";

import * as React from "react";
import { AlertTriangle, Trash2 } from "lucide-react";

import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

export interface DestructiveDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description: string;
  confirmLabel?: string;
  onConfirm: () => void | Promise<void>;
  /**
   * If provided, Mode 2 is activated: the user must type this exact string
   * before the destructive confirm button becomes enabled.
   */
  matchString?: string;
  isLoading?: boolean;
}

export function DestructiveDialog({
  open,
  onOpenChange,
  title,
  description,
  confirmLabel = "Delete",
  onConfirm,
  matchString,
  isLoading = false,
}: DestructiveDialogProps) {
  const [typedInput, setTypedInput] = React.useState("");
  const inputRef = React.useRef<HTMLInputElement>(null);
  const previouslyFocusedElement = React.useRef<HTMLElement | null>(null);

  // Capture previously focused element when opened so focus returns when closed
  React.useEffect(() => {
    if (open) {
      previouslyFocusedElement.current = document.activeElement as HTMLElement | null;
      setTypedInput("");
      if (matchString) {
        setTimeout(() => inputRef.current?.focus(), 50);
      }
    } else {
      if (previouslyFocusedElement.current && previouslyFocusedElement.current.focus) {
        previouslyFocusedElement.current.focus();
      }
    }
  }, [open, matchString]);

  const isMatched = matchString ? typedInput.trim() === matchString.trim() : true;

  async function handleConfirm() {
    if (!isMatched || isLoading) return;
    await onConfirm();
    onOpenChange(false);
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <div className="flex items-center gap-2 text-danger">
            <AlertTriangle className="size-5 shrink-0" aria-hidden="true" />
            <DialogTitle className="text-ink">{title}</DialogTitle>
          </div>
          <DialogDescription className="text-muted text-xs leading-relaxed">
            {description}
          </DialogDescription>
        </DialogHeader>

        {matchString ? (
          <DialogBody className="space-y-3 pt-2">
            <p className="text-xs text-ink-soft">
              Please type <span className="font-mono font-semibold text-ink select-all">{matchString}</span> to confirm:
            </p>
            <Input
              ref={inputRef}
              value={typedInput}
              onChange={(e) => setTypedInput(e.target.value)}
              placeholder={matchString}
              aria-label={`Type ${matchString} to confirm`}
              className="font-mono text-xs"
              onKeyDown={(e) => {
                if (e.key === "Enter" && isMatched && !isLoading) {
                  e.preventDefault();
                  void handleConfirm();
                }
              }}
            />
          </DialogBody>
        ) : null}

        <DialogFooter className="mt-4 gap-2">
          <Button
            variant="ghost"
            onClick={() => onOpenChange(false)}
            disabled={isLoading}
          >
            Cancel
          </Button>
          <Button
            variant="danger"
            onClick={() => void handleConfirm()}
            disabled={!isMatched || isLoading}
            aria-disabled={!isMatched || isLoading}
          >
            <Trash2 className="size-4" aria-hidden="true" />
            {isLoading ? "Deleting..." : confirmLabel}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

