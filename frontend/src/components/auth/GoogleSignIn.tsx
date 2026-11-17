import { useEffect, useState } from "react";
import { Button, buttonVariants } from "@/components/ui/button";
import { useT } from "@/lib/i18n/I18nProvider";
import { isNative } from "@/lib/native";

export type GoogleState = "loading" | "enabled" | "disabled";

function GoogleMark() {
  return (
    <svg viewBox="0 0 48 48" className="size-5" aria-hidden="true">
      <path fill="#EA4335" d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5z" />
      <path fill="#4285F4" d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z" />
      <path fill="#FBBC05" d="M10.53 28.59c-.48-1.45-.76-2.99-.76-4.59s.27-3.14.76-4.59l-7.98-6.19C.92 16.46 0 20.12 0 24c0 3.88.92 7.54 2.56 10.78l7.97-6.19z" />
      <path fill="#34A853" d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.15 1.45-4.92 2.3-8.16 2.3-6.26 0-11.57-4.22-13.47-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z" />
    </svg>
  );
}

/**
 * "Continue with Google". It is a real link to the server's /api/auth/google/start (the server does the OAuth with PKCE, state and nonce);
 * when the server has no Google credentials the button is shown disabled with a plain note, never as a fake sign-in.
 */
export default function GoogleSignIn({ state }: { state: GoogleState }) {
  const t = useT();
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    // Coming back with the browser's back button restores this page as it was: do not leave the button spinning.
    const reset = (e: PageTransitionEvent) => e.persisted && setBusy(false);
    window.addEventListener("pageshow", reset);
    return () => window.removeEventListener("pageshow", reset);
  }, []);

  // Google sign-in is a browser redirect flow that ends on the server's own page; the Android app signs in with email and password.
  if (isNative()) return null;
  if (state === "loading") return <div className="h-11 rounded-full vidhi-sweep bg-muted/40" aria-hidden="true" data-testid="auth-google-loading" />;
  if (state === "disabled")
    return (
      <div>
        <Button type="button" variant="outline" size="lg" className="w-full gap-3" disabled data-testid="auth-google-disabled">
          <GoogleMark />
          {t("login.google")}
        </Button>
        <p className="mt-2 text-center text-xs text-muted-foreground" data-testid="auth-google-off-note">
          {t("login.google.off")}
        </p>
      </div>
    );
  return (
    <div>
      <a
        href="/api/auth/google/start"
        onClick={(e) => {
          // a new-tab click (Ctrl/Cmd/Shift or middle button) leaves this page as it is, so it must not spin
          if (!e.ctrlKey && !e.metaKey && !e.shiftKey && !e.altKey && e.button === 0) setBusy(true);
        }}
        aria-busy={busy || undefined}
        className={buttonVariants({ variant: "outline", size: "lg", className: "w-full gap-3" })}
        data-testid="auth-google-button"
      >
        {busy ? <span className="spinner-ring size-4" aria-hidden="true" /> : <GoogleMark />}
        {busy ? t("login.working") : t("login.google")}
      </a>
      <p className="mt-2 text-center text-[11px] text-muted-foreground">{t("login.google.note")}</p>
    </div>
  );
}
