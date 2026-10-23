import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import { getIdentity } from "@/core/lib/identity";

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
// rename is a backend restart, not a frontend rebuild.
export const revalidate = 60;

export async function generateMetadata(): Promise<Metadata> {
  const { product_name, tagline } = await getIdentity();
  return {
    title: { template: `%s — ${product_name}`, default: product_name },
    description: tagline || undefined,
  };
}

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="en"
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
    >
      <body className="min-h-full flex flex-col">{children}</body>
    </html>
  );
}
