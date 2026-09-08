import { api, API_URL } from "@/lib/api";

type Health = {
  status: "ok" | "degraded";
  app: string;
  checks: Record<string, boolean>;
};

async function getHealth(): Promise<Health | null> {
  try {
    return await api<Health>("/api/health/", { cache: "no-store" });
  } catch {
    return null;
  }
}

export default async function Home() {
  const health = await getHealth();

  return (
    <main className="flex min-h-screen flex-col items-center justify-center gap-8 p-8 font-sans">
      <div className="text-center">
        <h1 className="text-4xl font-bold tracking-tight">DjangoBaseX</h1>
        <p className="mt-2 text-zinc-600 dark:text-zinc-400">
          Django 5 + Django REST Framework &nbsp;↔&nbsp; Next.js 16
        </p>
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
            {Object.entries(health.checks).map(([name, ok]) => (
              <li key={name}>
                {name}: {ok ? "✅" : "❌"}
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-sm text-red-600">
            Could not reach <code>{API_URL}/api/health/</code>. Is the Django server running?
          </p>
        )}
      </section>

      <p className="text-xs text-zinc-500">
        API docs: <a className="underline" href={`${API_URL}/api/docs/`}>{API_URL}/api/docs/</a>
      </p>
    </main>
  );
}
