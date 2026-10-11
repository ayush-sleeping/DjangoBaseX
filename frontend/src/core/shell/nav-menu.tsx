"use client";

// Client component: navigation is per-user, and the session is an httpOnly cookie.
import Link from "next/link";
import { useEffect, useState } from "react";

import { ApiError } from "@/core/lib/api";
import { fetchNavigation, type NavSection } from "@/core/lib/navigation";

/** Every section and item this user may follow; renders nothing when signed out. */
export function NavMenu() {
  const [sections, setSections] = useState<NavSection[] | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let active = true;
    fetchNavigation()
      .then((value) => {
        if (active) setSections(value);
      })
      .catch((error) => {
        if (!active) return;
        // Signed out is the one expected failure. Anything else is shown, never rendered as an
        // empty menu (BUG_CLASSES BC-42): a 500 here means a broken registration, not "no items".
        if (error instanceof ApiError && error.status === 401) setSections([]);
        else setFailed(true);
      });
    return () => {
      active = false;
    };
  }, []);

  if (failed) {
    return (
      <p role="alert" className="text-sm text-red-600">
        Could not load the menu. Reload the page to try again.
      </p>
    );
  }
  if (!sections || sections.length === 0) return null;
  return (
    <nav aria-label="Modules" className="w-full max-w-md rounded-xl border border-zinc-200 p-6 dark:border-zinc-800">
      {sections.map((section) => (
        <section key={section.key} className="mb-3 last:mb-0">
          <h2 className="mb-1 text-sm font-semibold uppercase tracking-wide text-zinc-500">
            {section.label}
          </h2>
          <ul className="space-y-1 text-sm">
            {section.items.map((item) => (
              <li key={item.key}>
                <Link className="underline" href={item.path}>
                  {item.label}
                </Link>
              </li>
            ))}
          </ul>
        </section>
      ))}
    </nav>
  );
}
