import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";

import { cn } from "@/lib/utils";

const badgeVariants = cva(
  "inline-flex h-7 items-center gap-1.5 whitespace-nowrap rounded-full px-3 text-xs font-medium leading-none tracking-[0.01em] ring-1 ring-inset [&_svg]:size-3.5",
  {
    variants: {
      tone: {
        neutral: "bg-surface-2 text-muted ring-line",
        accent: "bg-accent-soft text-accent-link ring-line-accent",
        success: "bg-success-soft text-success ring-success/25",
        warning: "bg-warning-soft text-warning ring-warning/25",
        danger: "bg-danger-soft text-danger ring-danger/28",
        info: "bg-info-soft text-info ring-info/25",
        nonGrounded:
          "bg-nongrounded-soft text-nongrounded ring-nongrounded/25",
        outline: "bg-surface text-ink-soft ring-line-strong",
      },
    },
    defaultVariants: { tone: "neutral" },
  },
);

export interface BadgeProps
  extends React.HTMLAttributes<HTMLSpanElement>,
    VariantProps<typeof badgeVariants> {}

export function Badge({ className, tone, ...props }: BadgeProps) {
  return <span className={cn(badgeVariants({ tone }), className)} {...props} />;
}

export { badgeVariants };
