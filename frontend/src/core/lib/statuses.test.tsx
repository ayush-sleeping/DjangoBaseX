/**
 * Status metadata comes from the backend (BUILD_ORDER 8.4a): bootstrap's table (plugins included)
 * wins; the generated core table answers before bootstrap arrives and outside a provider.
 */
import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import { StatusPill } from "@/core/components/StatusPill";
import { STATUSES } from "@/generated/statuses";

import { server } from "../../../tests/setup";
import { API_URL } from "./api";
import { makeQueryClient } from "./query/client";
import { StatusProvider } from "./statuses";

describe("useStatus / StatusPill", () => {
  it("uses the generated core table without a provider", () => {
    render(<StatusPill status="users.user.deactivated" />);
    expect(screen.getByText(STATUSES["users.user.deactivated"].label).closest("[data-tone]")).toHaveAttribute("data-tone", "err");
  });

  it("takes a plugin's status from bootstrap, with its tone", async () => {
    server.use(
      http.get(`${API_URL}/api/me/bootstrap/`, () =>
        HttpResponse.json({
          user: {}, permissions: [], session: {}, server_time: "x", degraded: [],
          statuses: { "notes.note.archived": { label: "Archived", tone: "neutral", transitional: false } },
        }),
      ),
    );
    const client = makeQueryClient();
    render(
      <QueryClientProvider client={client}>
        <StatusProvider>
          <StatusPill status="notes.note.archived" />
        </StatusProvider>
      </QueryClientProvider>,
    );
    expect((await screen.findByText("Archived")).closest("[data-tone]")).toHaveAttribute("data-tone", "neutral");
  });
});
