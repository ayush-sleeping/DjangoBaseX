"use client";

/**
 * <DateTime>, <Money>, <Bytes> (FRONTEND_PLATFORM § 13, § 14): the rendered forms of the formatters,
 * bound to the viewer's localization. A missing value renders the one empty marker.
 */
import { useFormat } from "@/core/lib/format/use-format";

/** An instant as <time dateTime>, in the viewer's zone, with UTC and the zone name on hover. */
export function DateTime({ value }: { value: string | null | undefined }) {
  const f = useFormat();
  if (!value) return <>{f.dateTime(value)}</>;
  return (
    <time dateTime={value} title={f.instantUtc(value)}>
      {f.dateTime(value)}
    </time>
  );
}

/** A calendar date ("2026-03-01") — never shifted by a timezone. */
export function DateOnly({ value }: { value: string | null | undefined }) {
  const f = useFormat();
  if (!value) return <>{f.date(value)}</>;
  return <time dateTime={value}>{f.date(value)}</time>;
}

/** An amount in the record's own currency: a decimal string and an ISO code from the API. */
export function Money({ amount, currency }: { amount: string | null | undefined; currency: string | null | undefined }) {
  const f = useFormat();
  return <span className="tabular-nums">{f.money(amount, currency)}</span>;
}

export function Bytes({ value }: { value: number | null | undefined }) {
  const f = useFormat();
  return <span className="tabular-nums">{f.bytes(value)}</span>;
}
