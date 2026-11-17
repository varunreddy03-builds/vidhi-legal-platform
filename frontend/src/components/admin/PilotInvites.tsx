import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { apiDelete, apiGet, apiPost } from "@/lib/api";
import { describe } from "@/lib/interaction";

type Invite = { id: string; email: string; created_at: string; expires_at: string; state: "open" | "used" | "revoked" | "expired" };
type Created = { code: string; link: string; emailed: boolean; email: string };

/** Pilot invitations (SIGNUP_MODE=invite): one single-use code per email address. The code is shown once, here, and in the email if you choose to send it. */
export default function PilotInvites() {
  const qc = useQueryClient();
  const [email, setEmail] = useState("");
  const [send, setSend] = useState(false);
  const [made, setMade] = useState<Created | null>(null);
  const list = useQuery({ queryKey: ["pilot-invites"], queryFn: () => apiGet<{ mode: "open" | "invite"; invites: Invite[] }>("/admin/pilot/invites") });
  const create = useMutation({
    mutationFn: () => apiPost<Created>("/admin/pilot/invites", { email, send_email: send }),
    onSuccess: (c) => {
      setMade({ ...c, email });
      setEmail("");
      void qc.invalidateQueries({ queryKey: ["pilot-invites"] });
    },
    onError: (e) => toast.error(describe(e)),
  });
  const revoke = useMutation({
    mutationFn: (id: string) => apiDelete(`/admin/pilot/invites/${id}`),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["pilot-invites"] }),
    onError: (e) => toast.error(describe(e)),
  });
  return (
    <div className="space-y-4" data-testid="pilot-invites">
      <p className="text-sm text-muted-foreground">
        {list.data?.mode === "invite" ? "Sign-up is invite-only: new accounts need an invitation." : "Sign-up is currently OPEN to anyone. Set SIGNUP_MODE=invite on the server to require invitations."} Each invitation works once, for one email address, for 14 days.
      </p>
      <form
        className="glass flex flex-col gap-3 rounded-lg p-4 sm:flex-row sm:items-end"
        onSubmit={(e) => {
          e.preventDefault();
          if (email.trim()) create.mutate();
        }}
      >
        <div className="flex-1">
          <Label htmlFor="pi-email">Email address to invite</Label>
          <Input id="pi-email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} required data-testid="pilot-invite-email" />
        </div>
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={send} onChange={(e) => setSend(e.target.checked)} data-testid="pilot-invite-send" />
          Email it to them
        </label>
        <Button type="submit" disabled={create.isPending || !email.trim()} data-testid="pilot-invite-create">
          Create invitation
        </Button>
      </form>
      {made && (
        <div className="glass rounded-lg p-4 text-sm" data-testid="pilot-invite-made">
          <p>
            Invitation for <strong>{made.email}</strong>{made.emailed ? " (emailed)" : ""}. Copy it now: the code is not shown again.
          </p>
          <p className="mt-1 break-all font-mono text-xs" data-testid="pilot-invite-link">
            {made.link}
          </p>
        </div>
      )}
      <ul className="space-y-2">
        {(list.data?.invites ?? []).map((i) => (
          <li key={i.id} className="glass flex flex-wrap items-center gap-3 rounded-lg p-3 text-sm" data-testid="pilot-invite-row">
            <span className="min-w-0 flex-1 truncate">{i.email}</span>
            <span className="text-xs text-muted-foreground">{i.state}</span>
            {i.state === "open" && (
              <Button size="xs" variant="outline" onClick={() => revoke.mutate(i.id)}>
                Cancel
              </Button>
            )}
          </li>
        ))}
        {list.data && list.data.invites.length === 0 && <li className="text-sm text-muted-foreground">No invitations yet.</li>}
      </ul>
    </div>
  );
}
