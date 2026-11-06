"use client";

import { isApiError, messageFor } from "@/core/lib/api/errors";
import { useT } from "@/core/lib/i18n";

/**
 * A panel that failed to load (FRONTEND_PLATFORM § 13): says what failed, that nothing changed,
 * offers a retry and shows the request id for support. ListLoadError is the list-shaped twin.
 */
export function PanelError({ error, retry, what }: { error: unknown; retry?: () => unknown; what: string }) {
  const t = useT();
  const message = isApiError(error) ? messageFor(error) : t("common.somethingWentWrong");
  const requestId = isApiError(error) ? error.requestId : undefined;
  return (
    <div role="alert" className="rounded-md border border-err-dot/40 bg-err-tint p-4 text-sm text-err-text">
      <p className="font-medium">{t("components.panelError.couldNotLoad", { what })}</p>
      <p className="mt-1">
        {message} {t("common.displayProblem")}
      </p>
      {requestId ? <p className="mt-1 text-xs opacity-80">{t("common.reference", { requestId })}</p> : null}
      {retry ? (
        <button type="button" className="mt-2 underline underline-offset-4" onClick={() => void retry()}>
          {t("common.tryAgain")}
        </button>
      ) : null}
    </div>
  );
}
