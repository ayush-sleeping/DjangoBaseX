"use client";

// Client component: users are authenticated data, and the session is an httpOnly cookie.
import Link from "next/link";
import { useRouter } from "next/navigation";
import { type FormEvent, useEffect, useState } from "react";

import { ApiError, isMfaEnrollmentRequired, type Page } from "@/core/lib/api";
import { INVITATION_CODES } from "@/core/lib/invitations";
import { MFA_ENROLMENT_PATH } from "@/core/lib/mfa";
import { usePermissions } from "@/core/lib/permissions";
import {
  formatDateTime,
  listUsers,
  type User,
  USER_CODES,
  usersErrorMessage,
  usersListHref,
} from "@/core/lib/users";

import { Gate, ui, UserBadges } from "./gate";

type Query = { page: number; search: string };
type Listing = Query & { users?: Page<User>; error?: string };

export function UsersPanel({
  initialPage,
  initialSearch,
}: {
  initialPage: number;
  initialSearch: string;
}) {
  const router = useRouter();
  const perms = usePermissions();
  const allowed = perms.can(USER_CODES.view);
  const [query, setQuery] = useState<Query>({ page: initialPage, search: initialSearch });
  const [listing, setListing] = useState<Listing | null>(null);

  useEffect(() => {
    if (!allowed) return;
    let active = true;
    listUsers(query.page, query.search)
      .then((users) => {
        if (active) setListing({ ...query, users });
      })
      .catch((error) => {
        if (!active) return;
        if (isMfaEnrollmentRequired(error)) router.push(MFA_ENROLMENT_PATH);
        // A page past the end (a stale link, a shrunken search) is DRF's 404: start over.
        if (error instanceof ApiError && error.status === 404 && query.page > 1) {
          setQuery({ ...query, page: 1 });
          window.history.replaceState(null, "", usersListHref(1, query.search));
          return;
        }
        setListing({ ...query, error: usersErrorMessage(error) });
      });
    return () => {
      active = false;
    };
  }, [allowed, query, router]);

  function go(next: Query) {
    setQuery(next);
    // Keep the address bar in step without a server round trip: Next syncs replaceState.
    window.history.replaceState(null, "", usersListHref(next.page, next.search));
  }

  function handleSearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    go({ page: 1, search: String(new FormData(event.currentTarget).get("search") ?? "") });
  }

  return (
    <Gate perms={perms} code={USER_CODES.view} what="view users">
      {() => {
        const loading =
          !listing || listing.page !== query.page || listing.search !== query.search;
        const users = listing?.users;
        return (
          <div className="flex w-full flex-col items-center gap-4">
            <nav className="flex w-full max-w-3xl flex-wrap items-center gap-4 text-sm">
              {perms.can(USER_CODES.create) ? (
                <Link className="underline" href="/users/new">
                  New user
                </Link>
              ) : null}
              {perms.can(INVITATION_CODES.send) ? (
                <Link className="underline" href="/users/invitations">
                  Invitations
                </Link>
              ) : null}
              <form onSubmit={handleSearch} className="ml-auto flex gap-2" role="search">
                <input
                  name="search"
                  type="search"
                  defaultValue={query.search}
                  placeholder="Search by email or name"
                  aria-label="Search users"
                  className="rounded-md border border-zinc-300 px-3 py-1.5 dark:border-zinc-700 dark:bg-zinc-900"
                />
                <button type="submit" className={ui.button}>
                  Search
                </button>
              </form>
            </nav>

            <section className={ui.card}>
              {loading ? (
                <p className="text-sm text-zinc-500">Loading users…</p>
              ) : listing.error ? (
                <p role="alert" className={ui.error}>
                  {listing.error}
                </p>
              ) : users && users.results.length > 0 ? (
                <table className="w-full text-left text-sm">
                  <thead className="text-xs uppercase tracking-wide text-zinc-500">
                    <tr>
                      <th className="pb-2 font-medium">User</th>
                      <th className="pb-2 font-medium">Roles</th>
                      <th className="pb-2 font-medium">Last sign-in</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-zinc-200 dark:divide-zinc-800">
                    {users.results.map((user) => (
                      <tr key={user.public_id}>
                        <td className="py-2 pr-3">
                          <Link
                            className="font-medium underline"
                            href={`/users/${encodeURIComponent(user.public_id)}`}
                          >
                            {user.email}
                          </Link>{" "}
                          <UserBadges user={user} />
                          {user.full_name ? (
                            <span className="block text-xs text-zinc-500">{user.full_name}</span>
                          ) : null}
                        </td>
                        <td className="py-2 pr-3 text-xs">
                          {user.roles.map((role) => role.name).join(", ") || "—"}
                        </td>
                        <td className="py-2 text-xs text-zinc-500">
                          {formatDateTime(user.last_login)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              ) : (
                <p className="text-sm text-zinc-500">
                  {query.search ? `No users match "${query.search}".` : "No users yet."}
                </p>
              )}
              {users && (users.previous || users.next) ? (
                <nav className="flex items-center justify-between text-sm">
                  <button
                    type="button"
                    className="underline disabled:no-underline disabled:opacity-40"
                    disabled={!users.previous || loading}
                    onClick={() => go({ ...query, page: Math.max(1, query.page - 1) })}
                  >
                    Previous
                  </button>
                  <span className="text-zinc-500">
                    Page {query.page} · {users.count} users
                  </span>
                  <button
                    type="button"
                    className="underline disabled:no-underline disabled:opacity-40"
                    disabled={!users.next || loading}
                    onClick={() => go({ ...query, page: query.page + 1 })}
                  >
                    Next
                  </button>
                </nav>
              ) : null}
            </section>
          </div>
        );
      }}
    </Gate>
  );
}
