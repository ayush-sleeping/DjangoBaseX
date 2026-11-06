"use client";

import { isApiError, messageFor } from "@/core/lib/api/errors";

/**
 * A panel that failed to load (FRONTEND_PLATFORM § 13): says what failed, that nothing changed,
 * offers a retry and shows the request id for support. ListLoadError is the list-shaped twin.
 */
export function PanelError({ error, retry, what }: { error: unknown; retry?: () => unknown; what: string }) {
  const message = isApiError(error) ? messageFor(error) : "Something went wrong.";
  const requestId = isApiError(error) ? error.requestId : undefined;
  return (
    <div role="alert" className="rounded-md border border-err-dot/40 bg-err-tint p-4 text-sm text-err-text">
      <p className="font-medium">Couldn&apos;t load {what}.</p>
      <p className="mt-1">{message} This is a display problem — nothing has changed.</p>
      {requestId ? <p className="mt-1 text-xs opacity-80">Reference: {requestId}</p> : null}
      {retry ? (
        <button type="button" className="mt-2 underline underline-offset-4" onClick={() => void retry()}>
          Try again
        </button>
      ) : null}
    </div>
  );
}
