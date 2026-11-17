import { afterEach, describe, expect, it, vi } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { callbackErrorKey } from "@/lib/authErrors";
import { I18nProvider } from "@/lib/i18n/I18nProvider";
import { ThemeProvider } from "@/lib/theme";
import Login from "./Login";

function page(url: string, options?: { google: boolean; turnstile_site_key: string | null }) {
  vi.stubGlobal("window", { sessionStorage: { getItem: () => "1", setItem: () => {} }, matchMedia: () => ({ matches: false }), localStorage: { getItem: () => null, setItem: () => {} } });
  vi.stubGlobal("document", { documentElement: { classList: { toggle() {}, add() {}, remove() {} }, style: {}, setAttribute() {} } });
  const qc = new QueryClient();
  if (options) qc.setQueryData(["sign-in-options"], options);
  return renderToStaticMarkup(
    <QueryClientProvider client={qc}>
      <I18nProvider>
        <ThemeProvider>
          <MemoryRouter initialEntries={[url]}>
            <Login />
          </MemoryRouter>
        </ThemeProvider>
      </I18nProvider>
    </QueryClientProvider>,
  );
}
afterEach(() => vi.unstubAllGlobals());

describe("sign-in screen", () => {
  it("offers Continue with Google as a real link when the server has Google set up", () => {
    const html = page("/login", { google: true, turnstile_site_key: null });
    expect(html).toContain('data-testid="auth-google-button"');
    expect(html).toContain('href="/api/auth/google/start"');
    expect(html).not.toContain("auth-google-disabled");
    expect(html.indexOf("auth-google-button")).toBeLessThan(html.indexOf('data-testid="auth-form"'));
  });

  it("shows Google disabled with a plain note when the server has no Google credentials, and no fake path", () => {
    const html = page("/login", { google: false, turnstile_site_key: null });
    expect(html).toContain("auth-google-disabled");
    expect(html).toContain("Google sign-in is not set up on this server yet");
    expect(html).not.toContain("/api/auth/google/start");
  });

  it("shows a loading placeholder, not a button, while the options are loading", () => {
    const html = page("/login");
    expect(html).toContain("auth-google-loading");
    expect(html).not.toContain("auth-google-button");
  });

  it("keeps the email form: email, password, forgot-password link, submit", () => {
    const html = page("/login", { google: false, turnstile_site_key: null });
    for (const id of ["auth-email-input", "auth-password-input", "auth-forgot-link", "auth-submit-button", "auth-mode-toggle"]) expect(html).toContain(id);
    expect(html).toContain('autoComplete="current-password"');
  });

  it("sign-up asks for name, organisation and the privacy tick", () => {
    const html = page("/login?mode=signup", { google: true, turnstile_site_key: null });
    for (const id of ["auth-fullname-input", "auth-org-input", "auth-privacy-checkbox"]) expect(html).toContain(id);
    expect(html).toContain("new-password");
  });

  it("shows an inline, announced message after Google is cancelled or fails", () => {
    const cancelled = page("/login?error=google_cancelled", { google: true, turnstile_site_key: null });
    expect(cancelled).toContain('role="alert"');
    expect(cancelled).toContain("cancelled");
    const failed = page("/login?error=google_failed", { google: true, turnstile_site_key: null });
    expect(failed).toContain("Google sign-in did not work");
    expect(page("/login", { google: true, turnstile_site_key: null })).not.toContain("auth-error");
  });

  it("maps every error code the server can send back", () => {
    expect(callbackErrorKey(null)).toBeNull();
    expect(callbackErrorKey("google_cancelled")).toBe("login.err.cancelled");
    expect(callbackErrorKey("google_failed")).toBe("login.err.google");
    expect(callbackErrorKey("two_step_use_password")).toBe("login.err.twostep");
    expect(callbackErrorKey("suspended")).toBe("login.err.suspended");
    expect(callbackErrorKey("anything_else")).toBe("login.err.google");
  });
});
