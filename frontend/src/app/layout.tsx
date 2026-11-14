import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import { headers } from "next/headers";
import { getIdentity } from "@/core/lib/identity";
import { brandCss } from "@/core/lib/security/brand";
import { Providers } from "@/core/providers/Providers";
import { ThemeScript } from "@/core/theme/ThemeScript";
import { TitleSync } from "@/core/theme/TitleSync";

import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

// The product's name comes from the API (CONFIGURATION.md § 7): re-read at most once a minute, so a
// rename is a backend restart, not a frontend rebuild. (The fetch's own 60 s cache in getIdentity is
// what bounds it now: the layout reads x-nonce, so every page renders per request.)
export const revalidate = 60;

export async function generateMetadata(): Promise<Metadata> {
  const { product_name, tagline } = await getIdentity();
  return {
    title: { template: `%s — ${product_name}`, default: product_name },
    description: tagline || undefined,
  };
}

export default async function RootLayout({ children }: LayoutProps<"/">) {
  // The platform's locale (and timezone), from the same cached public config as the product name:
  // <html lang> and signed-out formatting follow it; a signed-in user's own comes from bootstrap.
  const { locale, timezone, brand, product_name } = await getIdentity();
  // The per-request CSP nonce (src/proxy.ts). Reading it makes every page dynamic, which a nonce
  // requires: Next tags its own scripts from the request's CSP header, and we tag ours.
  const nonce = (await headers()).get("x-nonce") ?? undefined;
  // First paint is branded: numbers re-validated into oklch() (§ 17); "" leaves the stylesheet's own.
  const brandStyles = brandCss(brand);
  return (
    // suppressHydrationWarning: ThemeScript sets data-theme on <html> before React hydrates.
    <html
      lang={locale}
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
      suppressHydrationWarning
    >
      <head>
        <ThemeScript nonce={nonce} />
        {brandStyles ? <style>{brandStyles}</style> : null}
      </head>
      <body className="min-h-full flex flex-col bg-background text-foreground">
        <TitleSync productName={product_name} />
        <Providers platform={{ locale, timezone }}>{children}</Providers>
      </body>
    </html>
  );
}
