"use client";

/**
 * Re-applies the title template after client navigation (FRONTEND_PLATFORM § 17).
 *
 * The App Router re-asserts static metadata when the route changes, which can leave a bare page
 * title or none. On every pathname change this puts `<page> — <product>` back, rather than making
 * every page dynamic just to compute a title. A title already ending in the suffix is left alone,
 * so it never doubles up.
 */
import { usePathname } from "next/navigation";
import { useEffect } from "react";

export function applyTitle(productName: string): void {
  const current = document.title.trim();
  if (!current) {
    document.title = productName;
    return;
  }
  if (current === productName || current.endsWith(` — ${productName}`)) return;
  document.title = `${current} — ${productName}`;
}

export function TitleSync({ productName }: { productName: string }) {
  const pathname = usePathname();
  useEffect(() => {
    applyTitle(productName);
    // Next writes its metadata after the route commits: assert once more after that.
    const id = setTimeout(() => applyTitle(productName), 0);
    return () => clearTimeout(id);
  }, [pathname, productName]);
  return null;
}
