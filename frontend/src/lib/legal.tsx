import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import NervousSystemBackground from "@/components/NervousSystemBackground";
import { apiGet } from "@/lib/api";

/**
 * Flip a flag to true ONLY after a qualified Indian lawyer has reviewed that document for the operator's real legal duties.
 * Until then the page shows a visible "draft" note. Reviewing means more than reading: the lawyer confirms the business details, the
 * processors listed and the rights described, and the operator then sets the real business details in the server settings.
 */
export const LEGAL_REVIEWED = { terms: false, privacy: false, cookies: false, security: false } as const;

export type LegalConfig = { config: Record<string, string | null>; missing: string[]; response_days: number };

export function useLegalConfig() {
  return useQuery<LegalConfig>({ queryKey: ["legal-config"], queryFn: () => apiGet<LegalConfig>("/public/legal-config"), staleTime: 300_000, retry: false });
}

/** What to show for a business detail that has not been configured yet. Never a made-up value. */
export const placeholderText = (label: string) => `[${label}: not configured yet]`;

export function Ph({ value, label }: { value?: string | null; label: string }) {
  return value ? (
    <span>{value}</span>
  ) : (
    <mark className="rounded px-1" style={{ background: "#F0A63A22", color: "#F0A63A" }} data-testid="legal-placeholder">
      {placeholderText(label)}
    </mark>
  );
}

export function DraftNote({ doc }: { doc: keyof typeof LEGAL_REVIEWED }) {
  if (LEGAL_REVIEWED[doc]) return null;
  return (
    <p className="mt-3 rounded-md border border-border bg-background/40 p-3 text-xs text-muted-foreground" data-testid="legal-draft-note">
      DRAFT, pending review by a qualified Indian lawyer. It describes how the software works and what the operator intends. It is not yet a reviewed legal
      undertaking, and anything marked &ldquo;not configured yet&rdquo; is waiting for the operator&apos;s real details.
    </p>
  );
}

export function LegalShell({ title, doc, testId, children }: { title: string; doc: keyof typeof LEGAL_REVIEWED; testId: string; children: ReactNode }) {
  return (
    <main id="main-content" className="relative min-h-screen px-4 py-10">
      <NervousSystemBackground intensity="ambient" />
      <div className="glass relative z-10 mx-auto max-w-2xl rounded-xl p-8" data-testid={testId}>
        <Link to="/" className="font-heading text-xs tracking-[0.3em] text-muted-foreground">
          ◈ VIDHI
        </Link>
        <h1 className="mt-4 text-2xl">{title}</h1>
        <DraftNote doc={doc} />
        <div className="mt-6 space-y-6">{children}</div>
        <LegalLinks className="mt-10 border-t border-border pt-4" />
      </div>
    </main>
  );
}

export function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section>
      <h2 className="font-heading text-sm uppercase tracking-wider text-muted-foreground">{title}</h2>
      <div className="mt-2 space-y-2 text-sm">{children}</div>
    </section>
  );
}

export function LegalLinks({ className = "" }: { className?: string }) {
  const link = "inline-flex min-h-6 items-center underline-offset-4 hover:underline"; // at least 24 px tall: a small link is hard to hit with a thumb (WCAG 2.5.8)
  return (
    <nav className={`flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground ${className}`} aria-label="Legal and support" data-testid="legal-links">
      <Link to="/terms" className={link}>Terms</Link>
      <Link to="/privacy" className={link}>Privacy</Link>
      <Link to="/cookies" className={link}>Cookies</Link>
      <Link to="/security" className={link}>Security</Link>
      <Link to="/data-rights" className={link}>Your data rights</Link>
      <Link to="/support" className={link}>Contact support</Link>
    </nav>
  );
}