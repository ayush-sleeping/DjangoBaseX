import type { ReactNode } from "react";

/**
 * An honest empty list (FRONTEND_PLATFORM § 11). `none`: nothing exists yet (offer to create, if
 * permitted). `filtered`: filters hid everything (offer to clear them). A FAILED load is never this
 * — it is ListLoadError.
 */
export function EmptyState({
  variant,
  title,
  body,
  action,
}: {
  variant: "none" | "filtered";
  title: string;
  body?: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div role="status" data-empty={variant} className="flex flex-col items-center gap-2 rounded-lg border border-dashed border-border p-8 text-center">
      <p className="text-sm font-medium">{title}</p>
      {body ? <p className="text-sm text-muted-foreground">{body}</p> : null}
      {action}
    </div>
  );
}
