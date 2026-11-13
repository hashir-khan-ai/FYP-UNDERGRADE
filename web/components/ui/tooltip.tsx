"use client";

import type * as React from "react";
import * as TooltipPrimitive from "@radix-ui/react-tooltip";

import { cn } from "@/lib/utils";

export const TooltipProvider = TooltipPrimitive.Provider;
export const Tooltip = TooltipPrimitive.Root;
export const TooltipTrigger = TooltipPrimitive.Trigger;

export function TooltipContent({
  className,
  sideOffset = 8,
  ...props
}: React.ComponentProps<typeof TooltipPrimitive.Content>) {
  return (
    <TooltipPrimitive.Portal>
      <TooltipPrimitive.Content
        sideOffset={sideOffset}
        className={cn(
          "z-50 max-w-64 rounded-[var(--r-sm)] border border-line-strong bg-canvas-raised px-2.5 py-1.5 text-[0.6875rem] leading-relaxed text-ink-soft shadow-[var(--elev-md)]",
          "data-[state=delayed-open]:animate-enter",
          className,
        )}
        {...props}
      />
    </TooltipPrimitive.Portal>
  );
}
