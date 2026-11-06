"use client";

/**
 * The pager (FRONTEND_PLATFORM § 11, § 12). The row count lives here and nowhere else. Pages are
 * truncated around the current one: 1 … 4 5 6 … 20.
 */
import { ChevronLeft, ChevronRight } from "lucide-react";

import { list as listDefaults } from "@/core/lib/config/defaults";
import { useT } from "@/core/lib/i18n";

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
  noun,
  disabled = false,
}: {
  page: number;
  count: number;
  onPage: (page: number) => void;
  pageSize?: number;
  /** Plural noun for the count, already translated: "users", "orders". "rows" when omitted. */
  noun?: string;
  disabled?: boolean;
}) {
  const t = useT("dataTable");
  const label = noun ?? t("rows");
  const pages = Math.max(1, Math.ceil(count / pageSize));
  const from = count === 0 ? 0 : (page - 1) * pageSize + 1;
  const to = Math.min(count, page * pageSize);
  return (
    <nav aria-label={t("pager.label")} className="flex flex-wrap items-center justify-between gap-2 text-sm text-muted-foreground">
      <p aria-live="polite">
        {count === 0 ? t("pager.none", { count, noun: label }) : t("pager.range", { from, to, count, noun: label })}
      </p>
      {pages > 1 ? (
        <div className="flex items-center gap-1">
          <IconButton icon={ChevronLeft} label={t("pager.previous")} disabled={disabled || page <= 1} onClick={() => onPage(page - 1)} />
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
                aria-label={t("pager.page", { page: p })}
                onClick={() => onPage(p)}
                className={`h-8 min-w-8 rounded-md px-2 ${p === page ? "bg-primary text-primary-foreground" : "hover:bg-accent hover:text-accent-foreground"}`}
              >
                {t("pager.number", { page: p })}
              </button>
            ),
          )}
          <IconButton icon={ChevronRight} label={t("pager.next")} disabled={disabled || page >= pages} onClick={() => onPage(page + 1)} />
        </div>
      ) : null}
    </nav>
  );
}
