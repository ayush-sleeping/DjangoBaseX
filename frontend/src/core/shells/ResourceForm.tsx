"use client";

/**
 * The Form shell (FRONTEND_PLATFORM § 11, § 15). ONE form, two modes: a `record` present means edit,
 * and the heading names it. A module supplies fields and a submit handler; the shell supplies the
 * layout and the rules every form shares:
 *
 * - Save is disabled until the form is dirty, and while it submits.
 * - Server errors land on their fields (applyServerErrors); anything else is a form-level message in
 *   the footer, left of the actions. An error shows once, on its field; the footer only counts.
 * - Leaving a dirty form asks first: closing the modal confirms; a page unload warns.
 * - As a page or as a modal (create/edit from an index keeps the index's filters and scroll).
 */
import { type ReactNode, useEffect, useId } from "react";
import type { FieldValues, UseFormReturn } from "react-hook-form";

import { Button } from "@/core/components/Button";
import { confirm } from "@/core/components/confirm";
import { Modal } from "@/core/components/Modal";

import { applyServerErrors, dirtyValues, FORM_ERROR } from "./form-errors";

export type ResourceFormProps<T extends FieldValues> = {
  /** "<module>.<resource>.form", rendered as data-page for e2e selectors. */
  pageKey: string;
  form: UseFormReturn<T>;
  /** Receives all values and only the changed ones (send those on a PATCH). Throw to show errors. */
  onSubmit: (values: T, changed: Partial<T>) => Promise<void>;
  /** The resource, singular: "user" → "New user" / "Edit Ada Lovelace". */
  resource: string;
  /** Present in edit mode: the record's human name for the heading. */
  record?: { name: string } | null;
  submitLabel?: string;
  pendingLabel?: string;
  children: ReactNode;
  /** Above the sections: what saving does ("We email a set-your-password link…"). */
  intro?: ReactNode;
  layout?: "page" | "modal";
  /** Modal layout only. */
  open?: boolean;
  onClose?: () => void;
  /** Page layout only: a cancel action (usually a link back). */
  cancel?: ReactNode;
};

export function ResourceForm<T extends FieldValues>({
  pageKey,
  form,
  onSubmit,
  resource,
  record,
  submitLabel,
  pendingLabel = "Saving…",
  children,
  intro,
  layout = "page",
  open = true,
  onClose,
  cancel,
}: ResourceFormProps<T>) {
  const id = useId();
  const { isDirty, isSubmitting, errors, dirtyFields } = form.formState;
  const editing = Boolean(record);
  const heading = editing ? `Edit ${record!.name}` : `New ${resource}`;
  const label = submitLabel ?? (editing ? "Save changes" : `Create ${resource}`);
  const formError = (errors as { root?: { server?: { message?: string } } }).root?.server?.message;
  const fieldErrorCount = Object.keys(errors).filter((key) => key !== "root").length;

  useEffect(() => {
    if (!isDirty) return;
    const warn = (event: BeforeUnloadEvent) => event.preventDefault();
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [isDirty]);

  const submit = form.handleSubmit(async (values) => {
    form.clearErrors(FORM_ERROR);
    try {
      await onSubmit(values, dirtyValues(values, dirtyFields as Partial<Record<keyof T, unknown>>));
    } catch (error) {
      applyServerErrors(form, error);
    }
  });

  const message = formError ? (
    <p role="alert" className="text-destructive">
      {formError}
    </p>
  ) : fieldErrorCount > 0 ? (
    <p role="alert" className="text-destructive">
      {fieldErrorCount === 1 ? "1 field needs attention." : `${fieldErrorCount} fields need attention.`}
    </p>
  ) : null;

  const save = (
    <Button type="submit" form={id} disabled={!isDirty} pending={isSubmitting} pendingLabel={pendingLabel}>
      {label}
    </Button>
  );

  const body = (
    <form id={id} onSubmit={submit} noValidate className="space-y-6" data-page={layout === "page" ? undefined : pageKey}>
      {intro ? <div className="text-sm text-muted-foreground">{intro}</div> : null}
      {children}
    </form>
  );

  if (layout === "modal") {
    const close = async () => {
      if (isSubmitting) return;
      if (isDirty && !(await confirm({ title: "Discard your changes?", confirmLabel: "Discard", tone: "danger" }))) return;
      form.reset();
      onClose?.();
    };
    return (
      <Modal
        open={open}
        onClose={() => void close()}
        title={heading}
        size="lg"
        dismissible={!isSubmitting}
        footerMessage={message}
        footer={
          <>
            <Button variant="secondary" onClick={() => void close()} disabled={isSubmitting}>
              Cancel
            </Button>
            {save}
          </>
        }
      >
        {body}
      </Modal>
    );
  }

  return (
    <main data-page={pageKey} className="mx-auto w-full max-w-3xl space-y-6 p-6">
      <h1 className="text-2xl font-bold tracking-tight">{heading}</h1>
      <div className="rounded-xl border border-border bg-card p-6 text-card-foreground">{body}</div>
      <footer className="flex items-center justify-between gap-4">
        <div className="min-w-0 text-sm">{message}</div>
        <div className="flex shrink-0 gap-2">
          {cancel}
          {save}
        </div>
      </footer>
    </main>
  );
}

/** A titled group of fields. */
export function FormSection({ title, description, children }: { title?: string; description?: ReactNode; children: ReactNode }) {
  return (
    <fieldset className="space-y-4">
      {title ? <legend className="text-sm font-semibold">{title}</legend> : null}
      {description ? <p className="text-sm text-muted-foreground">{description}</p> : null}
      {children}
    </fieldset>
  );
}

const GRID = { 1: "grid gap-4", 2: "grid gap-4 sm:grid-cols-2", 3: "grid gap-4 sm:grid-cols-2 lg:grid-cols-3" } as const;

/** Fields side by side on wide screens, stacked on narrow ones. */
export function FormGrid({ columns = 2, children }: { columns?: 1 | 2 | 3; children: ReactNode }) {
  return <div className={GRID[columns]}>{children}</div>;
}
