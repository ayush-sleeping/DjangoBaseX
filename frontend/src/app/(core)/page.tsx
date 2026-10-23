import Link from "next/link";

import { api, API_URL } from "@/core/lib/api";
import { getIdentity } from "@/core/lib/identity";
import { NavMenu } from "@/core/shell/nav-menu";

type Health = { status: "ok" } | { status: "unavailable"; failed: string[] };

async function getHealth(): Promise<Health | null> {
  try {
    return await api<Health>("/api/health/ready/", { cache: "no-store" });
  } catch {
    return null;
  }
}

export default async function Home() {
  const [health, identity] = await Promise.all([getHealth(), getIdentity()]);

  return (
    <main className="flex min-h-screen flex-col items-center justify-center gap-8 p-8 font-sans">
      <div className="text-center">
        <h1 className="text-4xl font-bold tracking-tight">{identity.product_name}</h1>
        {identity.tagline && (
          <p className="mt-2 text-zinc-600 dark:text-zinc-400">{identity.tagline}</p>
        )}
      </div>

      <section className="w-full max-w-md rounded-xl border border-zinc-200 p-6 dark:border-zinc-800">
        <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-zinc-500">
          Backend connection
        </h2>
        {health ? (
          <ul className="space-y-1 text-sm">
            <li>
              Status:{" "}
              <span className={health.status === "ok" ? "text-green-600" : "text-amber-600"}>
                {health.status}
              </span>
            </li>
            {health.status === "unavailable" &&
              health.failed.map((name) => <li key={name}>{name}: ❌</li>)}
          </ul>
        ) : (
          <p className="text-sm text-red-600">
            Could not reach <code>{API_URL}/api/health/ready/</code>. Is the Django server running?
          </p>
        )}
      </section>

      <NavMenu />

      <p className="text-xs text-zinc-500">
        API docs: <a className="underline" href={`${API_URL}/api/docs/`}>{API_URL}/api/docs/</a>
        {" · "}
        <Link className="underline" href="/login">
          Sign in
        </Link>
      </p>
    </main>
  );
}
