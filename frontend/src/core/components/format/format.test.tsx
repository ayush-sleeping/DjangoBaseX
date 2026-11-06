/**
 * The rendered formatters follow the viewer (FRONTEND_PLATFORM § 14, BUILD_ORDER 8.4b): bootstrap's
 * `localization` when signed in, the platform's locale from public config otherwise. No component
 * names a locale or a currency of its own.
 */
import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import type { ReactNode } from "react";
import { describe, expect, it } from "vitest";

import { API_URL } from "@/core/lib/api";
import { LocalizationProvider } from "@/core/lib/format/use-format";
import { makeQueryClient } from "@/core/lib/query/client";

import { server } from "../../../../tests/setup";
import { DateOnly, DateTime, Money } from "./index";

const BOOT = `${API_URL}/api/me/bootstrap/`;

function wrap(ui: ReactNode, platform = { locale: "en-US", timezone: "UTC" }) {
  const client = makeQueryClient();
  client.setDefaultOptions({ queries: { ...client.getDefaultOptions().queries, retry: false } });
  return render(
    <QueryClientProvider client={client}>
      <LocalizationProvider platform={platform}>{ui}</LocalizationProvider>
    </QueryClientProvider>,
  );
}

describe("<DateTime> / <Money>", () => {
  it("use the signed-in viewer's locale and zone from bootstrap", async () => {
    server.use(
      http.get(BOOT, () =>
        HttpResponse.json({
          user: {}, permissions: [], session: {}, server_time: "x", degraded: [],
          localization: { locale: "de-DE", timezone: "Europe/Berlin", currency: "EUR", country: "DE", date_style: "locale", time_style: "locale", week_start: "locale" },
        }),
      ),
    );
    wrap(
      <>
        <DateTime value="2026-03-01T23:30:00Z" />
        <Money amount="1234.5" currency="EUR" />
      </>,
    );
    // 23:30 UTC is 00:30 on 2 March in Berlin: the viewer's zone, not the machine's.
    const time = await screen.findByText(/02\.03\.2026|2\. März 2026/);
    expect(time.tagName).toBe("TIME");
    expect(time).toHaveAttribute("dateTime", "2026-03-01T23:30:00Z");
    expect(time.getAttribute("title")).toMatch(/UTC · shown in Europe\/Berlin/);
    // Testing Library normalises the no-break space Intl puts before the euro sign.
    expect(screen.getByText(/^1\.234,50\s€$/)).toBeInTheDocument();
  });

  it("fall back to the platform's locale while signed out", async () => {
    server.use(http.get(BOOT, () => HttpResponse.json({ error: { code: "not_authenticated", message: "x" } }, { status: 401 })));
    server.use(http.post(`${API_URL}/api/auth/refresh/`, () => new HttpResponse(null, { status: 401 })));
    wrap(<DateOnly value="2026-03-01" />, { locale: "en-IN", timezone: "Asia/Kolkata" });
    expect(await screen.findByText("1 Mar 2026")).toBeInTheDocument();
  });

  it("render the one empty marker for a missing value", () => {
    // The provider still asks for bootstrap; without a handler MSW's "error" strategy rejects and
    // Vitest fails the run as an unhandled error even though every assertion passed.
    server.use(http.get(BOOT, () => HttpResponse.json({ error: { code: "not_authenticated", message: "x" } }, { status: 401 })));
    server.use(http.post(`${API_URL}/api/auth/refresh/`, () => new HttpResponse(null, { status: 401 })));
    wrap(<DateTime value={null} />);
    expect(screen.getByText("—")).toBeInTheDocument();
  });
});
