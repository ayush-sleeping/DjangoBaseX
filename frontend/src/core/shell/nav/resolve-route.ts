/**
 * The ONE deepest-prefix function (FRONTEND_PLATFORM § 10), shared by the route gate, the proxy
 * and the route-manifest test, so the three can never disagree about which entry owns a page.
 *
 * Navigation is the route gate: a pathname is matched against every entry's href (menu items and
 * `hidden` URL-only entries alike) and the LONGEST matching href wins. No match → no entry → the
 * page is denied (default-deny). An `exact` entry matches only its own href, so "/" does not
 * swallow every page.
 */
export type RouteEntry = {
  key: string;
  label: string;
  href: string;
  permission: string | null;
  hidden: boolean;
  public: boolean;
  exact: boolean;
};

export type NavSection = { key: string; label: string; module: string; items: RouteEntry[] };

/** "/users/" and "/users" are one page; "/" stays "/". */
export function normalisePath(pathname: string): string {
  const path = pathname.split(/[?#]/, 1)[0] || "/";
  return path.length > 1 ? path.replace(/\/+$/, "") || "/" : path;
}

export function matches(entry: Pick<RouteEntry, "href" | "exact">, pathname: string): boolean {
  const path = normalisePath(pathname);
  const href = normalisePath(entry.href);
  if (path === href) return true;
  if (entry.exact) return false;
  return path.startsWith(href === "/" ? "/" : `${href}/`);
}

/** The entry that owns `pathname`, or null: denied. */
export function resolveRoute<E extends Pick<RouteEntry, "href" | "exact">>(
  pathname: string,
  entries: readonly E[],
): E | null {
  let best: E | null = null;
  for (const entry of entries) {
    if (!matches(entry, pathname)) continue;
    if (!best || normalisePath(entry.href).length > normalisePath(best.href).length) best = entry;
  }
  return best;
}

export function flatten(sections: readonly NavSection[]): RouteEntry[] {
  return sections.flatMap((section) => section.items);
}
