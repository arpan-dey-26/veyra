import { ApiStatus } from "@/components/system/api-status";

export function SiteFooter() {
  return (
    <footer className="border-t border-line">
      <div className="mx-auto flex max-w-(--layout-max) flex-col gap-4 px-(--gutter) py-8 sm:flex-row sm:items-center sm:justify-between">
        <ApiStatus />
        <p className="text-xs text-ink-subtle">
          VEYRA is a prototype, not a certified medical system.
        </p>
      </div>
    </footer>
  );
}
