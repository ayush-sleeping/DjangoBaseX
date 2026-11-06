"use client";

/**
 * The error surface a list renders when it failed and has nothing to show (FRONTEND_PLATFORM § 5).
 * Never an empty state: "No invoices yet" after a network blip reads as "your invoices are gone".
 */
import { isApiError, messageFor } from "@/core/lib/api/errors";
import { useT } from "@/core/lib/i18n";
import type { ListErrorProps } from "@/core/lib/query/use-api-query";

export function ListLoadError({ error, retry, resource }: ListErrorProps & { resource: string }) {
  const t = useT();
  const message = isApiError(error) ? messageFor(error) : t("common.somethingWentWrong");
  const requestId = isApiError(error) ? error.requestId : undefined;
  return (
    <div role="alert" className="rounded-md border border-err-dot/40 bg-err-tint p-4 text-sm text-err-text">
      <p>{t("components.listError.couldNotLoad", { resource, message })}</p>
      <p className="mt-1">{t("common.displayProblem")}</p>
      {requestId && <p className="mt-1 text-xs opacity-80">{t("common.reference", { requestId })}</p>}
      <button type="button" className="mt-2 underline underline-offset-4" onClick={() => void retry()}>
        {t("common.tryAgain")}
      </button>
    </div>
  );
}
