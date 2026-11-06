/**
 * The Users reference module end to end against a mocked API (BUILD_ORDER 8.3b): the index lists
 * through useApiList, hides actions the user cannot take, creates through the modal form and lands
 * on the record; the record shows its facts and gates its actions.
 */
import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ConfirmHost } from "@/core/components/confirm";
import { API_URL } from "@/core/lib/api";
import { PermissionProvider } from "@/core/lib/permissions";
import { makeQueryClient } from "@/core/lib/query/client";
import type { User } from "@/core/lib/users";

import { server } from "../../../../tests/setup";
import { UsersIndex } from "./Index";
import { UserShow } from "./Show";

const push = vi.fn();
const replace = vi.fn();
let search = "";
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push, replace }),
  usePathname: () => "/users",
  useSearchParams: () => new URLSearchParams(search),
}));

const ADA: User = {
  public_id: "u-ada", email: "ada@example.test", full_name: "Ada Lovelace", is_active: true, is_superuser: false,
  mfa_enabled: true, last_login: null, created_at: "2026-01-01T00:00:00Z", deactivated_at: null, deactivated_reason: "", roles: [{ public_id: "r1", slug: "staff", name: "Staff" }],
};

function signedInWith(...permissions: string[]) {
  server.use(
    http.get(`${API_URL}/api/me/bootstrap/`, () =>
      HttpResponse.json({
        user: { public_id: "u-me", email: "me@example.test", full_name: "", is_staff: false, is_superuser: false, mfa_enabled: false, mfa_enforced: false },
        permissions, session: { expires_at: "x", idle_expires_at: "x" }, server_time: "x", nav: [], flags: [], build: "test", degraded: [],
      }),
    ),
  );
}

function wrap(ui: ReactNode) {
  const client = makeQueryClient();
  client.setDefaultOptions({ queries: { ...client.getDefaultOptions().queries, retry: false } });
  return render(
    <QueryClientProvider client={client}>
      <PermissionProvider>{ui}</PermissionProvider>
      <ConfirmHost />
    </QueryClientProvider>,
  );
}

const page = (results: User[]) => ({ count: results.length, next: null, previous: null, results });

beforeEach(() => {
  push.mockReset();
  search = "";
});

describe("UsersIndex", () => {
  it("lists users through the shell, with status pills and labelled actions", async () => {
    signedInWith("users.users.view");
    server.use(http.get(`${API_URL}/api/users/`, () => HttpResponse.json(page([ADA]))));
    const { container } = wrap(<UsersIndex />);
    const row = await screen.findByRole("row", { name: /ada@example.test/ });
    expect(within(row).getByText("Active")).toBeInTheDocument();
    expect(within(row).getByRole("link", { name: "Open Ada Lovelace" })).toHaveAttribute("href", "/users/u-ada");
    expect(container.querySelector('[data-page="users.user.index"]')).not.toBeNull();
    // Without users.users.create there is no New user button anywhere.
    expect(screen.queryByRole("button", { name: /New user/ })).toBeNull();
  });

  it("sends the URL's search and page to the API", async () => {
    signedInWith("users.users.view");
    search = "search=ada&page=2";
    const seen = vi.fn();
    server.use(
      http.get(`${API_URL}/api/users/`, ({ request }) => {
        seen(new URL(request.url).searchParams.toString());
        return HttpResponse.json({ count: 21, next: null, previous: "x", results: [ADA] });
      }),
    );
    wrap(<UsersIndex />);
    await screen.findByRole("row", { name: /ada@example.test/ });
    expect(seen).toHaveBeenCalledWith("page=2&search=ada");
  });

  it("creates a user from the modal and opens the record", async () => {
    const user = userEvent.setup();
    signedInWith("users.users.view", "users.users.create");
    server.use(
      http.get(`${API_URL}/api/users/`, () => HttpResponse.json(page([]))),
      http.post(`${API_URL}/api/users/`, async ({ request }) => {
        const body = (await request.json()) as { email: string };
        return HttpResponse.json({ ...ADA, public_id: "u-new", email: body.email }, { status: 201 });
      }),
    );
    wrap(<UsersIndex />);
    expect(await screen.findByText("No users yet")).toBeInTheDocument();
    await user.click(screen.getAllByRole("button", { name: /New user/ })[0]);
    await user.type(await screen.findByLabelText(/Email/), "new@example.test");
    await user.click(screen.getByRole("button", { name: "Create user" }));
    await waitFor(() => expect(push).toHaveBeenCalledWith("/users/u-new"));
  });

  it("puts the API's field error on the field", async () => {
    const user = userEvent.setup();
    signedInWith("users.users.view", "users.users.create");
    server.use(
      http.get(`${API_URL}/api/users/`, () => HttpResponse.json(page([]))),
      http.post(`${API_URL}/api/users/`, () =>
        HttpResponse.json({ error: { code: "invalid", message: "Invalid.", details: { email: ["A user with this email already exists."] } } }, { status: 400 }),
      ),
    );
    wrap(<UsersIndex />);
    await user.click((await screen.findAllByRole("button", { name: /New user/ }))[0]);
    await user.type(await screen.findByLabelText(/Email/), "ada@example.test");
    await user.click(screen.getByRole("button", { name: "Create user" }));
    expect(await screen.findByText("A user with this email already exists.")).toBeInTheDocument();
    expect(screen.getByLabelText(/Email/)).toHaveAttribute("aria-invalid", "true");
  });
});

describe("UserShow", () => {
  it("shows the record and offers only the actions the user holds", async () => {
    signedInWith("users.users.view", "users.users.update");
    server.use(http.get(`${API_URL}/api/users/u-ada/`, () => HttpResponse.json(ADA)));
    const { container } = wrap(<UserShow publicId="u-ada" />);
    expect(await screen.findByRole("heading", { level: 1 })).toHaveTextContent("ada@example.test");
    expect(screen.getByRole("button", { name: /Edit/ })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Deactivate/ })).toBeNull();
    expect(screen.queryByText("Sessions")).toBeNull();
    expect(screen.getByText("Staff")).toBeInTheDocument();
    expect(container.querySelector('[data-page="users.user.show"]')).not.toBeNull();
  });

  it("renders a failed load as a panel error", async () => {
    signedInWith("users.users.view");
    server.use(http.get(`${API_URL}/api/users/u-x/`, () => HttpResponse.json({ error: { code: "not_found", message: "Not found." } }, { status: 404 })));
    wrap(<UserShow publicId="u-x" />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Couldn't load this user");
  });
});
