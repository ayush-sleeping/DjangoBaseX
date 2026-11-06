"use client";

/**
 * <FormField kind=…> (FRONTEND_PLATFORM § 13, § 15): a screen declares WHAT a field is, the registry
 * owns HOW it renders. Bound to react-hook-form through useController, so dirty state, touched state
 * and the field's error come from one form state.
 *
 * Invariants it carries for every field: the label is a real <label>; required ends with an asterisk
 * plus an sr-only "required"; the error shows ONCE, on the field, wired by aria-describedby; the
 * control is aria-invalid while it has one.
 */
import { type ReactNode, useId } from "react";
import { type Control, type FieldPath, type FieldValues, useController } from "react-hook-form";

import { useT } from "@/core/lib/i18n";

import { MultiSelect, type Option, Select } from "../Select";
import { Switch } from "../Switch";
import { inputClass, textareaClass } from "./styles";

export type FieldRenderProps = {
  id: string;
  name: string;
  value: unknown;
  onChange: (value: unknown) => void;
  onBlur: () => void;
  disabled?: boolean;
  invalid: boolean;
  describedBy?: string;
  label: string;
  required?: boolean;
  placeholder?: string;
  options?: readonly Option[];
  autoComplete?: string;
};

type Renderer = (props: FieldRenderProps) => ReactNode;

const str = (v: unknown) => (typeof v === "string" ? v : v == null ? "" : String(v));

function textInput(type: string): Renderer {
  return function TextKind(p) {
    return (
      <input
        id={p.id}
        name={p.name}
        type={type}
        value={str(p.value)}
        onChange={(e) => p.onChange(e.target.value)}
        onBlur={p.onBlur}
        disabled={p.disabled}
        required={p.required}
        placeholder={p.placeholder}
        autoComplete={p.autoComplete}
        aria-invalid={p.invalid || undefined}
        aria-describedby={p.describedBy}
        className={inputClass}
      />
    );
  };
}

const KINDS = new Map<string, Renderer>([
  ["text", textInput("text")],
  ["email", textInput("email")],
  ["password", textInput("password")],
  ["number", textInput("number")],
  [
    "textarea",
    function TextareaKind(p) {
      return (
        <textarea
          id={p.id}
          name={p.name}
          value={str(p.value)}
          onChange={(e) => p.onChange(e.target.value)}
          onBlur={p.onBlur}
          disabled={p.disabled}
          placeholder={p.placeholder}
          aria-invalid={p.invalid || undefined}
          aria-describedby={p.describedBy}
          className={textareaClass}
        />
      );
    },
  ],
  [
    "select",
    function SelectKind(p) {
      return (
        <Select
          id={p.id}
          name={p.name}
          options={p.options ?? []}
          value={p.value == null || p.value === "" ? null : str(p.value)}
          onChange={(v) => p.onChange(v ?? "")}
          disabled={p.disabled}
          required={p.required}
          invalid={p.invalid}
          placeholder={p.placeholder}
        />
      );
    },
  ],
  [
    "multiselect",
    function MultiSelectKind(p) {
      return (
        <MultiSelect
          id={p.id}
          name={p.name}
          options={p.options ?? []}
          value={Array.isArray(p.value) ? p.value.map(str) : []}
          onChange={p.onChange}
          disabled={p.disabled}
          invalid={p.invalid}
          placeholder={p.placeholder}
        />
      );
    },
  ],
  [
    "switch",
    function SwitchKind(p) {
      return <Switch checked={p.value === true} onChange={p.onChange} label={p.label} name={p.name} disabled={p.disabled} />;
    },
  ],
]);

/** Kinds that render their own label (a switch is labelled beside its track). */
const SELF_LABELLED = new Set(["switch"]);

/** A module or plugin adds a kind; core's kinds cannot be replaced by accident. */
export function registerFieldKind(kind: string, render: Renderer, { selfLabelled = false } = {}): void {
  if (KINDS.has(kind)) throw new Error(`FormField kind "${kind}" is already registered`);
  KINDS.set(kind, render);
  if (selfLabelled) SELF_LABELLED.add(kind);
}

export function fieldKinds(): string[] {
  return [...KINDS.keys()].sort();
}

export function FormField<T extends FieldValues>({
  control,
  name,
  kind,
  label,
  hint,
  required,
  disabled,
  placeholder,
  options,
  autoComplete,
}: {
  control: Control<T>;
  name: FieldPath<T>;
  kind: string;
  label: string;
  hint?: ReactNode;
  required?: boolean;
  disabled?: boolean;
  placeholder?: string;
  options?: readonly Option[];
  autoComplete?: string;
}) {
  const t = useT("common");
  const render = KINDS.get(kind);
  if (!render) throw new Error(`FormField: unknown kind "${kind}" (known: ${fieldKinds().join(", ")})`);
  const { field, fieldState } = useController({ control, name });
  const id = useId();
  const errorId = `${id}-error`;
  const hintId = `${id}-hint`;
  const message = fieldState.error?.message;
  const describedBy = [message ? errorId : null, hint ? hintId : null].filter(Boolean).join(" ") || undefined;

  return (
    <div className="space-y-1">
      {SELF_LABELLED.has(kind) ? null : (
        <label htmlFor={id} className="block text-sm font-medium">
          {label}
          {required ? (
            <>
              <span aria-hidden className="text-destructive"> *</span>
              <span className="sr-only"> {t("required")}</span>
            </>
          ) : null}
        </label>
      )}
      {render({
        id,
        name: field.name,
        value: field.value,
        onChange: field.onChange,
        onBlur: field.onBlur,
        disabled: disabled || field.disabled,
        invalid: Boolean(message),
        describedBy,
        label,
        required,
        placeholder,
        options,
        autoComplete,
      })}
      {hint ? (
        <p id={hintId} className="text-xs text-muted-foreground">
          {hint}
        </p>
      ) : null}
      {message ? (
        <p id={errorId} className="text-xs text-destructive">
          {message}
        </p>
      ) : null}
    </div>
  );
}
