import type { Metadata } from "next";
import Link from "next/link";

import { ForgotPasswordForm } from "./forgot-password-form";

export const metadata: Metadata = {
  title: "Forgot password — DjangoBaseX",
};

export default function ForgotPasswordPage() {
  return (
    <main className="flex min-h-screen flex-col items-center justify-center gap-6 p-8 font-sans">
      <h1 className="text-2xl font-bold tracking-tight">Forgot password</h1>
      <ForgotPasswordForm />
      <Link className="text-xs text-zinc-500 underline" href="/login">
        Back to sign in
      </Link>
    </main>
  );
}
