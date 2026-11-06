"use client";

/**
 * The error surface a list renders when it failed and has nothing to show (FRONTEND_PLATFORM § 5).
 * Never an empty state: "No invoices yet" after a network blip reads as "your invoices are gone".
 */
import { isApiError, messageFor } from "@/core/lib/api/errors";
import type { ListErrorProps } from "@/core/lib/query/use-api-query";

export function ListLoadError({ error, retry, resource }: ListErrorProps & { resource: string }) {
  const message = isApiError(error) ? messageFor(error) : "Something went wrong.";
  const requestId = isApiError(error) ? error.requestId : undefined;
  return (
    <div role="alert" className="rounded-md border border-err-dot/40 bg-err-tint p-4 text-sm text-err-text">
      <p>
        Couldn&apos;t load {resource}. {message}
      </p>
      <p className="mt-1">This is a display problem — nothing has changed.</p>
      {requestId && <p className="mt-1 text-xs opacity-80">Reference: {requestId}</p>}
      <button type="button" className="mt-2 underline underline-offset-4" onClick={() => void retry()}>
        Try again
      </button>
    </div>
  );
}
