import { useRecoveryEnabled } from "@/lib/recovery/useRecoveryEnabled";
import { useEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import NervousSystemBackground from "@/components/NervousSystemBackground";
import { buttonVariants } from "@/components/ui/button";
import { apiPost } from "@/lib/api";
import { describe } from "@/lib/interaction";

/** Landing page for the emailed "confirm your email address" link. */
export default function VerifyEmail() {
  const { enabled: recoveryOn } = useRecoveryEnabled();
  const [params] = useSearchParams();
  const token = params.get("token");
  const qc = useQueryClient();
  const [state, setState] = useState<"working" | "ok" | "error">(token ? "working" : "error");
  const [message, setMessage] = useState(token ? "" : "This link is not complete.");
  // The link works once. React may run this effect twice in development; submitting the token twice
  // would show the second ("already used") answer, so submit exactly once per token.
  const submitted = useRef<string | null>(null);

  useEffect(() => {
    if (!token || submitted.current === token) return;
    submitted.current = token;
    apiPost("/auth/verify-email", { token })
      .then(async () => {
        await qc.invalidateQueries({ queryKey: ["me"] });
        setState("ok");
      })
      .catch((e) => {
        setMessage(describe(e));
        setState("error");
      });
  }, [token, qc]);

  return (
    <main id="main-content" className="relative flex min-h-screen items-center justify-center px-4">
      <NervousSystemBackground intensity="ambient" />
      <div className="glass relative z-10 w-full max-w-md rounded-xl p-8 text-center" data-testid="verify-email-page">
        {state === "working" && <h1 className="text-xl">Confirming your email…</h1>}
        {state === "ok" && (
          <>
            <h1 className="text-xl">Your email address is confirmed</h1>
            <p className="mt-2 text-sm text-muted-foreground">You can now send notices and statements from VIDHI.</p>
            <Link to={recoveryOn ? "/recovery" : "/start"} className={buttonVariants({ className: "mt-5" })}>
              Continue
            </Link>
          </>
        )}
        {state === "error" && (
          <>
            <h1 className="text-xl">We could not confirm that</h1>
            <p className="mt-2 text-sm text-muted-foreground">{message}</p>
            <Link to="/settings" className={buttonVariants({ variant: "outline", className: "mt-5" })}>
              Go to your account
            </Link>
          </>
        )}
      </div>
    </main>
  );
}
