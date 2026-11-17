import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import NervousSystemBackground from "@/components/NervousSystemBackground";

/** The centred glass card used by the sign-in style pages (forgot / reset password, accept invitation). */
export default function AuthCard({
  title,
  subtitle,
  children,
  testId,
}: {
  title: string;
  subtitle?: string;
  children: ReactNode;
  testId?: string;
}) {
  return (
    <main id="main-content" className="relative flex min-h-screen items-center justify-center px-4">
      <NervousSystemBackground intensity="ambient" />
      <div className="glass relative z-10 w-full max-w-md rounded-xl p-8 vidhi-rise" data-testid={testId}>
        <Link to="/" className="font-heading text-xs tracking-[0.3em] text-muted-foreground">
          ◈ VIDHI
        </Link>
        <h1 className="mt-4 text-2xl">{title}</h1>
        {subtitle && <p className="mt-1 text-sm text-muted-foreground">{subtitle}</p>}
        <div className="mt-6">{children}</div>
      </div>
    </main>
  );
}
