import { themeScript } from "./theme";

/**
 * Applies the stored theme before the first paint (FRONTEND_PLATFORM § 16). Rendered in the root
 * layout's <head>; <html> carries suppressHydrationWarning because this script sets data-theme
 * before React hydrates. `nonce` is the request's CSP nonce (src/proxy.ts, § 18): under
 * 'strict-dynamic' an inline script without it does not run.
 */
export function ThemeScript({ nonce }: { nonce?: string }) {
  // ui-contract: the one inline script; its body is a constant built by themeScript(), never input.
  return <script nonce={nonce} dangerouslySetInnerHTML={{ __html: themeScript() }} />;
}
