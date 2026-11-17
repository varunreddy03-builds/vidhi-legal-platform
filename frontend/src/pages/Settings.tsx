import { useRecoveryEnabled } from "@/lib/recovery/useRecoveryEnabled";
import { useEffect, useRef, useState } from "react";
import { openApiFile } from "@/lib/files";
import { formatDateTime, formatMoney } from "@/lib/format";
import { Link, useNavigate } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import AppShell from "@/components/AppShell";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { apiGet, apiPost, apiPatch, apiDelete, apiUpload } from "@/lib/api";
import type { PaymentTransaction } from "@/lib/types";
import { useMe, useCan } from "@/lib/useMe";
import SecuritySection from "@/components/settings/SecuritySection";
import TeamSection from "@/components/settings/TeamSection";
import DirectorySection from "@/components/settings/DirectorySection";
import DataPrivacySection from "@/components/settings/DataPrivacySection";
import AiUsageMeter from "@/components/settings/AiUsageMeter";
import PlanSection from "@/components/settings/PlanSection";
import { AppearanceSection } from "@/components/AppearanceControls";
import TwoStepSection from "@/components/settings/TwoStepSection";
import PhoneAlertsSection from "@/components/settings/PhoneAlertsSection";
import SessionsSection from "@/components/settings/SessionsSection";
import { endSession } from "@/lib/session";
import { describe } from "@/lib/interaction";

