import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";

import { cn } from "@/lib/utils";

const buttonVariants = cva(
  "inline-flex select-none items-center justify-center gap-2 whitespace-nowrap rounded-[var(--r-sm)] font-medium transition-[background-color,border-color,color,box-shadow,transform] duration-[var(--duration-fast)] ease-[var(--ease-out)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:pointer-events-none disabled:opacity-45 active:translate-y-px [&_svg]:shrink-0",
  {
    variants: {
      variant: {
        primary:
          "bg-accent text-accent-ink shadow-[var(--elev-accent)] hover:bg-accent-strong",
        secondary:
          "border border-line bg-surface-2 text-ink shadow-[var(--elev-sm)] hover:border-line-strong hover:bg-surface-3",
        outline:
          "border border-line-strong bg-transparent text-ink hover:border-line-accent hover:bg-surface-2",
        ghost: "text-muted hover:bg-surface-2 hover:text-ink",
        soft: "bg-accent-soft text-accent hover:bg-[rgba(120,169,255,0.18)]",
        danger:
          "border border-[rgba(255,133,133,0.32)] bg-danger-soft text-danger hover:bg-[rgba(255,133,133,0.16)]",
      },
      size: {
        sm: "h-8 px-3 text-xs [&_svg]:size-3.5",
        md: "h-9.5 px-4 text-[0.8125rem] [&_svg]:size-4",
        lg: "h-11 px-5 text-sm [&_svg]:size-4",
        icon: "size-9 [&_svg]:size-4",
        "icon-sm": "size-7 [&_svg]:size-3.5",
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
