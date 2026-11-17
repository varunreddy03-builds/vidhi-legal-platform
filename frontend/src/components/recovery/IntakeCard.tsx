import { useEffect, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { apiPatch } from "@/lib/api";
import { describe } from "@/lib/interaction";
import type { CaseCharge, CaseCredit, CaseIntake, RecoveryCase, Tri } from "@/lib/types";

const EMPTY: CaseIntake = {
  invoice_number: "",
  invoice_date: null,
  supply_description: "",
  payment_terms: "",
  creditor_email: "",
  creditor_phone: "",
  debtor_phone: "",
  promise_to_pay: { text: "", date: null },
  disputes: { invoice: false, quality: false, delivery: false, amount: false, note: "" },
  route: { cheque_given: null, cheque_bounced: null, msme: null, existing_proceedings: null, insolvency: null },
  response_days: 15,
};

const QUESTIONS: { key: keyof CaseIntake["route"]; text: string }[] = [
  { key: "cheque_given", text: "Did the customer give you a cheque for this?" },
  { key: "cheque_bounced", text: "Did a cheque from the customer bounce?" },
  { key: "msme", text: "Is your business a registered micro or small enterprise (for example with Udyam)?" },
  { key: "existing_proceedings", text: "Is there already a court case or complaint about this money?" },
  { key: "insolvency", text: "Is the customer in insolvency, closure or winding-up?" },
];

function YesNo({ value, onChange, id }: { value: Tri | null; onChange: (v: Tri | null) => void; id: string }) {
  return (
    <select
      id={id}
      className="h-8 rounded-md border border-border bg-background px-2 text-sm"
      value={value ?? ""}
      onChange={(e) => onChange((e.target.value || null) as Tri | null)}
    >
      <option value="">Not answered</option>
      <option value="yes">Yes</option>
      <option value="no">No</option>
      <option value="unsure">Not sure</option>
    </select>
  );
}

/** The facts only the owner knows: invoice, terms, disputes, credits and charges. Saved as typed, never guessed. */
export default function IntakeCard({
  c,
  caseId,
  onChanged,
}: {
  c: RecoveryCase;
  caseId: string;
  onChanged: () => Promise<void>;
}) {
  const [amount, setAmount] = useState(String(c.amount ?? ""));
  const [intake, setIntake] = useState<CaseIntake>({ ...EMPTY, ...(c.intake ?? {}) });
  const [credits, setCredits] = useState<CaseCredit[]>(c.credits ?? []);
  const [charges, setCharges] = useState<CaseCharge[]>(c.charges ?? []);
  const [debtorEmail, setDebtorEmail] = useState(c.debtor_email ?? "");

  useEffect(() => {
    setAmount(String(c.amount ?? ""));
    setIntake({ ...EMPTY, ...(c.intake ?? {}) });
    setCredits(c.credits ?? []);
    setCharges(c.charges ?? []);
    setDebtorEmail(c.debtor_email ?? "");
  }, [c.updated_at]); // eslint-disable-line react-hooks/exhaustive-deps

  const set = <K extends keyof CaseIntake>(k: K, v: CaseIntake[K]) => setIntake((i) => ({ ...i, [k]: v }));

  const save = useMutation({
    mutationFn: () =>
      apiPatch<RecoveryCase>(`/recovery/cases/${caseId}/intake`, {
        amount: Number(amount) || 0,
        debtor_email: debtorEmail,
        invoice_number: intake.invoice_number,
        invoice_date: intake.invoice_date || null,
        supply_description: intake.supply_description,
        payment_terms: intake.payment_terms,
        creditor_email: intake.creditor_email,
        creditor_phone: intake.creditor_phone,
        debtor_phone: intake.debtor_phone,
        promise_to_pay: intake.promise_to_pay,
        disputes: intake.disputes,
        route: intake.route,
        response_days: intake.response_days,
        credits: credits.filter((x) => x.label.trim() && x.amount > 0),
        charges: charges.filter((x) => x.label.trim() && x.amount > 0),
      }),
    onSuccess: async () => {
      await onChanged();
      toast.success("Details saved");
    },
    onError: (e) => toast.error(describe(e)),
  });

  const dispute = (k: "invoice" | "quality" | "delivery" | "amount", label: string) => (
    <label key={k} className="flex items-center gap-2 text-sm">
      <input
        type="checkbox"
        checked={intake.disputes[k]}
        onChange={(e) => set("disputes", { ...intake.disputes, [k]: e.target.checked })}
      />
      {label}
    </label>
  );

  return (
    <div className="space-y-5" data-testid="recovery-intake">
      <div className="grid gap-3 md:grid-cols-2">
        <div className="space-y-1.5">
          <Label htmlFor="inv-amount">Invoice amount ({c.currency})</Label>
          <Input id="inv-amount" type="number" min="0" step="0.01" value={amount} onChange={(e) => setAmount(e.target.value)} data-testid="intake-amount" />
          {c.detected_amount != null && Number(amount) !== c.detected_amount && (
            <p className="text-xs text-muted-foreground">
              Your documents seem to show {c.detected_amount.toLocaleString("en-IN")}.{" "}
              <button type="button" className="underline" onClick={() => setAmount(String(c.detected_amount))}>
                Use that amount
              </button>{" "}
              only if it is right.
            </p>
          )}
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="inv-no">Invoice number</Label>
          <Input id="inv-no" value={intake.invoice_number} onChange={(e) => set("invoice_number", e.target.value)} maxLength={60} data-testid="intake-invoice-number" />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="inv-date">Invoice date</Label>
          <Input id="inv-date" type="date" value={intake.invoice_date ?? ""} onChange={(e) => set("invoice_date", e.target.value || null)} />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="terms">Agreed payment terms</Label>
          <Input id="terms" placeholder="for example: payment within 30 days" value={intake.payment_terms} onChange={(e) => set("payment_terms", e.target.value)} maxLength={500} />
        </div>
      </div>
      <div className="space-y-1.5">
        <Label htmlFor="supplied">What did you supply? (goods or services)</Label>
        <Textarea id="supplied" rows={2} value={intake.supply_description} onChange={(e) => set("supply_description", e.target.value)} maxLength={1000} data-testid="intake-supplied" />
      </div>

      <div className="grid gap-3 md:grid-cols-3">
        <div className="space-y-1.5">
          <Label htmlFor="c-email">Your email (for the notice)</Label>
          <Input id="c-email" type="email" value={intake.creditor_email} onChange={(e) => set("creditor_email", e.target.value)} />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="c-phone">Your phone</Label>
          <Input id="c-phone" value={intake.creditor_phone} onChange={(e) => set("creditor_phone", e.target.value)} maxLength={30} />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="d-phone">Customer&apos;s phone</Label>
          <Input id="d-phone" value={intake.debtor_phone} onChange={(e) => set("debtor_phone", e.target.value)} maxLength={30} />
        </div>
        <div className="space-y-1.5 md:col-span-3">
          <Label htmlFor="d-email">Customer&apos;s email (if you have it)</Label>
          <Input id="d-email" type="email" value={debtorEmail} onChange={(e) => setDebtorEmail(e.target.value)} />
        </div>
      </div>

      <div>
        <p className="text-sm">Did the customer promise to pay, or admit owing, in writing?</p>
        <div className="mt-2 grid gap-3 md:grid-cols-[1fr_160px]">
          <Textarea
            rows={2}
            placeholder="What did they write? For example: “I will pay on 10 September” (then upload the message as proof)"
            value={intake.promise_to_pay.text}
            onChange={(e) => set("promise_to_pay", { ...intake.promise_to_pay, text: e.target.value })}
            maxLength={1000}
          />
          <Input type="date" value={intake.promise_to_pay.date ?? ""} onChange={(e) => set("promise_to_pay", { ...intake.promise_to_pay, date: e.target.value || null })} />
        </div>
      </div>

      <div>
        <p className="text-sm">Does the customer dispute anything?</p>
        <div className="mt-2 grid gap-1.5 md:grid-cols-2">
          {dispute("invoice", "The invoice itself")}
          {dispute("quality", "The quality of the goods or work")}
          {dispute("delivery", "That it was delivered or done")}
          {dispute("amount", "The amount")}
        </div>
        <Input
          className="mt-2"
          placeholder="In their words, what do they say? (optional)"
          value={intake.disputes.note}
          onChange={(e) => set("disputes", { ...intake.disputes, note: e.target.value })}
          maxLength={1000}
        />
      </div>

      <div>
        <p className="text-sm">Credits and extra charges</p>
        <p className="mt-1 text-xs text-muted-foreground">
          A credit (credit note, discount, return) lowers what is owed. An extra charge (for example agreed delivery cost) is
          only counted if you write down where it was agreed. Interest is set separately below.
        </p>
        {credits.map((cr, i) => (
          <div key={cr.id} className="mt-2 grid gap-2 md:grid-cols-[1fr_120px_1fr_auto]">
            <Input placeholder="Credit (for example: returned goods)" value={cr.label} onChange={(e) => setCredits(credits.map((x, j) => (j === i ? { ...x, label: e.target.value } : x)))} />
            <Input type="number" min="0" step="0.01" placeholder="Amount" value={cr.amount || ""} onChange={(e) => setCredits(credits.map((x, j) => (j === i ? { ...x, amount: Number(e.target.value) } : x)))} />
            <Input placeholder="Reason or credit note number" value={cr.reason} onChange={(e) => setCredits(credits.map((x, j) => (j === i ? { ...x, reason: e.target.value } : x)))} />
            <Button type="button" size="xs" variant="ghost" onClick={() => setCredits(credits.filter((_, j) => j !== i))}>
              Remove
            </Button>
          </div>
        ))}
        {charges.map((ch, i) => (
          <div key={ch.id} className="mt-2 grid gap-2 md:grid-cols-[1fr_120px_1fr_auto]">
            <Input placeholder="Extra charge (for example: delivery)" value={ch.label} onChange={(e) => setCharges(charges.map((x, j) => (j === i ? { ...x, label: e.target.value } : x)))} />
            <Input type="number" min="0" step="0.01" placeholder="Amount" value={ch.amount || ""} onChange={(e) => setCharges(charges.map((x, j) => (j === i ? { ...x, amount: Number(e.target.value) } : x)))} />
            <Input placeholder="Where was it agreed? (required)" value={ch.basis} onChange={(e) => setCharges(charges.map((x, j) => (j === i ? { ...x, basis: e.target.value } : x)))} />
            <Button type="button" size="xs" variant="ghost" onClick={() => setCharges(charges.filter((_, j) => j !== i))}>
              Remove
            </Button>
          </div>
        ))}
        <div className="mt-2 flex gap-2">
          <Button type="button" size="xs" variant="outline" onClick={() => setCredits([...credits, { id: crypto.randomUUID(), label: "", amount: 0, reason: "" }])}>
            Add a credit
          </Button>
          <Button type="button" size="xs" variant="outline" onClick={() => setCharges([...charges, { id: crypto.randomUUID(), label: "", amount: 0, basis: "" }])}>
            Add an extra charge
          </Button>
        </div>
      </div>

      <div>
        <p className="text-sm">A few questions that change what you should do</p>
        <div className="mt-2 space-y-2">
          {QUESTIONS.map((q) => (
            <div key={q.key} className="flex flex-wrap items-center justify-between gap-2">
              <label htmlFor={`q-${q.key}`} className="text-sm text-muted-foreground">
                {q.text}
              </label>
              <YesNo id={`q-${q.key}`} value={intake.route[q.key]} onChange={(v) => set("route", { ...intake.route, [q.key]: v })} />
            </div>
          ))}
        </div>
      </div>

      <div className="space-y-1.5 md:max-w-xs">
        <Label htmlFor="days">Days you give the customer to pay or reply</Label>
        <Input id="days" type="number" min={7} max={60} value={intake.response_days} onChange={(e) => set("response_days", Math.min(60, Math.max(7, Number(e.target.value) || 15)))} />
      </div>

      <Button onClick={() => save.mutate()} disabled={save.isPending} data-testid="intake-save">
        {save.isPending ? "Saving…" : "Save these details"}
      </Button>
    </div>
  );
}
