"use client";

// Client component: navigation is per-user, and the session is an httpOnly cookie.
import Link from "next/link";

import { useNav } from "@/core/shell/nav/use-nav";

/** Every section and item this user may follow; renders nothing when signed out. */
export function NavMenu() {
  const nav = useNav();

  if (nav.failed && nav.signedIn) {
    // A broken registration or menu build is shown, never rendered as an empty menu (BC-42).
    return (
      <p role="alert" className="text-sm text-red-600">
        Could not load the menu. Reload the page to try again.
      </p>
    );
  }
  if (nav.sections.length === 0) return null;
  return (
    <nav aria-label="Modules" className="w-full max-w-md rounded-xl border border-zinc-200 p-6 dark:border-zinc-800">
      {nav.sections.map((section) => (
        <section key={section.key} className="mb-3 last:mb-0">
          <h2 className="mb-1 text-sm font-semibold uppercase tracking-wide text-zinc-500">
            {section.label}
          </h2>
          <ul className="space-y-1 text-sm">
            {section.items.map((item) => (
              <li key={item.key}>
                <Link className="underline" href={item.href}>
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
