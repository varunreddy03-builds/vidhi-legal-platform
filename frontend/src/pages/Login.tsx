import { useEffect, useRef, useState } from "react";
import { useNavigate, useSearchParams, Link } from "react-router-dom";
import { useMutation, useQuery } from "@tanstack/react-query";
import { toast } from "sonner";
import NervousSystemBackground from "@/components/NervousSystemBackground";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ApiError, apiGet, apiPost } from "@/lib/api";
import type { UserOut } from "@/lib/types";
import { beginSession } from "@/lib/session";
import { describe } from "@/lib/interaction";
import { useT } from "@/lib/i18n/I18nProvider";
import { LanguageMenu, ThemeToggle } from "@/components/AppearanceControls";
import { LegalLinks } from "@/lib/legal";
import GoogleSignIn from "@/components/auth/GoogleSignIn";
import ServerNote from "@/components/native/ServerNote";
import { callbackErrorKey } from "@/lib/authErrors";

/** Only same-site paths are followed after sign-in (never an outside address). */
function safeNext(v: string | null): string {
  return v && /^\/[A-Za-z0-9/_-]*$/.test(v) && !v.startsWith("//") ? v : "/start";
}

export default function Login() {
  const t = useT();
  const [params] = useSearchParams();
  const [mode, setMode] = useState<"login" | "signup">(
    params.get("mode") === "signup" ? "signup" : "login",
  );
  const [email, setEmail] = useState(params.get("email") ?? ""); // an invitation link brings the address and the code
  const [inviteCode, setInviteCode] = useState(params.get("invite") ?? "");
  const [password, setPassword] = useState("");
  const [fullName, setFullName] = useState("");
  const [orgName, setOrgName] = useState("");
  const [privacy, setPrivacy] = useState(false);
  const [needOtp, setNeedOtp] = useState(false);
  const [trap, setTrap] = useState(""); // a field people never see; bots fill it in
  const [token, setToken] = useState<string | null>(null); // Cloudflare Turnstile answer, when bot protection is on
  const opened = useRef(Date.now());
  const widget = useRef<HTMLDivElement>(null);
  const [otp, setOtp] = useState("");
  const [formError, setFormError] = useState<string | null>(null);
  const [cbDismissed, setCbDismissed] = useState(false); // the Google error in the address is old news once they try something else
  const navigate = useNavigate();
  const options = useQuery({ queryKey: ["sign-in-options"], queryFn: () => apiGet<{ google: boolean; turnstile_site_key: string | null; signup_mode?: "open" | "invite" }>("/auth/options"), retry: false });
  const siteKey = options.data?.turnstile_site_key ?? null;
  useEffect(() => {
    // Load Cloudflare's bot check only when it is configured and the person is signing up.
    if (!siteKey || mode !== "signup" || !widget.current) return;
    const el = widget.current;
    const render = () => (window as unknown as { turnstile?: { render: (e: HTMLElement, o: object) => void } }).turnstile?.render(el, { sitekey: siteKey, callback: (t: string) => setToken(t), "expired-callback": () => setToken(null) });
    if ((window as unknown as { turnstile?: unknown }).turnstile) return render();
    const s = document.createElement("script");
    s.src = "https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit";
    s.async = true;
    s.onload = render;
    document.head.appendChild(s);
  }, [siteKey, mode]);
  const comeBackKey = callbackErrorKey(params.get("error"));
  const inviteOnlyNote = params.get("error") === "invite_only" && !cbDismissed ? "VIDHI is invite-only during the pilot. Use the invitation you were sent, with the same email address." : null;
  const shownError = formError ?? inviteOnlyNote ?? (comeBackKey && !cbDismissed ? t(comeBackKey) : null);
  const inviteOnly = options.data?.signup_mode === "invite";

  const mutation = useMutation({
    mutationFn: async () => {
      setFormError(null);
      setCbDismissed(true);
      return mode === "signup"
        ? apiPost<UserOut>("/auth/signup", {
            email,
            password,
            full_name: fullName,
            organization_name: orgName,
            accept_privacy: privacy,
            website: trap,
            elapsed_ms: Date.now() - opened.current,
            ...(token ? { turnstile_token: token } : {}),
            ...(inviteCode.trim() ? { invite_code: inviteCode.trim() } : {}),
          })
        : apiPost<UserOut>("/auth/login", { email, password, ...(needOtp ? { otp } : {}) });
    },
    onSuccess: async (user) => {
      await beginSession();
      toast.success(`Signed in as ${user.email}`);
      navigate(safeNext(params.get("next")), { replace: true });
    },
    onError: (err) => {
      if (err instanceof ApiError && err.status === 428) {
        setNeedOtp(true); // the password was right: ask for the second step
        return;
      }
      setFormError(describe(err)); // shown inline, next to the form, and announced to screen readers
    },
  });

  return (
    <main id="main-content" className="relative flex min-h-screen items-center justify-center px-4">
      <NervousSystemBackground intensity="ambient" />
      <div className="absolute right-4 top-4 z-10 flex items-center gap-2">
        <LanguageMenu />
        <ThemeToggle />
      </div>
      <div className="glass relative z-10 w-full max-w-md rounded-xl p-8 vidhi-rise">
        <div className="flex items-center justify-between">
          <Link to="/" className="font-heading text-xs tracking-[0.3em] text-muted-foreground transition-colors hover:text-foreground">
            ◈ VIDHI
          </Link>
        </div>
        <hr className="gold-rule mt-4" />
        <h1 className="mt-5 text-2xl">
          {mode === "signup" ? t("login.signup.title") : t("login.signin.title")}
        </h1>
        <p className="mt-1 text-sm text-muted-foreground">
          {mode === "signup" ? t("login.signup.sub") : t("login.signin.sub")}
        </p>

        {!options.isError && (
        <div className="mt-6" data-testid="auth-google-block">
          <GoogleSignIn state={options.isPending ? "loading" : options.data?.google ? "enabled" : "disabled"} />
          <div className="my-5 flex items-center gap-3 text-xs text-muted-foreground">
            <span className="h-px flex-1 bg-border" />
            {t("login.or")}
            <span className="h-px flex-1 bg-border" />
          </div>
        </div>
        )}

        <form
          className="space-y-4"
          onSubmit={(e) => {
            e.preventDefault();
            mutation.mutate();
          }}
          data-testid="auth-form"
        >
          {shownError && (
            <p role="alert" className="rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm text-foreground" data-testid="auth-error">
              {shownError}
            </p>
          )}
          {mode === "signup" && inviteOnly && (
            <div className="space-y-1.5">
              <Label htmlFor="invite_code">Invitation code</Label>
              <Input id="invite_code" value={inviteCode} onChange={(e) => setInviteCode(e.target.value)} autoComplete="off" required data-testid="auth-invite-input" />
              <p className="text-xs text-muted-foreground">VIDHI is invite-only during the pilot. Use the code from your invitation, with the email address it was sent to.</p>
            </div>
          )}
          {mode === "signup" && (
            <>
              <div className="space-y-1.5">
                <Label htmlFor="full_name">{t("login.name")}</Label>
                <Input
                  id="full_name"
                  value={fullName}
                  onChange={(e) => setFullName(e.target.value)}
                  required
                  data-testid="auth-fullname-input"
                />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="org">{t("login.org")}</Label>
                <Input
                  id="org"
                  value={orgName}
                  onChange={(e) => setOrgName(e.target.value)}
                  required
                  data-testid="auth-org-input"
                />
              </div>
            </>
          )}
          <div className="space-y-1.5">
            <Label htmlFor="email">{t("login.email")}</Label>
            <Input
              id="email"
              type="email"
              autoComplete="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              data-testid="auth-email-input"
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="password">{t("login.password")}</Label>
            <Input
              id="password"
              type="password"
              autoComplete={mode === "signup" ? "new-password" : "current-password"}
              minLength={8}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              data-testid="auth-password-input"
            />
            {mode === "signup" && (
              <p className="text-xs text-muted-foreground">{t("login.password.hint")}</p>
            )}
            {mode === "login" && (
              <Link
                to="/forgot-password"
                className="block text-xs text-muted-foreground transition-colors hover:text-foreground"
                data-testid="auth-forgot-link"
              >
                {t("login.forgot")}
              </Link>
            )}
          </div>
          {needOtp && mode === "login" && (
            <div className="space-y-1.5" data-testid="auth-otp-step">
              <Label htmlFor="otp">{t("login.otp.label")}</Label>
              <Input
                id="otp"
                inputMode="numeric"
                autoComplete="one-time-code"
                autoFocus
                value={otp}
                onChange={(e) => setOtp(e.target.value)}
                required
                data-testid="auth-otp-input"
              />
              <p className="text-xs text-muted-foreground">{t("login.otp.hint")}</p>
            </div>
          )}
          {mode === "signup" && (
            <input type="text" name="website" value={trap} onChange={(e) => setTrap(e.target.value)} tabIndex={-1} autoComplete="off" aria-hidden="true" className="absolute -left-[9999px] h-0 w-0 opacity-0" />
          )}
          {mode === "signup" && siteKey && <div ref={widget} data-testid="turnstile-widget" />}
          {mode === "signup" && (
            <label className="flex items-start gap-2 text-xs text-muted-foreground">
              <input
                type="checkbox"
                checked={privacy}
                onChange={(e) => setPrivacy(e.target.checked)}
                className="mt-0.5"
                data-testid="auth-privacy-checkbox"
              />
              <span>
                {t("login.privacy.pre")}{" "}
                <Link to="/privacy" target="_blank" className="underline">
                  {t("login.privacy.link")}
                </Link>
                .
              </span>
            </label>
          )}
          <Button
            type="submit"
            className="w-full"
            loading={mutation.isPending}
            disabled={mutation.isPending || (mode === "signup" && (!privacy || (!!siteKey && !token)))}
            data-testid="auth-submit-button"
          >
            {mutation.isPending ? t("login.working") : mode === "signup" ? t("login.btn.signup") : t("login.btn.signin")}
          </Button>
        </form>

        <button
          className="mt-4 w-full text-center text-xs text-muted-foreground transition-colors hover:text-foreground"
          onClick={() => {
            setFormError(null);
            setCbDismissed(true);
            setMode(mode === "signup" ? "login" : "signup");
          }}
          data-testid="auth-mode-toggle"
        >
          {mode === "signup" ? t("login.toggle.signin") : t("login.toggle.signup")}
        </button>
        <LegalLinks className="mt-6 justify-center" />
        <ServerNote />
        <p className="mt-3 text-center text-[11px] text-muted-foreground">
          ⚠️ {t("login.disclaimer")}
        </p>
      </div>
    </main>
  );
}
