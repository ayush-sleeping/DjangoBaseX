"use client";

/**
 * The Show shell (FRONTEND_PLATFORM § 11): a title row with the record's badges and actions, then
 * a 2:1 grid — the record's sections on the left, a sticky sidebar of facts on the right. The
 * sidebar is `self-start`: without it, a grid item stretches to the row's height and `sticky`
 * never engages (load-bearing, not decoration).
 *
 * Loading and failure are the shell's too, so no record page renders a half-loaded record.
 */
import type { ReactNode } from "react";

import { useEnrolmentRedirect } from "./use-enrolment-redirect";

import { PanelError } from "@/core/components/PanelError";

export type ShowState = { isLoading: boolean; showError: boolean; error: unknown; refetch: () => unknown };

export function ResourceShow({
  pageKey,
  noun,
  state,
  title,
  subtitle,
  badges,
  actions,
  sidebar,
  children,
}: {
  /** "<module>.<resource>.show", rendered as data-page for e2e selectors. */
  pageKey: string;
  /** Singular noun: "user". */
  noun: string;
  state: ShowState;
  title?: ReactNode;
  subtitle?: ReactNode;
  badges?: ReactNode;
  /** Record actions, each permission-gated by the caller. */
  actions?: ReactNode;
  sidebar?: ReactNode;
  /** The record's sections (InfoCards). Rendered only once the record has loaded. */
  children?: ReactNode;
}) {
  useEnrolmentRedirect(state.showError ? state.error : null);
  if (state.showError) {
    return (
      <main data-page={pageKey} className="mx-auto w-full max-w-6xl p-6">
        <PanelError error={state.error} retry={state.refetch} what={`this ${noun}`} />
      </main>
    );
  }
  if (state.isLoading) {
    return (
      <main data-page={pageKey} aria-busy className="mx-auto w-full max-w-6xl space-y-4 p-6">
        <span className="block h-8 w-1/3 animate-pulse rounded bg-muted" />
        <span className="block h-40 w-full animate-pulse rounded-xl bg-muted" />
      </main>
    );
  }
  return (
    <main data-page={pageKey} className="mx-auto w-full max-w-6xl space-y-6 p-6">
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0 space-y-1">
          <h1 className="flex flex-wrap items-center gap-2 text-2xl font-bold tracking-tight">
            <span className="min-w-0 break-words">{title}</span>
            {badges}
          </h1>
          {subtitle ? <div className="text-sm text-muted-foreground">{subtitle}</div> : null}
        </div>
        {actions ? <div className="flex flex-wrap gap-2">{actions}</div> : null}
      </header>
      <div className="grid gap-6 lg:grid-cols-3">
        <div className="min-w-0 space-y-6 lg:col-span-2">{children}</div>
        {sidebar ? <aside className="space-y-4 self-start lg:sticky lg:top-6">{sidebar}</aside> : null}
      </div>
    </main>
  );
}

/** A section of a record: a titled card with optional actions. */
export function InfoCard({ title, actions, children }: { title: string; actions?: ReactNode; children: ReactNode }) {
  return (
    <section className="space-y-3 rounded-xl border border-border bg-card p-5 text-card-foreground">
      <header className="flex items-center justify-between gap-3">
        <h2 className="text-sm font-semibold">{title}</h2>
        {actions ? <div className="flex gap-2">{actions}</div> : null}
      </header>
      {children}
    </section>
  );
}

/** Facts about a record: label → value. A missing value renders one em dash. */
export function MetaCard({ title = "Details", items }: { title?: string; items: { label: string; value: ReactNode }[] }) {
  return (
    <section className="rounded-xl border border-border bg-card p-5 text-card-foreground">
      <h2 className="mb-3 text-sm font-semibold">{title}</h2>
      <dl className="grid grid-cols-[max-content_1fr] gap-x-4 gap-y-2 text-sm">
        {items.map((item) => (
          <div key={item.label} className="contents">
            <dt className="text-muted-foreground">{item.label}</dt>
            <dd className="min-w-0 break-words">{item.value ?? "—"}</dd>
          </div>
        ))}
      </dl>
    </section>
  );
}
