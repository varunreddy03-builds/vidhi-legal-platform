import { useRecoveryEnabled } from "@/lib/recovery/useRecoveryEnabled";
import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { apiGet, apiPost } from "@/lib/api";
import { formatDate, formatMoney } from "@/lib/format";
import { describe } from "@/lib/interaction";
import type { CheckoutResponse } from "@/lib/types";
import { useCan, useEntitlement } from "@/lib/useMe";

const PENDING = "vidhi-pending-payment";
const FREE_POINTS = [
  "Legal Recovery: everything, free",
  "Simple research questions and single-document reading",
  "Light, fast AI models",
];

/** Free vs Pro for VIDHI Legal Katalyst and research. Recovery is free for everyone. The server enforces every limit shown here. */
export default function PlanSection() {
  const { enabled: recoveryOn } = useRecoveryEnabled();
  const { data: ent } = useEntitlement();
  const canBilling = useCan("billing");
  const qc = useQueryClient();
  const refresh = async () => {
    await qc.invalidateQueries({ queryKey: ["entitlement"] });
  };

  const packages = useQuery({ queryKey: ["packages"], queryFn: () => apiGet<{ id: string; interval: string; providers: string[]; prices: Record<string, { amount: number; currency: string }> }[]>("/payments/packages") });
  const [yearly, setYearly] = useState(false); // offered only when the operator has set a yearly price
  const hasYearly = !!packages.data?.some((p) => p.id === "vidhi_pro_yearly");
  const pkg = packages.data?.find((p) => p.id === (yearly && hasYearly ? "vidhi_pro_yearly" : "vidhi_pro"));
  const providers = (pkg?.providers ?? []).filter((p) => pkg?.prices?.[p]);
  const per = pkg?.interval === "year" ? "year" : "month";
  const priceOf = (prov: string) => (pkg?.prices?.[prov] ? `${formatMoney(pkg.prices[prov].amount, pkg.prices[prov].currency)} / ${per}` : "");

  const checkout = useMutation({
    mutationFn: (provider: string) => apiPost<CheckoutResponse>("/payments/checkout", { package_id: pkg?.id ?? "vidhi_pro", origin_url: window.location.origin, provider }),
    onSuccess: (r, provider) => {
      if (provider === "razorpay") {
        try {
          localStorage.setItem(PENDING, r.session_id); // Razorpay cannot send the buyer back, so remember it and check on return
        } catch {
          /* private mode: the "check my payment" button simply will not appear */
        }
      }
      window.location.href = r.checkout_url;
    },
    onError: (e) => toast.error(describe(e)),
  });
  const pendingId = (() => {
    try {
      return localStorage.getItem(PENDING);
    } catch {
      return null;
    }
  })();
  const check = useMutation({
    mutationFn: (id: string) => apiGet<{ payment_status: string }>(`/payments/status/${id}`),
    onSuccess: async (r) => {
      if (r.payment_status === "paid") {
        try {
          localStorage.removeItem(PENDING);
        } catch {
          /* nothing to clear */
        }
        await refresh();
        toast.success("Payment received. Pro is now on.");
      } else toast.info("Not confirmed yet. If you have just paid, wait a minute and check again.");
    },
    onError: (e) => toast.error(describe(e)),
  });
  useEffect(() => {
    if (pendingId && ent && ent.plan !== "PRO") check.mutate(pendingId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pendingId, ent?.plan]);
  const cancel = useMutation({
    mutationFn: () => apiPost("/payments/subscription/cancel"),
    onSuccess: async () => {
      await refresh();
      toast.success("Cancelled. Pro stays until the end of the period you paid for.");
    },
    onError: (e) => toast.error(describe(e)),
  });
  const resume = useMutation({
    mutationFn: () => apiPost("/payments/subscription/resume"),
    onSuccess: async () => {
      await refresh();
      toast.success("Your subscription will renew as normal.");
    },
    onError: (e) => toast.error(describe(e)),
  });

  const lim = ent?.limits;
  const price = lim?.price;
  const isFirm = ent?.plan === "FIRM";
  const isPro = ent?.plan === "PRO" || isFirm; // a paid plan: no upgrade buttons
  const priceText = pkg?.prices ? (priceOf(providers[0] ?? "stripe") || (price ? `${formatMoney(price.amount, price.currency)} / ${per}` : "")) : price ? `${formatMoney(price.amount, price.currency)} / month` : "";
  const proPoints = [
    "Everything in Free",
    "Contract review and whole-matter analysis (who is who, where sources differ)",
    "The strongest AI models, chosen for each task",
    `Far more AI requests (${lim?.pro.ai_per_day ?? 500} a day) and the full document-reading budget`,
  ];

  return (
    <section className="glass rounded-lg p-5" data-testid="settings-plan">
      <h2 className="font-heading text-sm uppercase tracking-wider text-muted-foreground">Your plan</h2>
      <div className="mt-3 flex flex-wrap items-center gap-2">
        <Badge variant="outline" style={{ color: isPro ? "#5B8CFF" : "#C8A96B" }} data-testid="settings-plan-badge">
          {ent?.plan ?? "—"}
        </Badge>
        {isFirm && (
          <span className="text-xs text-muted-foreground" data-testid="plan-firm-note">
            Your organisation is on the Firm plan, set up by VIDHI{ent?.pro_until ? ` until ${formatDate(ent.pro_until)}` : ""}.
          </span>
        )}
        {isPro && !isFirm && ent?.pro_until && (
          <span className="text-xs text-muted-foreground" data-testid="plan-renewal">
            {ent.cancel_at_period_end
              ? `Cancelled: Pro ends on ${formatDate(ent.pro_until)}`
              : `Renews automatically around ${formatDate(ent.pro_until)}`}
          </span>
        )}
        {isPro && ent?.subscription_status === "past_due" && (
          <span className="text-xs" style={{ color: "#F0A63A" }}>
            The last payment did not go through. We will try again; if it keeps failing, Pro ends on the date above.
          </span>
        )}
      </div>

      {ent?.usage && (
        <p className="mt-3 text-sm" data-testid="plan-usage">
          Today: {ent.usage.ai_used_today} of {ent.usage.ai_limit_today} AI requests used by your organisation. People: {ent.usage.members_used}
          {ent.usage.members_limit != null ? ` of ${ent.usage.members_limit} allowed (invitations not yet accepted count)` : " (no limit on your plan)"}.
        </p>
      )}
      <div className="mt-4 grid grid-cols-1 gap-3 md:grid-cols-2">
        <div className="rounded-md border border-border p-4" style={!isPro ? { borderColor: "#C8A96B66" } : undefined} data-testid="plan-free-card">
          <p className="text-sm">Free</p>
          <p className="text-xs text-muted-foreground">
            {lim ? `${formatMoney(0, price?.currency ?? "inr")} · ${lim.free.ai_per_day} AI requests a day` : ""}
            {!isPro && ent?.ai_limit_today != null ? ` · used ${ent.ai_used_today} of ${ent.ai_limit_today} today` : ""}
          </p>
          <ul className="mt-2 space-y-1 text-xs text-muted-foreground">
            {FREE_POINTS.filter((p) => recoveryOn || !p.startsWith("Legal Recovery")).map((p) => (
              <li key={p}>• {p}</li>
            ))}
            {lim?.free.locked.map((p) => (
              <li key={p} style={{ color: "#F0A63A" }}>
                ✗ {p}: Pro only
              </li>
            ))}
          </ul>
          <p className="mt-2 text-xs text-muted-foreground">The free plan is for simple questions. It is not meant for complex matters.</p>
        </div>
        {lim?.firm && (
          <div className="rounded-md border border-border p-4 md:col-span-2" style={isFirm ? { borderColor: "#5B8CFF88" } : undefined} data-testid="plan-firm-card">
            <p className="text-sm">Firm</p>
            <p className="text-xs" style={{ color: "#5B8CFF" }}>
              {lim.firm.price ? `${formatMoney(lim.firm.price.amount, lim.firm.price.currency)} / month` : "Price to be announced"}
            </p>
            <ul className="mt-2 space-y-1 text-xs text-muted-foreground">
              <li>✓ Everything in Pro, for a whole firm</li>
              <li>✓ {lim.firm.ai_per_day} AI requests a day, shared by the organisation</li>
              <li>✓ {lim.firm.members_max != null ? `Up to ${lim.firm.members_max} people` : "No limit on people"}</li>
            </ul>
            <p className="mt-2 text-xs text-muted-foreground">There is no online checkout for the Firm plan yet. To ask for it, contact support.</p>
          </div>
        )}
        <div className="rounded-md border border-border p-4" style={isPro ? { borderColor: "#5B8CFF88" } : undefined} data-testid="plan-pro-card">
          <p className="text-sm">Pro</p>
          <p className="text-xs" style={{ color: "#5B8CFF" }}>{priceText}</p>
          <ul className="mt-2 space-y-1 text-xs text-muted-foreground">
            {proPoints.map((p) => (
              <li key={p}>✓ {p}</li>
            ))}
          </ul>
          {canBilling && !isPro && hasYearly && (
            <div className="mt-3 flex gap-2 text-xs" role="group" aria-label="Billing period">
              <Button size="xs" variant={yearly ? "outline" : "default"} onClick={() => setYearly(false)} data-testid="plan-monthly">Monthly</Button>
              <Button size="xs" variant={yearly ? "default" : "outline"} onClick={() => setYearly(true)} data-testid="plan-yearly">Yearly</Button>
            </div>
          )}
          {canBilling ? (
            <div className="mt-3 flex flex-wrap gap-2">
              {!isPro &&
                (providers.length ? providers : ["stripe"]).map((prov) => (
                  <Button
                    key={prov}
                    size="sm"
                    className="h-auto min-h-8 max-w-full whitespace-normal py-1.5 text-center" // a long label wraps on a phone instead of running off the screen
                    variant={prov === (providers[0] ?? "stripe") ? "default" : "outline"}
                    loading={checkout.isPending && checkout.variables === prov}
                    disabled={checkout.isPending}
                    onClick={() => checkout.mutate(prov)}
                    data-testid={`settings-upgrade-${prov}`}
                  >
                    {prov === "razorpay"
                      ? `Pay with UPI, card or netbanking (${priceOf(prov) || priceText})`
                      : prov === "paypal"
                        ? `Pay with PayPal (${priceOf(prov)})`
                        : providers.length > 1
                          ? `Pay by international card (${priceOf(prov) || priceText})`
                          : `Upgrade to Pro (${priceText})`}
                  </Button>
                ))}
              {!isPro && pendingId && (
                <Button size="sm" variant="ghost" loading={check.isPending} onClick={() => check.mutate(pendingId)} data-testid="check-payment">
                  I have finished paying: check my payment
                </Button>
              )}
              {isPro && ent?.subscription_status && !ent.cancel_at_period_end && (
                <Button size="sm" variant="outline" onClick={() => cancel.mutate()} disabled={cancel.isPending} data-testid="cancel-subscription">
                  Cancel subscription
                </Button>
              )}
              {isPro && ent?.cancel_at_period_end && (
                <Button size="sm" onClick={() => resume.mutate()} disabled={resume.isPending} data-testid="resume-subscription">
                  Keep my subscription
                </Button>
              )}
            </div>
          ) : (
            !isPro && <p className="mt-3 text-xs text-muted-foreground">Ask your organisation&apos;s owner to upgrade.</p>
          )}
        </div>
      </div>
      <p className="mt-3 text-xs text-muted-foreground">
        {recoveryOn ? "Legal Recovery is free for everyone. " : ""}Pro is billed {hasYearly ? "monthly or yearly" : "monthly"} through a secure payment page (UPI, cards or netbanking in India; PayPal or international cards elsewhere) and renews until you cancel; we never see or store your card or UPI details.
      </p>
    </section>
  );
}
