import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";

import { cn } from "@/lib/utils";

const badgeVariants = cva(
  "inline-flex items-center gap-1.5 whitespace-nowrap rounded-full border px-2.5 py-0.5 text-xs font-medium leading-5 tracking-[0.01em] [&_svg]:size-3.5",
  {
    variants: {
      tone: {
        neutral: "border-line bg-surface-2 text-muted",
        accent: "border-[rgba(120,169,255,0.3)] bg-accent-soft text-accent",
        success: "border-[rgba(86,217,155,0.28)] bg-success-soft text-success",
        warning: "border-[rgba(240,195,106,0.28)] bg-warning-soft text-warning",
        danger: "border-[rgba(255,133,133,0.3)] bg-danger-soft text-danger",
        info: "border-[rgba(131,201,255,0.28)] bg-info-soft text-info",
        nonGrounded:
          "border-[rgba(193,168,255,0.3)] bg-nongrounded-soft text-nongrounded",
        outline: "border-line-strong bg-transparent text-ink-soft",
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
