import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Smartphone } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { apiDelete, apiGet, apiPatch, apiPost } from "@/lib/api";
import { describe } from "@/lib/interaction";

type PhoneState = { available: boolean; channels: string[]; verified: boolean; last4: string | null; channel: string | null; alerts: boolean };

/** Opt-in SMS or WhatsApp alerts to YOUR OWN phone. Alerts never contain names or amounts and are never sent to a customer. */
export default function PhoneAlertsSection() {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["phone"], queryFn: () => apiGet<PhoneState>("/auth/phone") });
  const [phone, setPhone] = useState("");
  const [channel, setChannel] = useState("sms");
  const [code, setCode] = useState("");
  const [sent, setSent] = useState(false);
  const done = (r: PhoneState) => qc.setQueryData(["phone"], r);

  const start = useMutation({
    mutationFn: () => apiPost("/auth/phone/start", { phone, channel }),
    onSuccess: () => {
      setSent(true);
      toast.success("We sent you a code.");
    },
    onError: (e) => toast.error(describe(e)),
  });
  const verify = useMutation({
    mutationFn: () => apiPost<PhoneState>("/auth/phone/verify", { code }),
    onSuccess: (r) => {
      done(r);
      setSent(false);
      setCode("");
      setPhone("");
      toast.success("Phone added. Alerts are on.");
    },
    onError: (e) => toast.error(describe(e)),
  });
  const toggle = useMutation({ mutationFn: (alerts: boolean) => apiPatch<PhoneState>("/auth/phone", { alerts }), onSuccess: done, onError: (e) => toast.error(describe(e)) });
  const remove = useMutation({
    mutationFn: () => apiDelete("/auth/phone"),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["phone"] }),
    onError: (e) => toast.error(describe(e)),
  });

  const s = q.data;
  if (!s?.available) return null; // hidden until the installation has Twilio set up

  return (
    <section className="glass rounded-lg p-5" data-testid="settings-phone">
      <h2 className="flex items-center gap-2 font-heading text-sm uppercase tracking-wider text-muted-foreground">
        <Smartphone className="size-4" /> Phone alerts
      </h2>
      <p className="mt-2 text-sm text-muted-foreground">
        Get a short text when something changes on a case, such as a notice being delivered. Texts never include names or amounts, and VIDHI never texts
        the person who owes you money. Reply STOP to a text to switch them off.
      </p>

      {s.verified ? (
        <div className="mt-4 flex flex-wrap items-center gap-3">
          <span className="text-sm">
            {s.channel === "whatsapp" ? "WhatsApp" : "SMS"} to a number ending {s.last4}
          </span>
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={s.alerts} onChange={(e) => toggle.mutate(e.target.checked)} data-testid="phone-alerts-toggle" />
            Alerts on
          </label>
          <Button size="sm" variant="outline" onClick={() => remove.mutate()} loading={remove.isPending}>
            Remove my number
          </Button>
        </div>
      ) : !sent ? (
        <div className="mt-4 flex flex-wrap items-center gap-2">
          <Input value={phone} onChange={(e) => setPhone(e.target.value)} placeholder="+91 98765 43210" inputMode="tel" className="max-w-56" data-testid="phone-input" />
          {s.channels.length > 1 && (
            <select aria-label="How to send alerts" className="h-9 rounded-md border border-border bg-background px-2 text-sm" value={channel} onChange={(e) => setChannel(e.target.value)}>
              <option value="sms">SMS</option>
              <option value="whatsapp">WhatsApp</option>
            </select>
          )}
          <Button size="sm" loading={start.isPending} disabled={phone.trim().length < 8} onClick={() => start.mutate()} data-testid="phone-send-code">
            Send me a code
          </Button>
        </div>
      ) : (
        <div className="mt-4 flex flex-wrap items-center gap-2">
          <Input value={code} onChange={(e) => setCode(e.target.value)} placeholder="6-digit code" inputMode="numeric" autoComplete="one-time-code" className="max-w-40" data-testid="phone-code" />
          <Button size="sm" loading={verify.isPending} disabled={code.trim().length !== 6} onClick={() => verify.mutate()} data-testid="phone-verify">
            Confirm
          </Button>
          <Button size="sm" variant="ghost" onClick={() => setSent(false)}>
            Use another number
          </Button>
        </div>
      )}
    </section>
  );
}