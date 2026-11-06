"use client";

/**
 * What is selected, and the escalation to "every row matching" (FRONTEND_PLATFORM § 12). Actions
 * are the caller's; each one sends bulkTarget(selection, query) so the server re-runs the list's
 * own query in query mode. Results report what was skipped (§ 11).
 */
import type { ReactNode } from "react";

import { Button } from "../Button";
import { EMPTY_SELECTION, pageState, selectAllMatching, selectedCount, type Selection } from "./selection";

export function BulkBar({
  selection,
  onChange,
  total,
  pageIds,
  noun = "rows",
  children,
}: {
  selection: Selection;
  onChange: (next: Selection) => void;
  total: number;
  pageIds: readonly string[];
  noun?: string;
  /** Bulk actions. */
  children?: ReactNode;
}) {
  const count = selectedCount(selection, total);
  if (count === 0) return null;
  const canEscalate = selection.mode === "ids" && pageState(selection, pageIds) === "all" && total > pageIds.length;
  return (
    <div role="region" aria-label="Selection" className="flex flex-wrap items-center gap-3 rounded-md border border-border bg-accent px-3 py-2 text-sm text-accent-foreground">
      <span className="font-medium">
        {selection.mode === "query" && selection.excludeIds.size === 0 ? `All ${total} matching ${noun} selected` : `${count} selected`}
      </span>
      {canEscalate ? (
        <Button variant="link" onClick={() => onChange(selectAllMatching())}>
          Select all {total} matching
        </Button>
      ) : null}
      <Button variant="link" onClick={() => onChange(EMPTY_SELECTION)}>
        Clear selection
      </Button>
      {children ? <div className="ml-auto flex gap-2">{children}</div> : null}
    </div>
  );
}
