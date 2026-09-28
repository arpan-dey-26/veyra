import { Badge } from "@/components/ui/badge";

export interface SimulatedBadgeProps {
  /** What is simulated, e.g. "IoT sensor", "Blood bank", "Local demo chain". */
  subject?: string;
  label?: "Simulated" | "Demo" | "Synthetic data";
}

/**
 * The mandatory label for any simulated/demo/synthetic data (frozen UI contract).
 * Render it wherever the API returns `source.simulated === true`.
 */
export function SimulatedBadge({ subject, label = "Simulated" }: SimulatedBadgeProps) {
  const description = subject
    ? `${subject}: ${label.toLowerCase()} for this prototype, not a real-world integration`
    : `${label} for this prototype, not a real-world integration`;
  return (
    <Badge tone="simulated" title={description} aria-label={description}>
      <svg aria-hidden viewBox="0 0 12 12" className="size-3" fill="none">
        <path d="M6 1.5v9M1.5 6h9" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
        <circle cx="6" cy="6" r="4.5" stroke="currentColor" strokeWidth="1" strokeDasharray="2 2" />
      </svg>
      {label}
    </Badge>
  );
}
