import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { apiPost, apiPut } from "@/lib/api";
import { describe } from "@/lib/interaction";
import type { AccountantContact, RecoveryCase } from "@/lib/types";

const LABEL: Record<AccountantContact["status"], { text: string; color: string }> = {
  PENDING: { text: "Waiting for them to confirm", color: "#F0A63A" },
  CONFIRMED: { text: "Confirmed", color: "#5B8CFF" },
  DECLINED: { text: "Declined — will not be emailed", color: "#E0604D" },
  BOUNCED: { text: "Could not be reached", color: "#E0604D" },
};

/** Nobody is copied on anything until they confirm by link. They can stop at any time. */
export default function AccountantsCard({
  c,
  caseId,
  onChanged,
  verified,
}: {
  c: RecoveryCase;
  caseId: string;
  onChanged: () => Promise<void>;
  verified: boolean;
}) {
  const [email, setEmail] = useState("");
  const contacts = c.accountants ?? [];

  const save = useMutation({
    mutationFn: (emails: string[]) => apiPut<RecoveryCase>(`/recovery/cases/${caseId}/accountants`, { emails }),
    onSuccess: async () => {
      await onChanged();
      setEmail("");
    },
    onError: (e) => toast.error(describe(e)),
  });

  const resend = useMutation({
    mutationFn: (address: string) => apiPost(`/recovery/cases/${caseId}/accountants/resend`, { email: address }),
    onSuccess: () => toast.success("Request sent again"),
    onError: (e) => toast.error(describe(e)),
  });

  const listWith = (extra?: string, without?: string) =>
    [...contacts.map((a) => a.email).filter((e) => e !== without), ...(extra ? [extra] : [])];

  return (
    <div className="mt-2" data-testid="accountant-recipients">
      <p className="text-xs text-muted-foreground">
        Accountants to copy on statements. We email them once to ask — they get nothing unless they say yes.
      </p>
      <form
        className="mt-1 flex flex-wrap items-center gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          if (email.trim()) save.mutate(listWith(email.trim().toLowerCase()));
        }}
      >
        <Input
          type="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          placeholder="Accountant's email address"
          className="h-7 w-72"
          disabled={!verified}
          data-testid="accountant-emails-input"
        />
        <Button size="xs" variant="outline" type="submit" disabled={save.isPending || !verified || !email.trim()} data-testid="accountant-emails-save">
          {save.isPending ? "Sending request…" : "Ask them to confirm"}
        </Button>
      </form>
      {!verified && (
        <p className="mt-1 text-xs" style={{ color: "#F0A63A" }}>
          Verify your own email address first (see the banner at the top).
        </p>
      )}
      {contacts.length > 0 && (
        <ul className="mt-2 space-y-1" data-testid="accountant-emails-list">
          {contacts.map((a) => (
            <li key={a.email} className="flex flex-wrap items-center gap-2 text-xs" data-testid="accountant-row">
              <span className="break-all">{a.email}</span>
              <span style={{ color: LABEL[a.status].color }}>{LABEL[a.status].text}</span>
              {a.status === "PENDING" && (
                <button
                  className="underline text-muted-foreground hover:text-foreground"
                  onClick={() => resend.mutate(a.email)}
                  disabled={resend.isPending}
                >
                  Send again
                </button>
              )}
              {a.status !== "DECLINED" && (
                <button
                  className="underline text-muted-foreground hover:text-foreground"
                  onClick={() => save.mutate(listWith(undefined, a.email))}
                  disabled={save.isPending}
                >
                  Remove
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
