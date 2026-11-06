"use client";

/** An always-labelled switch (FRONTEND_PLATFORM § 13): a toggle never appears without its label. */
import { Field, Label, Switch as HeadlessSwitch } from "@headlessui/react";

export function Switch({
  checked,
  onChange,
  label,
  name,
  disabled,
  description,
}: {
  checked: boolean;
  onChange: (checked: boolean) => void;
  label: string;
  name?: string;
  disabled?: boolean;
  description?: string;
}) {
  return (
    <Field disabled={disabled} className="flex items-center gap-3">
      <HeadlessSwitch
        checked={checked}
        onChange={onChange}
        name={name}
        className="group relative inline-flex h-5 w-9 shrink-0 items-center rounded-full bg-input transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring data-checked:bg-primary data-disabled:opacity-50"
      >
        <span aria-hidden className="size-4 translate-x-0.5 rounded-full bg-background shadow transition-transform group-data-checked:translate-x-4.5" />
      </HeadlessSwitch>
      <Label className="text-sm">
        {label}
        {description ? <span className="block text-xs text-muted-foreground">{description}</span> : null}
      </Label>
    </Field>
  );
}
