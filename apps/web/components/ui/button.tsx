import { forwardRef, type ButtonHTMLAttributes } from "react";

import { cn } from "@/lib/cn";

export type ButtonVariant = "primary" | "vital" | "secondary" | "ghost";
export type ButtonSize = "sm" | "md" | "lg";

const base =
  "inline-flex items-center justify-center gap-2 rounded-pill font-medium select-none " +
  "transition-[transform,background-color,color,border-color,box-shadow] " +
  "duration-(--dur-fast) ease-standard active:scale-[0.98] " +
  "disabled:pointer-events-none disabled:opacity-45";

const variants: Record<ButtonVariant, string> = {
  primary: "bg-ink text-surface hover:bg-ink/88 shadow-1",
  vital: "bg-vital text-on-vital hover:bg-vital-strong shadow-1",
  secondary: "border border-line-strong bg-surface-raised text-ink hover:border-ink/40",
  ghost: "text-ink-muted hover:text-ink hover:bg-surface-sunken",
};

const sizes: Record<ButtonSize, string> = {
  sm: "h-8 px-3.5 text-sm",
  md: "h-10 px-5 text-sm",
  lg: "h-12 px-6 text-base",
};

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = "primary", size = "md", className, type = "button", ...props },
  ref,
) {
  return (
    <button
      ref={ref}
      type={type}
      data-variant={variant}
      className={cn(base, variants[variant], sizes[size], className)}
      {...props}
    />
  );
});
