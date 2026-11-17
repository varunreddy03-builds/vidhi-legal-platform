import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { toast } from "sonner";
import AppShell from "@/components/AppShell";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { apiPost } from "@/lib/api";
import { describe } from "@/lib/interaction";

type Choice<T extends string> = { value: T; label: string };
const DID: Choice<"yes" | "partly" | "no">[] = [{ value: "yes", label: "Yes" }, { value: "partly", label: "Partly" }, { value: "no", label: "No" }];
const UNDERSTOOD: Choice<"yes" | "mostly" | "no">[] = [{ value: "yes", label: "Yes" }, { value: "mostly", label: "Mostly" }, { value: "no", label: "No" }];
const WOULD: Choice<"yes" | "maybe" | "no">[] = [{ value: "yes", label: "Yes" }, { value: "maybe", label: "Maybe" }, { value: "no", label: "No" }];

function Radios<T extends string>({ name, label, options, value, onChange }: { name: string; label: string; options: Choice<T>[]; value: T | ""; onChange: (v: T) => void }) {
  return (
    <fieldset className="space-y-2">
      <legend className="text-sm font-medium">{label}</legend>
      <div className="flex flex-wrap gap-4">
        {options.map((o) => (
          <label key={o.value} className="flex min-h-10 items-center gap-2 text-sm">
            <input type="radio" name={name} className="size-4" checked={value === o.value} onChange={() => onChange(o.value)} data-testid={`pf-${name}-${o.value}`} />
            {o.label}
          </label>
        ))}
      </div>
    </fieldset>
  );
}

/** The pilot feedback form. Short on purpose: four choices and three free boxes. Pilot lawyers use sample or public drafts only, so nothing about a client belongs here. */
export default function PilotFeedback() {
  const [did, setDid] = useState<"yes" | "partly" | "no" | "">("");
  const [understood, setUnderstood] = useState<"yes" | "mostly" | "no" | "">("");
  const [trust, setTrust] = useState(0);
  const [would, setWould] = useState<"yes" | "maybe" | "no" | "">("");
  const [wrong, setWrong] = useState("");
  const [missing, setMissing] = useState("");
  const [other, setOther] = useState("");
  const [contact, setContact] = useState(false);
  const [sent, setSent] = useState(false);
  const ready = !!did && !!understood && trust >= 1 && !!would;
  const send = useMutation({
    mutationFn: () =>
      apiPost("/pilot/feedback", { did_task: did, understood_report: understood, trust, would_use: would, wrong_or_confusing: wrong, missing, other, can_contact: contact }),
    onSuccess: () => setSent(true),
    onError: (e) => toast.error(describe(e)),
  });
  return (
    <AppShell title="Pilot feedback">
      <div className="mx-auto max-w-xl" data-testid="pilot-feedback">
        {sent ? (
          <div className="glass rounded-2xl p-6" data-testid="pf-thanks">
            <h2 className="text-xl">Thank you.</h2>
            <p className="mt-2 text-sm text-muted-foreground">Your answers were saved. If a result was wrong, the button on that reference in the report is the best way to tell us exactly which one.</p>
          </div>
        ) : (
          <form
            className="space-y-6"
            onSubmit={(e) => {
              e.preventDefault();
              if (ready) send.mutate();
            }}
          >
            <p className="text-sm text-muted-foreground">Two minutes. Please do not write anything about a real client: use only what is in your sample or public draft.</p>
            <Radios name="did" label="Could you paste a draft and read the report?" options={DID} value={did} onChange={setDid} />
            <Radios name="understood" label="Did you understand why each reference got its label?" options={UNDERSTOOD} value={understood} onChange={setUnderstood} />
            <fieldset className="space-y-2">
              <legend className="text-sm font-medium">How much would you rely on this report? (1 = not at all, 5 = completely)</legend>
              <div className="flex gap-3">
                {[1, 2, 3, 4, 5].map((n) => (
                  <label key={n} className="flex min-h-10 items-center gap-1.5 text-sm">
                    <input type="radio" name="trust" className="size-4" checked={trust === n} onChange={() => setTrust(n)} data-testid={`pf-trust-${n}`} />
                    {n}
                  </label>
                ))}
              </div>
            </fieldset>
            <Radios name="would" label="Would you use it on your own drafts?" options={WOULD} value={would} onChange={setWould} />
            <div className="space-y-1.5">
              <Label htmlFor="pf-wrong">What was wrong or confusing?</Label>
              <Textarea id="pf-wrong" rows={3} maxLength={1000} value={wrong} onChange={(e) => setWrong(e.target.value)} data-testid="pf-wrong" />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="pf-missing">What is missing?</Label>
              <Textarea id="pf-missing" rows={3} maxLength={1000} value={missing} onChange={(e) => setMissing(e.target.value)} data-testid="pf-missing" />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="pf-other">Anything else?</Label>
              <Textarea id="pf-other" rows={2} maxLength={1000} value={other} onChange={(e) => setOther(e.target.value)} data-testid="pf-other" />
            </div>
            <label className="flex min-h-10 items-start gap-3 text-sm">
              <input type="checkbox" className="mt-1 size-4" checked={contact} onChange={(e) => setContact(e.target.checked)} data-testid="pf-contact" />
              You may contact me about these answers.
            </label>
            <Button type="submit" size="lg" className="w-full" loading={send.isPending} disabled={!ready} data-testid="pf-send">
              Send feedback
            </Button>
          </form>
        )}
      </div>
    </AppShell>
  );
}
