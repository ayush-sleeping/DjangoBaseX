/**
 * Server errors onto a react-hook-form form (FRONTEND_PLATFORM § 15).
 *
 * A `validation` error's fields[].path ("email", "lines.2.quantity") becomes that field's error. A
 * path the form does not hold becomes a FORM-LEVEL error — never dropped, because a message nobody
 * sees is a save that silently failed. Focus moves to the first errored field.
 */
import type { FieldPath, FieldValues, UseFormReturn } from "react-hook-form";

import { isApiError, messageFor } from "@/core/lib/api/errors";

/** The form-level error's key. */
export const FORM_ERROR = "root.server" as const;

function hasPath(values: unknown, path: string): boolean {
  let node: unknown = values;
  for (const part of path.split(".")) {
    if (node === null || typeof node !== "object" || !(part in (node as Record<string, unknown>))) return false;
    node = (node as Record<string, unknown>)[part];
  }
  return true;
}

/**
 * Returns how many field errors were applied. `failed` is the translated form-level message for an
 * error the API did not describe (a network failure): this module renders no copy of its own.
 */
export function applyServerErrors<T extends FieldValues>(form: UseFormReturn<T>, error: unknown, failed: string): number {
  const values = form.getValues();
  const formLevel: string[] = [];
  let first: string | null = null;
  let applied = 0;

  if (isApiError(error) && error.kind === "validation") {
    const byPath = new Map<string, string[]>();
    for (const field of error.fields) byPath.set(field.path, [...(byPath.get(field.path) ?? []), field.message]);
    for (const [path, messages] of byPath) {
      if (hasPath(values, path)) {
        form.setError(path as FieldPath<T>, { type: "server", message: messages.join(" ") });
        first ??= path;
        applied += 1;
      } else {
        formLevel.push(...messages.map((m) => `${path}: ${m}`));
      }
    }
    formLevel.push(...error.nonField);
    if (!applied && !formLevel.length) formLevel.push(messageFor(error));
  } else {
    formLevel.push(isApiError(error) ? messageFor(error) : failed);
  }

  if (formLevel.length) form.setError(FORM_ERROR, { type: "server", message: formLevel.join(" ") });
  if (first) form.setFocus(first as FieldPath<T>);
  return applied;
}

/** Only the fields the user changed: a PATCH that sends untouched fields clobbers other editors. */
export function dirtyValues<T extends FieldValues>(values: T, dirty: Partial<Record<keyof T, unknown>>): Partial<T> {
  const out: Partial<T> = {};
  for (const key of Object.keys(dirty) as (keyof T)[]) {
    if (dirty[key]) out[key] = values[key];
  }
  return out;
}
