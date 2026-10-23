import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { type ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ListLoadError } from "@/core/components/ListLoadError";
import { api, API_URL, type Page } from "@/core/lib/api";
import { server } from "../../../../tests/setup";
import { makeQueryClient } from "./client";
import { defineKeys } from "./keys";
import { resetRefreshFailed, subscribeRefreshFailed } from "./refresh-failed";
import { useApiList } from "./use-api-query";

type Row = { id: number; name: string };
const keys = defineKeys("probe.rows", { list: (q: string) => ["list", { q }] });
const URL = `${API_URL}/api/probe/rows/`;

function Rows({ enabled = true, q = "" }: { enabled?: boolean; q?: string }) {
  const rows = useApiList<Row>(keys.list(q), (signal) => api<Page<Row>>("/api/probe/rows/", { signal }), { enabled });
  if (rows.showError) return <ListLoadError {...rows.listErrorProps} resource="rows" />;
  if (rows.isLoading) return <p>loading…</p>;
  if (rows.isEmpty) return <p>No rows yet</p>;
  return (
    <ul data-fetching={rows.isFetching}>
      {rows.items.map((r) => (
        <li key={r.id}>{r.name}</li>
      ))}
    </ul>
  );
}

function wrap(ui: ReactNode) {
  const client = makeQueryClient();
  client.setDefaultOptions({ queries: { ...client.getDefaultOptions().queries, retry: false } });
  return { client, ...render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>) };
}

const page = (results: Row[]): Page<Row> => ({ count: results.length, next: null, previous: null, results });

beforeEach(() => resetRefreshFailed());
afterEach(() => vi.restoreAllMocks());

describe("useApiList: the load-state contract", () => {
  it("renders an error, never an empty state, when the list fetch fails", async () => {
    server.use(http.get(URL, () => HttpResponse.json({ error: { code: "server_error", message: "boom", request_id: "r1" } }, { status: 500 })));
    wrap(<Rows />);
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Couldn't load rows");
    expect(alert).toHaveTextContent("boom");
    expect(alert).toHaveTextContent("r1");
    expect(screen.queryByText("No rows yet")).toBeNull();
  });

  it("a disabled query is neither empty nor errored", () => {
    wrap(<Rows enabled={false} />);
    expect(screen.queryByText("No rows yet")).toBeNull();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("an empty success is empty", async () => {
    server.use(http.get(URL, () => HttpResponse.json(page([]))));
    wrap(<Rows />);
    expect(await screen.findByText("No rows yet")).toBeInTheDocument();
  });

  it("a failed refetch keeps the data and announces once per distinct error", async () => {
    let calls = 0;
    server.use(
      http.get(URL, () => {
        calls += 1;
        if (calls === 1) return HttpResponse.json(page([{ id: 1, name: "Ada" }]));
        return HttpResponse.json({ error: { code: "server_error" } }, { status: calls === 2 || calls === 3 ? 503 : 502 });
      }),
    );
    const events: string[] = [];
    const unsubscribe = subscribeRefreshFailed((e) => events.push(e.key));
    const { client } = wrap(<Rows />);
    expect(await screen.findByText("Ada")).toBeInTheDocument();
    for (let attempt = 0; attempt < 3; attempt++) {
      await client.refetchQueries({ queryKey: keys.root });
      await waitFor(() => expect(screen.getByText("Ada")).toBeInTheDocument());
    }
    expect(screen.queryByRole("alert")).toBeNull(); // last-good data is still shown
    await waitFor(() => expect(events).toEqual(["server:server_error:503", "server:server_error:502"]));
    unsubscribe();
  });

  it("refetch() resolves on failure instead of rejecting", async () => {
    server.use(http.get(URL, () => HttpResponse.json({ error: { code: "server_error" } }, { status: 500 })));
    wrap(<Rows />);
    const retry = await screen.findByRole("button", { name: "Try again" });
    await expect(Promise.resolve(retry.click())).resolves.toBeUndefined();
  });
});
