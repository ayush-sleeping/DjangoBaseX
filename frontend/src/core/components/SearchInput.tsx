"use client";

/**
 * The one search box (FRONTEND_PLATFORM § 6, § 13): it owns the debounce and the minimum length, so
 * every list searches the same way and no list fires a request per keystroke.
 */
import { Search } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { inputClass } from "./form/styles";

export const SEARCH_DEBOUNCE_MS = 300;
export const SEARCH_MIN_LENGTH = 2;

export function SearchInput({
  value,
  onSearch,
  label = "Search",
  placeholder = "Search…",
  debounceMs = SEARCH_DEBOUNCE_MS,
  minLength = SEARCH_MIN_LENGTH,
}: {
  /** The applied search (from the URL). */
  value: string;
  /** Called with the trimmed term once typing settles; "" when it drops below minLength. */
  onSearch: (term: string) => void;
  label?: string;
  placeholder?: string;
  debounceMs?: number;
  minLength?: number;
}) {
  const [draft, setDraft] = useState(value);
  const applied = useRef(value);

  useEffect(() => {
    const term = draft.trim();
    const effective = term.length >= minLength ? term : "";
    if (effective === applied.current) return;
    const timer = setTimeout(() => {
      applied.current = effective;
      onSearch(effective);
    }, debounceMs);
    return () => clearTimeout(timer);
  }, [draft, minLength, debounceMs, onSearch]);

  return (
    <label className="relative block w-full max-w-xs">
      <span className="sr-only">{label}</span>
      <Search aria-hidden className="pointer-events-none absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
      <input type="search" value={draft} placeholder={placeholder} onChange={(e) => setDraft(e.target.value)} className={`${inputClass} pl-8`} />
    </label>
  );
}
