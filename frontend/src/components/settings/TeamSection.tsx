import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { apiDelete, apiGet, apiPatch, apiPost } from "@/lib/api";
import { formatDate } from "@/lib/format";
import { describe } from "@/lib/interaction";
import type { UserOut } from "@/lib/types";

type Role = UserOut["role"];
interface Member {
  id: string;
  email: string;
  full_name: string;
  role: Role;
  email_verified: boolean;
  you: boolean;
}
interface Invite {
  id: string;
  email: string;
  role: Role;
  expires_at: string;
}

const ROLE_HELP: Record<Role, string> = {
  OWNER: "Everything, including billing and erasing the organisation",
  ADMIN: "Team, firm settings, data export, deletion; no billing",
  LAWYER: "Works on matters and cases, uses AI, emails third parties",
  MEMBER: "Can view and add records; no AI, no emailing, no deleting",
  CLIENT: "A client of the firm: sees only what you share with them from a matter (read-only)",
};

/** Owners manage everyone; admins only lawyers and members (the server enforces the same rule). */
export default function TeamSection({ me }: { me: UserOut }) {
  const qc = useQueryClient();
  const isOwner = me.role === "OWNER";
  const assignable: Role[] = isOwner ? ["OWNER", "ADMIN", "LAWYER", "MEMBER"] : ["LAWYER", "MEMBER"];
  const manageable = (r: Role) => assignable.includes(r) || r === "CLIENT"; // clients can be removed, never re-roled: they are invited from a matter
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<Role>("LAWYER");

  const members = useQuery<Member[]>({ queryKey: ["org-members"], queryFn: () => apiGet<Member[]>("/org/members") });
  const invites = useQuery<Invite[]>({ queryKey: ["org-invites"], queryFn: () => apiGet<Invite[]>("/org/invites") });
  const refresh = async () => {
    await qc.invalidateQueries({ queryKey: ["org-members"] });
    await qc.invalidateQueries({ queryKey: ["org-invites"] });
  };

  const invite = useMutation({
    mutationFn: () => apiPost("/org/invites", { email, role }),
    onSuccess: async () => {
      toast.success(`Invitation sent to ${email}`);
      setEmail("");
      await refresh();
    },
    onError: (e) => toast.error(describe(e)),
  });
  const changeRole = useMutation({
    mutationFn: (v: { id: string; role: Role }) => apiPatch(`/org/members/${v.id}`, { role: v.role }),
    onSuccess: refresh,
    onError: (e) => toast.error(describe(e)),
  });
  const remove = useMutation({
    mutationFn: (id: string) => apiDelete(`/org/members/${id}`),
    onSuccess: async () => {
      toast.success("Member removed and signed out everywhere");
      await refresh();
    },
    onError: (e) => toast.error(describe(e)),
  });
  const cancel = useMutation({
    mutationFn: (id: string) => apiDelete(`/org/invites/${id}`),
    onSuccess: refresh,
    onError: (e) => toast.error(describe(e)),
  });

  return (
    <section className="glass rounded-lg p-5" data-testid="settings-team">
      <h2 className="font-heading text-sm uppercase tracking-wider text-muted-foreground">Team</h2>
      <div className="mt-3 space-y-2">
        {(members.data ?? []).map((m) => (
          <div key={m.id} className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-border px-3 py-2" data-testid="member-row">
            <div className="min-w-0">
              <p className="truncate text-sm">
                {m.full_name || m.email} {m.you && <span className="text-xs text-muted-foreground">(you)</span>}
              </p>
              <p className="truncate text-xs text-muted-foreground">{m.email}</p>
            </div>
            <div className="flex items-center gap-2">
              {m.you || !manageable(m.role) || m.role === "CLIENT" ? (
                <Badge variant="outline">{m.role}</Badge>
              ) : (
                <select
                  className="h-7 rounded-md border border-border bg-background px-2 text-xs"
                  value={m.role}
                  onChange={(e) => changeRole.mutate({ id: m.id, role: e.target.value as Role })}
                  aria-label={`Role of ${m.email}`}
                >
                  {assignable.map((r) => (
                    <option key={r} value={r}>
                      {r}
                    </option>
                  ))}
                </select>
              )}
              {!m.you && manageable(m.role) && (
                <Button
                  size="xs"
                  variant="outline"
                  disabled={remove.isPending}
                  onClick={() => {
                    if (window.confirm(`Remove ${m.email}? They are signed out immediately; their work stays.`)) remove.mutate(m.id);
                  }}
                >
                  Remove
                </Button>
              )}
            </div>
          </div>
        ))}
      </div>

      {(invites.data ?? []).length > 0 && (
        <div className="mt-4">
          <p className="text-xs uppercase tracking-wider text-muted-foreground">Waiting to join</p>
          <div className="mt-2 space-y-2">
            {(invites.data ?? []).map((i) => (
              <div key={i.id} className="flex items-center justify-between gap-2 rounded-md border border-border px-3 py-2" data-testid="invite-row">
                <p className="min-w-0 truncate text-sm">
                  {i.email} · {i.role} <span className="text-xs text-muted-foreground">expires {formatDate(i.expires_at)}</span>
                </p>
                {manageable(i.role) && (
                  <Button size="xs" variant="ghost" onClick={() => cancel.mutate(i.id)} disabled={cancel.isPending}>
                    Cancel
                  </Button>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      <form
        className="mt-4 flex flex-wrap items-end gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          invite.mutate();
        }}
      >
        <div className="min-w-[200px] flex-1">
          <label className="text-xs text-muted-foreground">Invite by email</label>
          <Input type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="name@firm.in" className="mt-1" required data-testid="invite-email" />
        </div>
        <div>
          <label className="text-xs text-muted-foreground">Role</label>
          <select
            className="mt-1 block h-8 rounded-md border border-border bg-background px-2 text-sm"
            value={role}
            onChange={(e) => setRole(e.target.value as Role)}
            data-testid="invite-role"
            aria-label="Role for the person you are inviting"
          >
            {assignable.map((r) => (
              <option key={r} value={r}>
                {r}
              </option>
            ))}
          </select>
        </div>
        <Button type="submit" size="sm" variant="outline" disabled={invite.isPending} data-testid="invite-send">
          {invite.isPending ? "Sending…" : "Send invitation"}
        </Button>
      </form>
      <p className="mt-2 text-xs text-muted-foreground">{ROLE_HELP[role]}. The invitation link works once and expires in 7 days.</p>
      {!me.email_verified && (
        <p className="mt-1 text-xs text-muted-foreground">Confirm your own email address first: it is needed to send invitations.</p>
      )}
    </section>
  );
}
