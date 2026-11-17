import { useEffect, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { apiPatch } from "@/lib/api";
import { describe } from "@/lib/interaction";
import type { RecoveryCase } from "@/lib/types";

/** The facts a demand notice needs that we must never guess: both addresses, due date, optional interest. */
export default function CaseDetailsCard({
  c,
  caseId,
  onChanged,
}: {
  c: RecoveryCase;
  caseId: string;
  onChanged: () => Promise<void>;
}) {
  const [mine, setMine] = useState(c.creditor_address ?? "");
  const [theirs, setTheirs] = useState(c.debtor_address ?? "");
  const [due, setDue] = useState(c.due_date ?? "");
  const [rate, setRate] = useState(c.interest_rate_pct != null ? String(c.interest_rate_pct) : "");

  useEffect(() => {
    setMine(c.creditor_address ?? "");
    setTheirs(c.debtor_address ?? "");
    setDue(c.due_date ?? "");
    setRate(c.interest_rate_pct != null ? String(c.interest_rate_pct) : "");
  }, [c.creditor_address, c.debtor_address, c.due_date, c.interest_rate_pct]);

  const save = useMutation({
    mutationFn: () =>
      apiPatch<RecoveryCase>(`/recovery/cases/${caseId}/details`, {
        creditor_address: mine,
        debtor_address: theirs,
        due_date: due || undefined,
        clear_due_date: !due && !!c.due_date,
        interest_rate_pct: rate.trim() === "" ? undefined : Number(rate),
        clear_interest: rate.trim() === "" && c.interest_rate_pct != null,
      }),
    onSuccess: async () => {
      await onChanged();
      toast.success("Details saved");
    },
    onError: (e) => toast.error(describe(e)),
  });

  const ready = mine.trim() !== "" && theirs.trim() !== "";

  return (
    <div className="rounded-md border border-border p-4" data-testid="case-details">
      <p className="text-sm">Details for your notice</p>
      <p className="mt-1 text-xs text-muted-foreground">
        A notice has to say who it is from and where it is going. We never guess these.
      </p>
      <div className="mt-3 grid gap-3 md:grid-cols-2">
        <div className="space-y-1.5">
          <Label htmlFor="my-address">Your address</Label>
          <Textarea
            id="my-address"
            rows={3}
            value={mine}
            onChange={(e) => setMine(e.target.value)}
            maxLength={500}
            data-testid="creditor-address-input"
          />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="their-address">Their address</Label>
          <Textarea
            id="their-address"
            rows={3}
            value={theirs}
            onChange={(e) => setTheirs(e.target.value)}
            maxLength={500}
            data-testid="debtor-address-input"
          />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="due-date">Date the money was due (optional)</Label>
          <Input
            id="due-date"
            type="date"
            value={due}
            onChange={(e) => setDue(e.target.value)}
            data-testid="due-date-input"
          />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="rate">Interest rate, % a year (optional)</Label>
          <Input
            id="rate"
            type="number"
            min="0"
            max="100"
            step="0.01"
            value={rate}
            onChange={(e) => setRate(e.target.value)}
            data-testid="interest-rate-input"
          />
        </div>
      </div>
      <p className="mt-2 text-xs text-muted-foreground">
        Interest: leave empty to claim none. If you use a rate, use the one that was agreed in writing — we do not
        suggest one, and the notice will only claim interest if you enter a due date and a rate.
      </p>
      <Button
        size="sm"
        variant="outline"
        className="mt-3"
        onClick={() => save.mutate()}
        disabled={save.isPending}
        data-testid="save-details-button"
      >
        {save.isPending ? "Saving…" : "Save details"}
      </Button>
      {!ready && (
        <p className="mt-2 text-xs" style={{ color: "#F0A63A" }} data-testid="details-needed">
          Add both addresses before creating the notice.
        </p>
      )}
    </div>
  );
}
