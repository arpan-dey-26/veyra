import { SimulatedBadge } from "@/components/ui/simulated-badge";
import { DEMO_VERIFICATION_DISCLAIMER } from "@/lib/validation";

/** Mandatory, always-visible notice wherever demo phone verification is used. */
export function DemoVerificationNotice({ compact = false }: { compact?: boolean }) {
  return (
    <div
      role="note"
      aria-label="Demo verification notice"
      className="flex items-start gap-3 rounded-md border border-simulated/25 bg-simulated-soft px-4 py-3"
    >
      <SimulatedBadge label="Demo" subject="Phone verification" />
      <p className={compact ? "text-xs text-simulated" : "text-sm text-simulated"}>
        {DEMO_VERIFICATION_DISCLAIMER}
      </p>
    </div>
  );
}
