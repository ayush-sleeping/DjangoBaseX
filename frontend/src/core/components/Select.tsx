"use client";

/**
 * Select, MultiSelect and AsyncSelect (FRONTEND_PLATFORM § 13): custom, SEARCHABLE BY DEFAULT, never
 * a native <select> (which cannot be searched, styled or loaded asynchronously). Built on Headless
 * UI's Combobox, so keyboard navigation and the ARIA combobox pattern come from one audited place.
 *
 * Each takes `name`: Headless UI renders hidden inputs, so a plain <form> + FormData still works.
 */
import { Combobox, ComboboxButton, ComboboxInput, ComboboxOption, ComboboxOptions } from "@headlessui/react";
import { Check, ChevronsUpDown, X } from "lucide-react";
import { useMemo, useState } from "react";

import type { QueryKey } from "@/core/lib/query/keys";
import { useApiQuery } from "@/core/lib/query/use-api-query";

import { inputClass } from "./form/styles";

export type Option = { value: string; label: string; disabled?: boolean; hint?: string };

type Common = {
  /** The accessible name when no visible <label> points at the control. */
  label?: string;
  name?: string;
  placeholder?: string;
  disabled?: boolean;
  required?: boolean;
  invalid?: boolean;
  id?: string;
};

export function matchOptions(options: readonly Option[], query: string): Option[] {
  const q = query.trim().toLowerCase();
  if (!q) return [...options];
  return options.filter((o) => o.label.toLowerCase().includes(q) || o.value.toLowerCase().includes(q));
}

function OptionList({ options, empty }: { options: readonly Option[]; empty: string }) {
  return (
    <ComboboxOptions
      anchor="bottom start"
      className="z-50 mt-1 max-h-60 w-(--input-width) overflow-y-auto rounded-md border border-border bg-popover p-1 text-sm text-popover-foreground shadow-md empty:invisible"
    >
      {options.length === 0 ? (
        <div className="px-2 py-1.5 text-muted-foreground">{empty}</div>
      ) : (
        options.map((option) => (
          <ComboboxOption
            key={option.value}
            value={option.value}
            disabled={option.disabled}
            className="group flex cursor-default items-center gap-2 rounded px-2 py-1.5 data-disabled:opacity-50 data-focus:bg-accent data-focus:text-accent-foreground"
          >
            <Check aria-hidden className="invisible size-4 group-data-selected:visible" />
            <span className="min-w-0 flex-1 truncate">{option.label}</span>
            {option.hint ? <span className="text-xs text-muted-foreground">{option.hint}</span> : null}
          </ComboboxOption>
        ))
      )}
    </ComboboxOptions>
  );
}

function labelOf(options: readonly Option[], value: string | null): string {
  return options.find((o) => o.value === value)?.label ?? "";
}

export function Select({
  options,
  value,
  onChange,
  label,
  name,
  placeholder = "Choose…",
  disabled,
  required,
  invalid,
  id,
}: Common & { options: readonly Option[]; value: string | null; onChange: (value: string | null) => void }) {
  const [query, setQuery] = useState("");
  const shown = useMemo(() => matchOptions(options, query), [options, query]);
  return (
    <Combobox value={value} onChange={(v: string | null) => onChange(v)} onClose={() => setQuery("")} name={name} disabled={disabled} immediate>
      <div className="relative">
        <ComboboxInput
          id={id}
          aria-label={label}
          aria-required={required || undefined}
          aria-invalid={invalid || undefined}
          placeholder={placeholder}
          displayValue={(v: string | null) => labelOf(options, v)}
          onChange={(e) => setQuery(e.target.value)}
          className={`${inputClass} pr-8`}
        />
        <ComboboxButton aria-label="Show options" className="absolute inset-y-0 right-0 flex items-center px-2 text-muted-foreground">
          <ChevronsUpDown aria-hidden className="size-4" />
        </ComboboxButton>
      </div>
      <OptionList options={shown} empty="No matches" />
    </Combobox>
  );
}

export function MultiSelect({
  options,
  value,
  onChange,
  label,
  name,
  placeholder = "Add…",
  disabled,
  invalid,
  id,
}: Common & { options: readonly Option[]; value: string[]; onChange: (value: string[]) => void }) {
  const [query, setQuery] = useState("");
  const shown = useMemo(() => matchOptions(options, query), [options, query]);
  return (
    <Combobox value={value} onChange={(v: string[]) => onChange(v)} onClose={() => setQuery("")} multiple name={name} disabled={disabled} immediate>
      <div className={`${inputClass} flex h-auto min-h-(--control-h) flex-wrap items-center gap-1 py-1`}>
        {value.map((v) => (
          <span key={v} className="inline-flex items-center gap-1 rounded bg-secondary px-1.5 py-0.5 text-xs text-secondary-foreground">
            {labelOf(options, v) || v}
            <button type="button" aria-label={`Remove ${labelOf(options, v) || v}`} disabled={disabled} onClick={() => onChange(value.filter((x) => x !== v))}>
              <X aria-hidden className="size-3" />
            </button>
          </span>
        ))}
        <ComboboxInput
          id={id}
          aria-label={label}
          aria-invalid={invalid || undefined}
          placeholder={value.length ? "" : placeholder}
          onChange={(e) => setQuery(e.target.value)}
          className="min-w-24 flex-1 bg-transparent text-sm outline-none"
        />
      </div>
      <OptionList options={shown} empty="No matches" />
    </Combobox>
  );
}

/**
 * Options loaded from the server as the user types, through the one data layer (useApiQuery), so
 * results are cached and cancelled like any other query. `selectedLabel` names the current value
 * before any search has run.
 */
export function AsyncSelect({
  value,
  onChange,
  queryKey,
  load,
  selectedLabel,
  minLength = 1,
  label,
  name,
  placeholder = "Search…",
  disabled,
  invalid,
  id,
}: Common & {
  value: string | null;
  onChange: (value: string | null, option: Option | null) => void;
  /** A defineKeys factory for the search: (query) → key. */
  queryKey: (query: string) => QueryKey;
  load: (query: string, signal: AbortSignal) => Promise<Option[]>;
  selectedLabel?: string;
  minLength?: number;
}) {
  const [query, setQuery] = useState("");
  const enabled = query.trim().length >= minLength;
  const result = useApiQuery<Option[]>(queryKey(query.trim()), (signal) => load(query.trim(), signal), { enabled });
  const options = result.data ?? [];
  const empty = !enabled ? `Type ${minLength} or more characters` : result.isLoading ? "Searching…" : result.showError ? "Couldn't search — try again" : "No matches";
  return (
    <Combobox
      value={value}
      onChange={(v: string | null) => onChange(v, options.find((o) => o.value === v) ?? null)}
      onClose={() => setQuery("")}
      name={name}
      disabled={disabled}
      immediate
    >
      <ComboboxInput
        id={id}
        aria-label={label}
        aria-invalid={invalid || undefined}
        placeholder={placeholder}
        displayValue={(v: string | null) => options.find((o) => o.value === v)?.label ?? (v ? selectedLabel ?? v : "")}
        onChange={(e) => setQuery(e.target.value)}
        className={inputClass}
      />
      <OptionList options={enabled ? options : []} empty={empty} />
    </Combobox>
  );
}
