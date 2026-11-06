import { themeScript } from "./theme";

/**
 * Applies the stored theme before the first paint (FRONTEND_PLATFORM § 16). Rendered in the root
 * layout's <head>; <html> carries suppressHydrationWarning because this script sets data-theme
 * before React hydrates. BUILD_ORDER 8.5 adds the CSP nonce.
 */
export function ThemeScript() {
  // ui-contract: the one inline script; its body is a constant built by themeScript(), never input.
  return <script dangerouslySetInnerHTML={{ __html: themeScript() }} />;
}
