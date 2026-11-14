import * as React from "react";

import { cn } from "@/lib/utils";

export const Input = React.forwardRef<HTMLInputElement, React.InputHTMLAttributes<HTMLInputElement>>(
  ({ className, type = "text", ...props }, ref) => (
    <input
      ref={ref}
      type={type}
      className={cn(
        "h-11 min-h-[44px] w-full rounded-[var(--r-md)] bg-inset px-3.5 text-sm text-ink shadow-[var(--inner-inset)] outline-none transition-[box-shadow,background-color] duration-[var(--duration-fast)] ease-[var(--ease-out)] placeholder:text-faint hover:bg-surface focus:shadow-[0_0_0_2px_var(--accent)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:cursor-not-allowed disabled:opacity-50",
        className,
      )}
      {...props}
    />
  ),
);
Input.displayName = "Input";

export const Textarea = React.forwardRef<
  HTMLTextAreaElement,
  React.TextareaHTMLAttributes<HTMLTextAreaElement>
>(({ className, ...props }, ref) => (
  <textarea
    ref={ref}
    className={cn(
      "w-full resize-none rounded-[var(--r-lg)] bg-inset px-4 py-3 text-sm leading-relaxed text-ink shadow-[var(--inner-inset)] outline-none transition-[box-shadow,background-color] duration-[var(--duration-fast)] ease-[var(--ease-out)] placeholder:text-faint hover:bg-surface focus:shadow-[0_0_0_2px_var(--accent)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:cursor-not-allowed disabled:opacity-50",
      className,
    )}
    {...props}
  />
));
Textarea.displayName = "Textarea";

export const Label = React.forwardRef<
  HTMLLabelElement,
  React.LabelHTMLAttributes<HTMLLabelElement>
>(({ className, ...props }, ref) => (
  <label
    ref={ref}
    className={cn("text-xs font-medium tracking-[0.01em] text-ink-soft", className)}
    {...props}
  />
));
Label.displayName = "Label";
