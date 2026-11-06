import type { HTMLAttributes, ReactNode } from "react";

/** A surface: card fill, its foreground, a border. */
export function Card({ className, ...rest }: HTMLAttributes<HTMLElement>) {
  return <section className={`rounded-xl border border-border bg-card p-6 text-card-foreground ${className ?? ""}`} {...rest} />;
}

export function CardTitle({ children }: { children: ReactNode }) {
  return <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-muted-foreground">{children}</h2>;
}
