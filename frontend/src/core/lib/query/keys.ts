/**
 * Query keys are the contract between readers and writers (FRONTEND_PLATFORM.md § 4):
 * `[root, kind, context, ...params]`. A resource declares its factory once with `defineKeys`;
 * a plugin's root starts with its plugin key ("billing.invoices"), the same namespace rule as
 * permissions and routes. Invalidating `[root]` reaches every query of that resource in every
 * context.
 */
export type QueryKey = readonly unknown[];

type Factories = Record<string, (...args: never[]) => readonly unknown[]>;

export type Keys<F extends Factories> = {
  readonly root: readonly [string];
  readonly rootName: string;
} & {
  readonly [K in keyof F]: (...args: Parameters<F[K]>) => readonly [string, ...ReturnType<F[K]>];
};

const ROOTS = new Set<string>();

/** Exposed for the query-keys guard test; never for application code. */
export function registeredRoots(): string[] {
  return [...ROOTS].sort();
}

export function defineKeys<F extends Factories>(root: string, factories: F): Keys<F> {
  if (!/^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)*$/.test(root)) {
    throw new Error(`defineKeys: root "${root}" must be dotted lowercase, e.g. "users" or "billing.invoices"`);
  }
  if (ROOTS.has(root)) throw new Error(`defineKeys: root "${root}" is already defined`);
  ROOTS.add(root);
  const keys: Record<string, unknown> = { root: [root] as const, rootName: root };
  for (const [name, make] of Object.entries(factories)) {
    keys[name] = (...args: never[]) => [root, ...make(...args)] as const;
  }
  return keys as Keys<F>;
}
