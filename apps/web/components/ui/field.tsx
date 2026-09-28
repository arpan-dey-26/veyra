"use client";

import {
  forwardRef,
  useId,
  useState,
  type InputHTMLAttributes,
  type ReactNode,
  type SelectHTMLAttributes,
} from "react";

import { cn } from "@/lib/cn";

const control =
  "h-11 w-full rounded-md border bg-surface-raised px-3.5 text-[0.95rem] text-ink " +
  "placeholder:text-ink-subtle outline-none transition-[border-color,box-shadow] " +
  "duration-(--dur-fast) ease-standard " +
  "focus-visible:border-ink/50 focus-visible:shadow-[0_0_0_3px_var(--color-surface-sunken)] " +
  "disabled:opacity-60";

export interface FieldProps {
  label: string;
  hint?: ReactNode;
  error?: string | null;
  children: (props: {
    id: string;
    "aria-invalid": boolean;
    "aria-describedby": string | undefined;
  }) => ReactNode;
  className?: string;
}

/** Label + control + hint/error, wired for screen readers. */
export function Field({ label, hint, error, children, className }: FieldProps) {
  const id = useId();
  const hintId = hint ? `${id}-hint` : undefined;
  const errorId = error ? `${id}-error` : undefined;
  const describedBy = [errorId, hintId].filter(Boolean).join(" ") || undefined;
  return (
    <div className={cn("flex flex-col gap-1.5", className)}>
      <label htmlFor={id} className="text-sm font-medium text-ink">
        {label}
      </label>
      {children({ id, "aria-invalid": Boolean(error), "aria-describedby": describedBy })}
      {error ? (
        <p id={errorId} role="alert" className="text-xs font-medium text-critical">
          {error}
        </p>
      ) : hint ? (
        <p id={hintId} className="text-xs text-ink-subtle">
          {hint}
        </p>
      ) : null}
    </div>
  );
}

export const TextInput = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(
  function TextInput({ className, ...props }, ref) {
    return (
      <input
        ref={ref}
        className={cn(
          control,
          props["aria-invalid"] ? "border-critical" : "border-line-strong",
          className,
        )}
        {...props}
      />
    );
  },
);

export const SelectInput = forwardRef<HTMLSelectElement, SelectHTMLAttributes<HTMLSelectElement>>(
  function SelectInput({ className, children, ...props }, ref) {
    return (
      <select
        ref={ref}
        className={cn(
          control,
          "appearance-none bg-[length:16px] bg-[right_0.9rem_center] bg-no-repeat pr-10",
          props["aria-invalid"] ? "border-critical" : "border-line-strong",
          className,
        )}
        style={{
          backgroundImage:
            "url(\"data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16' fill='none' stroke='%237a716d' stroke-width='1.6'%3E%3Cpath d='M4 6l4 4 4-4'/%3E%3C/svg%3E\")",
        }}
        {...props}
      >
        {children}
      </select>
    );
  },
);

export const PasswordInput = forwardRef<
  HTMLInputElement,
  Omit<InputHTMLAttributes<HTMLInputElement>, "type">
>(function PasswordInput(props, ref) {
  const [visible, setVisible] = useState(false);
  return (
    <div className="relative">
      <TextInput ref={ref} type={visible ? "text" : "password"} className="pr-20" {...props} />
      <button
        type="button"
        onClick={() => setVisible((v) => !v)}
        aria-pressed={visible}
        aria-label={visible ? "Hide password" : "Show password"}
        className="absolute top-1/2 right-2 -translate-y-1/2 rounded-sm px-2 py-1 text-xs font-medium text-ink-muted hover:text-ink"
      >
        {visible ? "Hide" : "Show"}
      </button>
    </div>
  );
});

export function Spinner({ className }: { className?: string }) {
  return (
    <svg
      aria-hidden
      viewBox="0 0 24 24"
      className={cn("veyra-spin size-4", className)}
      fill="none"
      stroke="currentColor"
      strokeWidth="2.4"
    >
      <circle cx="12" cy="12" r="9" opacity="0.25" />
      <path d="M21 12a9 9 0 0 0-9-9" strokeLinecap="round" />
    </svg>
  );
}

export function InlineAlert({
  tone = "error",
  title,
  children,
}: {
  tone?: "error" | "demo" | "info" | "success";
  title?: string;
  children: ReactNode;
}) {
  const styles = {
    error: "bg-critical-soft text-critical",
    demo: "bg-simulated-soft text-simulated",
    info: "bg-surface-sunken text-ink-muted",
    success: "bg-verified-soft text-verified",
  }[tone];
  return (
    <div
      role={tone === "error" ? "alert" : "status"}
      className={cn("rounded-md px-4 py-3 text-sm", styles)}
    >
      {title && <p className="font-semibold">{title}</p>}
      <div className={cn(title && "mt-0.5")}>{children}</div>
    </div>
  );
}
