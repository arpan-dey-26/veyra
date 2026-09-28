import { cn } from "@/lib/cn";

/**
 * VEYRA wordmark: a drop-shaped mark built from a single continuous "vein" stroke, meeting
 * a node (the network). Original mark, drawn inline so it themes with tokens.
 */
export function Wordmark({ className, withTagline = false }: { className?: string; withTagline?: boolean }) {
  return (
    <span className={cn("inline-flex items-center gap-2.5", className)}>
      <svg aria-hidden viewBox="0 0 24 24" className="size-6" fill="none">
        <path
          d="M12 2.5C12 2.5 5 10.2 5 14.6A7 7 0 0 0 19 14.6C19 10.2 12 2.5 12 2.5Z"
          stroke="var(--color-vital)"
          strokeWidth="1.7"
          strokeLinejoin="round"
        />
        <path
          d="M8.6 15.2c1.4-2.2 3.2-1 4.4-2.6"
          stroke="var(--color-vital)"
          strokeWidth="1.5"
          strokeLinecap="round"
        />
        <circle cx="13.9" cy="12.1" r="1.45" fill="var(--color-vital)" />
      </svg>
      <span className="flex flex-col leading-none">
        <span className="text-[1.05rem] font-semibold tracking-[0.18em] text-ink">VEYRA</span>
        {withTagline && (
          <span className="mt-1 text-2xs tracking-(--tracking-label) text-ink-subtle uppercase">
            Intelligent Blood Network
          </span>
        )}
      </span>
    </span>
  );
}
