import * as React from "react";

import { cn } from "@/lib/utils";

export const Input = React.forwardRef<HTMLInputElement, React.InputHTMLAttributes<HTMLInputElement>>(
  ({ className, type = "text", ...props }, ref) => (
    <input
      ref={ref}
      type={type}
      className={cn(
        "h-10 w-full rounded-[var(--r-sm)] border border-line bg-[rgba(3,6,10,0.44)] px-3 text-sm text-ink shadow-[inset_0_1px_0_rgba(255,255,255,0.02)] outline-none transition-[border-color,box-shadow] duration-[var(--duration-fast)] placeholder:text-faint hover:border-line-strong focus:border-line-accent focus:shadow-[0_0_0_3px_rgba(120,169,255,0.12)] disabled:cursor-not-allowed disabled:opacity-50",
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
      "w-full resize-none rounded-[var(--r-md)] border border-line bg-[rgba(3,6,10,0.34)] px-3.5 py-3 text-sm leading-relaxed text-ink outline-none transition-[border-color,box-shadow] duration-[var(--duration-fast)] placeholder:text-faint hover:border-line-strong focus:border-line-accent focus:shadow-[0_0_0_3px_rgba(120,169,255,0.1)] disabled:cursor-not-allowed disabled:opacity-50",
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
