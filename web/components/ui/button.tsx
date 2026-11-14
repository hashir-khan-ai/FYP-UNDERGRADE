import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";

import { cn } from "@/lib/utils";

const buttonVariants = cva(
  "inline-flex select-none items-center justify-center gap-2 whitespace-nowrap font-medium transition-[background-color,color,box-shadow,transform] duration-[var(--duration-base)] ease-[var(--ease-out)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:pointer-events-none disabled:opacity-45 active:translate-y-px [&_svg]:shrink-0",
  {
    variants: {
      variant: {
        primary:
          "bg-accent text-accent-ink shadow-[var(--elev-accent)] hover:bg-accent-strong",
        secondary:
          "bg-surface text-ink shadow-[var(--elev-1)] hover:bg-surface-2",
        outline:
          "bg-surface-2/60 text-ink ring-1 ring-inset ring-line-strong hover:bg-surface-2",
        ghost: "text-muted hover:bg-surface-2/80 hover:text-ink",
        soft: "bg-accent-soft text-accent-link hover:bg-[var(--accent-soft-hover)]",
        danger:
          "bg-danger-soft text-danger ring-1 ring-inset ring-danger/30 hover:bg-danger/20",
      },
      size: {
        sm: "h-10 min-h-[40px] min-w-[40px] rounded-[var(--r-sm)] px-3.5 text-xs [&_svg]:size-4",
        md: "h-11 min-h-[44px] min-w-[44px] rounded-[var(--r-md)] px-4 text-sm [&_svg]:size-4",
        lg: "h-12 min-h-[48px] min-w-[48px] rounded-[var(--r-md)] px-5 text-base [&_svg]:size-5",
        icon: "size-11 min-h-[44px] min-w-[44px] rounded-[var(--r-md)] p-0 [&_svg]:size-4.5",
        "icon-sm": "size-10 min-h-[40px] min-w-[40px] rounded-[var(--r-sm)] p-0 [&_svg]:size-4",
      },
    },
    defaultVariants: {
      variant: "secondary",
      size: "md",
    },
  },
);

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {
  asChild?: boolean;
}

/**
 * Server-safe button. `asChild` deliberately avoids a context-based Slot so
 * this module can be imported by both Server and Client Components.
 */
export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, asChild = false, type, children, ...props }, ref) => {
    const classes = cn(buttonVariants({ variant, size }), className);

    if (asChild) {
      const child = React.Children.only(children) as React.ReactElement<{
        className?: string;
      }>;
      return React.cloneElement(child, {
        ...props,
        ref,
        className: cn(classes, child.props.className),
      } as React.Attributes & { className?: string; ref?: React.Ref<HTMLButtonElement> });
    }

    return (
      <button ref={ref} type={type ?? "button"} className={classes} {...props}>
        {children}
      </button>
    );
  },
);
Button.displayName = "Button";

export { buttonVariants };