export default function Settings() {
  const { enabled: recoveryOn } = useRecoveryEnabled();
  const { data: me } = useMe();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const canBilling = useCan("billing");
  const canAdmin = useCan("admin");

  const billing = useQuery<PaymentTransaction[]>({
    queryKey: ["payment-history"],
    queryFn: () => apiGet<PaymentTransaction[]>("/payments/history"),
    enabled: canBilling,
  });

  const logo = useQuery<{ has_logo: boolean; data_url: string | null }>({
    queryKey: ["org-logo"],
    queryFn: () => apiGet<{ has_logo: boolean; data_url: string | null }>("/org/logo"),
  });

  const branding = useQuery<{
    firm_name: string;
    firm_address: string;
    has_logo: boolean;
    data_url: string | null;
  }>({
    queryKey: ["org-branding"],
    queryFn: () =>
      apiGet<{ firm_name: string; firm_address: string; has_logo: boolean; data_url: string | null }>(
        "/org/branding",
      ),
  });
  const [firmName, setFirmName] = useState("");
  const [firmAddress, setFirmAddress] = useState("");
  useEffect(() => {
    if (branding.data) {
      setFirmName(branding.data.firm_name);
      setFirmAddress(branding.data.firm_address);
    }
  }, [branding.data?.firm_name, branding.data?.firm_address]);
  const saveBranding = useMutation({
    mutationFn: () =>
      apiPatch<{ firm_name: string }>("/org/branding", {
        firm_name: firmName,
        firm_address: firmAddress,
      }),
    onSuccess: async () => {
      await qc.invalidateQueries({ queryKey: ["org-branding"] });
      toast.success("Firm details saved — they print on notices and statements");
    },
    onError: (e) => toast.error(describe(e)),
  });

  const logoRef = useRef<HTMLInputElement>(null);
  const uploadLogo = useMutation({
    mutationFn: (file: File) => apiUpload<{ has_logo: boolean }>("/org/logo", file),
    onSuccess: async () => {
      await qc.invalidateQueries({ queryKey: ["org-logo"] });
      toast.success("Logo saved — it will appear on receipts, notices and statements");
    },
    onError: (e) => toast.error(describe(e)),
  });
  const removeLogo = useMutation({
    mutationFn: () => apiDelete<{ has_logo: boolean }>("/org/logo"),
    onSuccess: async () => {
      await qc.invalidateQueries({ queryKey: ["org-logo"] });
      toast.success("Logo removed");
    },
    onError: (e) => toast.error(describe(e)),
  });

  const resendReceipt = useMutation({
    mutationFn: (sessionId: string) =>
      apiPost<{ ok: boolean; sent_to: string }>(`/payments/receipt/${sessionId}/email`),
    onSuccess: (r) => toast.success(`Receipt emailed to ${r.sent_to}`),
    onError: (e) => toast.error(describe(e)),
  });

  return (
    <AppShell title="Settings">
      <div className="mx-auto max-w-3xl space-y-6">
        <section className="glass rounded-lg p-5">
          <h2 className="font-heading text-sm uppercase tracking-wider text-muted-foreground">
            Profile
          </h2>
          <p className="mt-3 text-sm" data-testid="settings-email">
            {me?.full_name} · {me?.email}
          </p>
          <p className="text-xs text-muted-foreground">
            {me?.role} of {me?.organization_name}
          </p>
          <Button
            variant="outline"
            size="sm"
            className="mt-4"
            data-testid="settings-signout"
            onClick={async () => {
              await endSession();
              navigate("/login", { replace: true });
            }}
          >
            Sign out
          </Button>
        </section>

        <AppearanceSection />
        <TwoStepSection />
        <SessionsSection />
        <PhoneAlertsSection />
        <PlanSection />
        <AiUsageMeter />

        <SecuritySection />
        {me && canAdmin && <TeamSection me={me} />}
        {me && me.capabilities.includes("send_mail") && <DirectorySection />}
        {me && canAdmin && <DataPrivacySection me={me} />}

        {canAdmin && (
        <section className="glass rounded-lg p-5" data-testid="settings-branding">
          <h2 className="font-heading text-sm uppercase tracking-wider text-muted-foreground">
            Firm branding
          </h2>
          <p className="mt-2 text-xs text-muted-foreground">
            Your logo, firm name and address print at the top of receipts, demand notices and
            statements.
          </p>
          <div className="mt-3 flex items-center gap-4">
            {logo.data?.has_logo && logo.data.data_url ? (
              <img
                src={logo.data.data_url}
                alt="Firm logo"
                className="h-12 w-auto max-w-[160px] rounded border border-border bg-white/5 p-1"
                data-testid="org-logo-preview"
              />
            ) : (
              <span className="text-xs text-muted-foreground">No logo yet.</span>
            )}
            <input
              ref={logoRef}
              type="file"
              accept=".png,.jpg,.jpeg,.webp"
              className="hidden"
              data-testid="org-logo-input"
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) uploadLogo.mutate(f);
                e.target.value = "";
              }}
            />
            <Button
              size="sm"
              variant="outline"
              onClick={() => logoRef.current?.click()}
              disabled={uploadLogo.isPending}
              data-testid="org-logo-upload"
            >
              {uploadLogo.isPending ? "Uploading…" : logo.data?.has_logo ? "Replace logo" : "Upload logo"}
            </Button>
            {logo.data?.has_logo && (
              <Button
                size="sm"
                variant="ghost"
                onClick={() => removeLogo.mutate()}
                disabled={removeLogo.isPending}
                data-testid="org-logo-remove"
              >
                Remove
              </Button>
            )}
          </div>
          <div className="mt-4 grid gap-3">
            <div>
              <label className="text-xs text-muted-foreground">Firm name</label>
              <Input
                value={firmName}
                onChange={(e) => setFirmName(e.target.value)}
                placeholder="Firm or practice name"
                className="mt-1"
                data-testid="firm-name-input"
              />
            </div>
            <div>
              <label className="text-xs text-muted-foreground">Firm address</label>
              <Textarea
                value={firmAddress}
                onChange={(e) => setFirmAddress(e.target.value)}
                placeholder="Street, city, PIN"
                className="mt-1"
                rows={3}
                data-testid="firm-address-input"
              />
            </div>
            <div>
              <Button
                size="sm"
                variant="outline"
                onClick={() => saveBranding.mutate()}
                disabled={saveBranding.isPending}
                data-testid="firm-branding-save"
              >
                {saveBranding.isPending ? "Saving…" : "Save firm details"}
              </Button>
            </div>
            <div
              className="rounded-md border border-border bg-background/40 p-4"
              data-testid="branding-preview"
            >
              <p className="text-xs uppercase tracking-wider text-muted-foreground">
                Letterhead preview
              </p>
              <div className="mt-2">
                {logo.data?.data_url && (
                  <img
                    src={logo.data.data_url}
                    alt="Firm logo"
                    className="h-10 w-auto max-w-[160px] object-contain"
                  />
                )}
                {firmName && <p className="mt-1 text-sm font-semibold">{firmName}</p>}
                {firmAddress && (
                  <p className="whitespace-pre-line text-xs text-muted-foreground">{firmAddress}</p>
                )}
                {!logo.data?.data_url && !firmName && !firmAddress && (
                  <p className="text-xs text-muted-foreground">
                    Add a logo, name or address to see your letterhead.
                  </p>
                )}
              </div>
            </div>
          </div>
        </section>

        )}

        {canBilling && (
        <section className="glass rounded-lg p-5" data-testid="settings-billing">
          <h2 className="font-heading text-sm uppercase tracking-wider text-muted-foreground">
            Billing history
          </h2>
          <div className="mt-3 space-y-2">
            {(billing.data ?? []).map((t) => (
              <div
                key={t.session_id}
                className="flex items-center justify-between gap-3 rounded-md border border-border px-3 py-2"
                data-testid="billing-row"
              >
                <div className="min-w-0">
                  <p className="text-sm">
                    VIDHI Pro · {formatMoney(t.amount, t.currency)}
                  </p>
                  <p className="text-xs text-muted-foreground">
                    {formatDateTime(t.created_at)} · {t.payment_status}
                    {t.card_brand && t.card_last4
                      ? ` · ${t.card_brand.toUpperCase()} ••${t.card_last4}`
                      : ""}
                  </p>
                </div>
                {t.payment_status === "paid" && (
                  <div className="flex gap-1.5">
                    <Button
                      size="xs"
                      variant="outline"
                      onClick={() =>
                        openApiFile(`/api/payments/receipt/${t.session_id}.pdf`)
                      }
                      data-testid="billing-receipt-button"
                    >
                      Receipt
                    </Button>
                    <Button
                      size="xs"
                      variant="outline"
                      onClick={() => resendReceipt.mutate(t.session_id)}
                      disabled={resendReceipt.isPending}
                      data-testid="billing-email-receipt-button"
                    >
                      Email
                    </Button>
                  </div>
                )}
              </div>
            ))}
            {!billing.isLoading && (billing.data ?? []).length === 0 && (
              <p className="text-sm text-muted-foreground">No payments yet.</p>
            )}
          </div>
        </section>
        )}

        {recoveryOn && (
          <section className="glass rounded-lg p-5" data-testid="settings-more">
            <h2 className="font-heading text-sm uppercase tracking-wider text-muted-foreground">More</h2>
            <Link to="/recovery" className="mt-3 flex min-h-12 items-center justify-between gap-3 rounded-lg border border-border px-4 text-sm hover:bg-accent" data-testid="settings-recovery-link">
              <span>
                Legal Recovery
                <span className="block text-xs text-muted-foreground">Help for someone who is owed money: proof, a demand notice, and a lawyer's review.</span>
              </span>
              <span aria-hidden="true">→</span>
            </Link>
          </section>
        )}

        <section className="glass rounded-lg p-5">
          <h2 className="font-heading text-sm uppercase tracking-wider text-muted-foreground">
            Jurisdiction plugin
          </h2>
          <p className="mt-3 text-sm">India (IN) · plugin v1.0.0 · first-class jurisdiction</p>
          <p className="text-xs text-muted-foreground">
            Citation rules, court hierarchy and source hierarchy are resolved per matter.
          </p>
        </section>


      </div>
    </AppShell>
  );
}
