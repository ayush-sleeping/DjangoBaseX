"use client";

/**
 * The pager (FRONTEND_PLATFORM § 11, § 12). The row count lives here and nowhere else. Pages are
 * truncated around the current one: 1 … 4 5 6 … 20.
 */
import { ChevronLeft, ChevronRight } from "lucide-react";

import { list as listDefaults } from "@/core/lib/config/defaults";

import { IconButton } from "../Button";

export function pageWindow(page: number, pages: number): (number | "gap")[] {
  if (pages <= 7) return Array.from({ length: pages }, (_, i) => i + 1);
  const wanted = new Set([1, pages, page - 1, page, page + 1].filter((p) => p >= 1 && p <= pages));
  const sorted = [...wanted].sort((a, b) => a - b);
  const out: (number | "gap")[] = [];
  for (const p of sorted) {
    const last = out[out.length - 1];
    if (typeof last === "number" && p - last > 1) out.push(p - last === 2 ? last + 1 : "gap");
    out.push(p);
  }
  return out;
}

export function Pager({
  page,
  count,
  onPage,
  pageSize = listDefaults.pageSize,
  noun = "rows",
  disabled = false,
}: {
  page: number;
  count: number;
  onPage: (page: number) => void;
  pageSize?: number;
  /** Plural noun for the count: "users", "orders". */
  noun?: string;
  disabled?: boolean;
}) {
  const pages = Math.max(1, Math.ceil(count / pageSize));
  const from = count === 0 ? 0 : (page - 1) * pageSize + 1;
  const to = Math.min(count, page * pageSize);
  return (
    <nav aria-label="Pagination" className="flex flex-wrap items-center justify-between gap-2 text-sm text-muted-foreground">
      <p aria-live="polite">
        {count === 0 ? `0 ${noun}` : `${from}–${to} of ${count} ${noun}`}
      </p>
      {pages > 1 ? (
        <div className="flex items-center gap-1">
          <IconButton icon={ChevronLeft} label="Previous page" disabled={disabled || page <= 1} onClick={() => onPage(page - 1)} />
          {pageWindow(page, pages).map((p, i) =>
            p === "gap" ? (
              <span key={`gap-${i}`} aria-hidden className="px-1">
                …
              </span>
            ) : (
              <button
                key={p}
                type="button"
                disabled={disabled}
                aria-current={p === page ? "page" : undefined}
                aria-label={`Page ${p}`}
                onClick={() => onPage(p)}
                className={`h-8 min-w-8 rounded-md px-2 ${p === page ? "bg-primary text-primary-foreground" : "hover:bg-accent hover:text-accent-foreground"}`}
              >
                {p}
              </button>
            ),
          )}
          <IconButton icon={ChevronRight} label="Next page" disabled={disabled || page >= pages} onClick={() => onPage(page + 1)} />
        </div>
      ) : null}
    </nav>
  );
}
