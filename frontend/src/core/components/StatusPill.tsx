"use client";

import { TONE_DOT, TONE_EMPTY, TONE_PILL } from "@/core/lib/status-tone";
import { useT } from "@/core/lib/i18n";
import { useStatus } from "@/core/lib/statuses";

/**
 * The one status chip (FRONTEND_PLATFORM § 13). Takes a status KEY; its label and tone are the
 * backend's (useStatus), so two screens can never disagree about what "deactivated" looks like. An unknown or missing key renders
 * the dashed "not set" chip, never a guessed colour.
 */
export function StatusPill({ status, label, title }: { status: string | null | undefined; label?: string; title?: string }) {
  const t = useT("components.status");
  const meta = useStatus(status);
  if (!meta) {
    return <span title={title} className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs ${TONE_EMPTY}`}>{label ?? t("notSet")}</span>;
  }
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset ${TONE_PILL[meta.tone]}`}
      data-tone={meta.tone}
      title={title}
    >
      <span aria-hidden className={`size-1.5 rounded-full ${TONE_DOT[meta.tone]} ${meta.transitional ? "animate-pulse" : ""}`} />
      {label ?? meta.label}
    </span>
  );
}
