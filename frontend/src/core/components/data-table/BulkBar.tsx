"use client";

/**
 * What is selected, and the escalation to "every row matching" (FRONTEND_PLATFORM § 12). Actions
 * are the caller's; each one sends bulkTarget(selection, query) so the server re-runs the list's
 * own query in query mode. Results report what was skipped (§ 11).
 */
import type { ReactNode } from "react";

import { useT } from "@/core/lib/i18n";

import { Button } from "../Button";
import { EMPTY_SELECTION, pageState, selectAllMatching, selectedCount, type Selection } from "./selection";

export function BulkBar({
  selection,
  onChange,
  total,
  pageIds,
  noun,
  children,
}: {
  selection: Selection;
  onChange: (next: Selection) => void;
  total: number;
  pageIds: readonly string[];
  /** Plural noun, already translated ("users"); "rows" when omitted. */
  noun?: string;
  /** Bulk actions. */
  children?: ReactNode;
}) {
  const t = useT("dataTable");
  const count = selectedCount(selection, total);
  if (count === 0) return null;
  const canEscalate = selection.mode === "ids" && pageState(selection, pageIds) === "all" && total > pageIds.length;
  return (
    <div role="region" aria-label={t("bulk.region")} className="flex flex-wrap items-center gap-3 rounded-md border border-border bg-accent px-3 py-2 text-sm text-accent-foreground">
      <span className="font-medium">
        {selection.mode === "query" && selection.excludeIds.size === 0
          ? t("bulk.allMatchingSelected", { total, noun: noun ?? t("rows") })
          : t("bulk.selected", { count })}
      </span>
      {canEscalate ? (
        <Button variant="link" onClick={() => onChange(selectAllMatching())}>
          {t("bulk.selectAllMatching", { total })}
        </Button>
      ) : null}
      <Button variant="link" onClick={() => onChange(EMPTY_SELECTION)}>
        {t("bulk.clear")}
      </Button>
      {children ? <div className="ms-auto flex gap-2">{children}</div> : null}
    </div>
  );
}
