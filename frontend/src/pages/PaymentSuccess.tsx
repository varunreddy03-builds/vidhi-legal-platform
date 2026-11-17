import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import NervousSystemBackground from "@/components/NervousSystemBackground";
import { buttonVariants } from "@/components/ui/button";
import { apiGet } from "@/lib/api";
import type { PaymentStatusResponse } from "@/lib/types";

export default function PaymentSuccess() {
  const [params] = useSearchParams();
  const sid = params.get("session_id") ?? params.get("subscription_id"); // PayPal returns ?subscription_id=...
  const qc = useQueryClient();
  const [state, setState] = useState<"checking" | "paid" | "pending" | "error">("checking");

  useEffect(() => {
    if (!sid) {
      setState("error");
      return;
    }
    let tries = 0;
    let active = true;
    async function poll() {
      if (!active) return;
      try {
        const r = await apiGet<PaymentStatusResponse>(`/payments/status/${sid}`);
        if (r.payment_status === "paid") {
          setState("paid");
          await qc.invalidateQueries({ queryKey: ["entitlement"] });
          await qc.invalidateQueries({ queryKey: ["me"] });
          return;
        }
      } catch {
        /* keep polling */
      }
      tries += 1;
      if (tries >= 10) {
        setState("pending");
        return;
      }
      setTimeout(poll, 2000);
    }
    poll();
    return () => {
      active = false;
    };
  }, [sid, qc]);

  return (
    <div className="relative flex min-h-screen items-center justify-center px-4">
      <NervousSystemBackground intensity={state === "checking" ? "active" : "ambient"} />
      <div className="glass relative z-10 w-full max-w-md rounded-xl p-8 text-center" data-testid="payment-success">
        {state === "checking" && (
          <>
            <h1 className="text-xl">Confirming your payment…</h1>
            <p className="mt-2 text-sm text-muted-foreground">This takes a few seconds.</p>
            <div className="mx-auto mt-4 h-2 w-40 rounded vidhi-sweep" />
          </>
        )}
        {state === "paid" && (
          <>
            <div className="text-3xl" style={{ color: "#5B8CFF" }}>
              ◈
            </div>
            <h1 className="mt-3 text-2xl">You&apos;re on VIDHI Pro</h1>
            <p className="mt-2 text-sm text-muted-foreground">
              Pro is fully unlocked: contract review, whole-matter analysis and the strongest
              models. Pro renews monthly until you cancel it in Settings.
            </p>
            <Link to="/dashboard" className={buttonVariants({ className: "mt-5" })} data-testid="payment-go-dashboard">
              Go to dashboard
            </Link>
          </>
        )}
        {state === "pending" && (
          <>
            <h1 className="text-xl">Payment is processing</h1>
            <p className="mt-2 text-sm text-muted-foreground">
              It hasn&apos;t confirmed yet. Your plan will update automatically once it does.
            </p>
            <Link to="/settings" className={buttonVariants({ variant: "outline", className: "mt-5" })}>
              Back to settings
            </Link>
          </>
        )}
        {state === "error" && (
          <>
            <h1 className="text-xl">Something went wrong</h1>
            <p className="mt-2 text-sm text-muted-foreground">We couldn&apos;t find that payment.</p>
            <Link to="/settings" className={buttonVariants({ variant: "outline", className: "mt-5" })}>
              Back to settings
            </Link>
          </>
        )}
      </div>
    </div>
  );
}
