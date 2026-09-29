import { Button } from "@/components/ui/button";
import { ErrorState } from "@/components/ui/states";

/** Error state with a "Try again" action (every load failure is recoverable). */
export function Retry({ title, error, onRetry }: { title: string; error: string; onRetry: () => void }) {
  return (
    <ErrorState
      title={title}
      description={error}
      action={
        <Button size="sm" variant="secondary" onClick={onRetry}>
          Try again
        </Button>
      }
    />
  );
}
