"use client";

import { Monitor, Moon, Sun } from "lucide-react";
import { useEffect, useSyncExternalStore } from "react";

import { applyTheme, chooseTheme, currentThemeChoice, subscribeTheme, THEMES, type ThemeChoice } from "./theme";

const ICON = { light: Sun, dark: Moon, system: Monitor } as const;
const LABEL = { light: "Light", dark: "Dark", system: "System" } as const;
// The server cannot read the cookie without making the layout dynamic: nothing is selected there.
const serverSnapshot = () => null;

/** Light / Dark / System. Writes the cookie the pre-paint script reads. */
export function ThemeToggle() {
  const choice = useSyncExternalStore<ThemeChoice | null>(subscribeTheme, currentThemeChoice, serverSnapshot);

  useEffect(() => {
    if (choice !== "system") return;
    const query = window.matchMedia("(prefers-color-scheme: dark)");
    const follow = () => applyTheme("system");
    query.addEventListener("change", follow);
    return () => query.removeEventListener("change", follow);
  }, [choice]);

  return (
    <div role="radiogroup" aria-label="Theme" className="inline-flex rounded-md border border-border p-0.5">
      {THEMES.map((theme) => {
        const Icon = ICON[theme];
        const active = choice === theme;
        return (
          <button
            key={theme}
            type="button"
            role="radio"
            aria-checked={active}
            aria-label={LABEL[theme]}
            title={LABEL[theme]}
            onClick={() => chooseTheme(theme)}
            className={`rounded px-2 py-1 ${active ? "bg-accent text-accent-foreground" : "text-muted-foreground hover:text-foreground"}`}
          >
            <Icon aria-hidden className="size-4" />
          </button>
        );
      })}
    </div>
  );
}
